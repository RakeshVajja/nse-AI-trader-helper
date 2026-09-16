"""Persistence service for recording agent decision cycles and telemetry (Phase 8C).

Records:
1. AgentDecision record in database (id, agent_id, simulation_id, action, confidence, etc.)
2. AgentToolCall records for each tool invoked during the cycle
3. AgentUsage record tracking token consumption, latency, and estimated cost

Enforces:
- No chain-of-thought, internal prompt artifacts, or raw SDK types persisted
- Strictly typed database entity mapping
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.trading.agent.cycle.schemas import DecisionCycleResult

logger = logging.getLogger(__name__)


async def persist_cycle_result(
    db: AsyncSession,
    result: DecisionCycleResult,
) -> Optional[models.AgentDecision]:
    """Persist decision cycle outcomes, tool execution records, and token telemetry to PostgreSQL."""
    if result.decision is None:
        # If no decision was produced (e.g. error or max turns), only persist usage if tokens consumed
        if result.total_tokens > 0:
            usage = models.AgentUsage(
                agent_id=result.agent_id,
                simulation_id=result.simulation_id,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                latency_ms=result.total_latency_ms,
                estimated_cost_usd=0.0,
            )
            db.add(usage)
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return None

    # Map decision action to database enum
    db_action = models.AgentAction(result.decision.action.value)

    db_decision = models.AgentDecision(
        id=result.cycle_id,
        agent_id=result.agent_id,
        simulation_id=result.simulation_id,
        candle_timestamp=result.candle_timestamp,
        action=db_action,
        confidence=result.decision.confidence,
        quantity=result.decision.quantity,
        stop_loss=result.decision.stop_loss,
        take_profit=result.decision.take_profit,
        reason=result.decision.reason,
        observations=list(result.decision.observations),
        tools_used=list(result.decision.tools_used),
        market_regime=None,
    )
    db.add(db_decision)

    # Persist tool execution records
    for tex in result.tool_executions:
        tool_call_record = models.AgentToolCall(
            decision_id=result.cycle_id,
            agent_id=result.agent_id,
            tool_name=tex.tool_name,
            tool_args=tex.arguments,
            tool_result=tex.data or ({"error": tex.error} if tex.error else {}),
            execution_time_ms=tex.execution_time_ms,
        )
        db.add(tool_call_record)

    # Persist token and latency usage accounting
    usage = models.AgentUsage(
        agent_id=result.agent_id,
        simulation_id=result.simulation_id,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        latency_ms=result.total_latency_ms,
        estimated_cost_usd=0.0,
    )
    db.add(usage)

    try:
        await db.commit()
        await db.refresh(db_decision)
        return db_decision
    except Exception:
        await db.rollback()
        raise
