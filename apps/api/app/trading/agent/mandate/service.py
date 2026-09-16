"""Persistence and service layer linking Phase 8B Agent Mandates to database models."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.agent import Agent, AgentConfig, AgentStatus, AgentUsage
from app.database.models.market import Instrument, InstrumentType
from app.trading.agent.gemini import GeminiClient, GeminiErrorType
from app.trading.agent.mandate.constants import (
    DEFAULT_INITIAL_CAPITAL,
    SUPPORTED_INDICES,
)
from app.trading.agent.mandate.generator import generate_mandate_async
from app.trading.agent.mandate.schemas import (
    AgentMandateCreateRequest,
    AgentMandateResponse,
)

logger = logging.getLogger(__name__)


async def get_or_create_instrument(db: AsyncSession, symbol: str) -> Instrument:
    """Retrieve an instrument by symbol, or create it if absent in development/test."""
    stmt = select(Instrument).where(Instrument.symbol == symbol)
    result = await db.execute(stmt)
    inst = result.scalar_one_or_none()
    if inst is not None:
        return inst

    inst_type = (
        InstrumentType.INDEX
        if symbol in SUPPORTED_INDICES or "NIFTY" in symbol
        else InstrumentType.EQUITY
    )
    new_inst = Instrument(
        symbol=symbol,
        name=f"{symbol} Stock" if inst_type == InstrumentType.EQUITY else f"{symbol} Index",
        exchange="NSE",
        instrument_type=inst_type,
        is_active=True,
    )
    db.add(new_inst)
    await db.flush()
    return new_inst


async def create_agent_with_mandate(
    db: AsyncSession,
    client: GeminiClient,
    request: AgentMandateCreateRequest,
) -> Tuple[Optional[Agent], AgentMandateResponse]:
    """Compile natural-language strategy into a mandate and persist the Agent and AgentConfig.

    Lifecycle:
    - Generates and validates AgentMandate via GeminiClient.
    - If generation fails, returns (None, error_response) with zero database mutations.
    - If valid, persists Agent with status CREATED and links structured AgentConfig.
    - Records Gemini token usage telemetry in AgentUsage.
    """
    mandate_resp = await generate_mandate_async(client, request)
    if not mandate_resp.success or mandate_resp.mandate is None:
        return None, mandate_resp

    mandate = mandate_resp.mandate

    try:
        # 1. Resolve Instrument
        instrument = await get_or_create_instrument(db, mandate.instrument)

        # 2. Instantiate Agent
        agent = Agent(
            name=request.agent_name,
            description=mandate.rationale,
            status=AgentStatus.CREATED,
            instrument_id=instrument.id,
            timeframe=mandate.timeframe,
            initial_capital=request.initial_capital or DEFAULT_INITIAL_CAPITAL,
            max_risk_per_trade=mandate.risk_per_trade,
            max_position_exposure=mandate.max_position_exposure,
            max_daily_loss=mandate.max_daily_loss,
            strategy_prompt=request.strategy_prompt,
        )
        db.add(agent)
        await db.flush()

        # 3. Instantiate AgentConfig (Structured Mandate)
        config = AgentConfig(
            agent_id=agent.id,
            strategy_style=mandate.strategy_style,
            objectives=mandate.objectives,
            preferred_indicators=mandate.preferred_indicators,
            raw_mandate=mandate.model_dump(mode="json"),
        )
        db.add(config)

        # 4. Record Token Consumption Telemetry
        usage = AgentUsage(
            agent_id=agent.id,
            simulation_id=None,
            prompt_tokens=mandate_resp.prompt_tokens,
            completion_tokens=mandate_resp.completion_tokens,
            total_tokens=mandate_resp.total_tokens,
            latency_ms=mandate_resp.latency_ms,
            estimated_cost_usd=0.0,
        )
        db.add(usage)

        await db.commit()
        await db.refresh(agent)

        # Attach agent_id to response envelope
        enriched_resp = AgentMandateResponse(
            success=True,
            mandate=mandate,
            agent_id=agent.id,
            prompt_tokens=mandate_resp.prompt_tokens,
            completion_tokens=mandate_resp.completion_tokens,
            total_tokens=mandate_resp.total_tokens,
            latency_ms=mandate_resp.latency_ms,
            error=None,
            error_type=None,
        )
        return agent, enriched_resp
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.error("Database persistence failed during agent creation: %s", exc)
        return None, AgentMandateResponse(
            success=False,
            mandate=mandate,
            prompt_tokens=mandate_resp.prompt_tokens,
            completion_tokens=mandate_resp.completion_tokens,
            total_tokens=mandate_resp.total_tokens,
            latency_ms=mandate_resp.latency_ms,
            error=f"Database persistence failed: {exc}",
            error_type=GeminiErrorType.API_ERROR,
        )
