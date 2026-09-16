"""Agent Management REST API Endpoints (Phase 9C).

Exposes endpoints for compiling natural language strategy prompts into mandates,
confirming and persisting agents, inspecting agent configurations, managing lifecycle
states (start, pause, resume, stop), and deleting agents.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.agent import Agent, AgentConfig, AgentStatus
from app.database.models.market import Instrument
from app.database.models.trading import SimulationRun, SimulationStatus
from app.database.session import get_db_session
from app.trading.agent.gemini import GeminiClient
from app.trading.agent.mandate.generator import generate_mandate_async
from app.trading.agent.mandate.schemas import (
    AgentCreateRequest,
    AgentListResponse,
    AgentMandateCreateRequest,
    AgentMandateResponse,
    AgentResponse,
    AgentStatusResponse,
    AgentUpdateRequest,
)
from app.trading.agent.mandate.service import get_or_create_instrument
from app.trading.simulation.service import SimulationService, get_simulation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

ACTIVE_AGENT_STATUSES = [
    AgentStatus.CREATED,
    AgentStatus.READY,
    AgentStatus.RUNNING,
    AgentStatus.PAUSED,
    AgentStatus.ANALYZING,
    AgentStatus.WAITING,
]


def get_gemini_client() -> GeminiClient:
    """Dependency provider for GeminiClient."""
    return GeminiClient()


async def get_simulation_service_dep() -> SimulationService:
    """Dependency provider for SimulationService executed on the asyncio event loop."""
    return get_simulation_service()


def _build_agent_response(
    agent: Agent,
    instrument_symbol: str,
    simulation_id: Optional[str] = None,
    message: Optional[str] = None,
) -> AgentResponse:
    """Convert Agent ORM entity + Instrument symbol into typed AgentResponse."""
    config = agent.config
    strategy_style = config.strategy_style if config else "custom"
    objectives = list(config.objectives) if config and config.objectives else []
    preferred_indicators = (
        list(config.preferred_indicators) if config and config.preferred_indicators else []
    )
    raw_mandate = config.raw_mandate if config and isinstance(config.raw_mandate, dict) else {}
    rationale = agent.description or (
        raw_mandate.get("rationale") if isinstance(raw_mandate, dict) else None
    )

    return AgentResponse(
        agent_id=agent.id,
        id=agent.id,
        name=agent.name,
        status=agent.status,
        instrument=instrument_symbol,
        timeframe=agent.timeframe,
        initial_capital=agent.initial_capital,
        max_risk_per_trade=agent.max_risk_per_trade,
        max_position_exposure=agent.max_position_exposure,
        max_daily_loss=agent.max_daily_loss,
        strategy_prompt=agent.strategy_prompt,
        strategy_style=strategy_style,
        objectives=objectives,
        preferred_indicators=preferred_indicators,
        raw_mandate=raw_mandate,
        rationale=rationale,
        simulation_id=simulation_id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        message=message,
    )


@router.post(
    "/mandate",
    response_model=AgentMandateResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Agent Mandate from natural language prompt",
    description=(
        "Compiles a natural language trading strategy and optional risk overrides "
        "into a structured, validated AgentMandate via Gemini LLM."
    ),
)
async def generate_mandate_endpoint(
    req: AgentMandateCreateRequest,
    client: GeminiClient = Depends(get_gemini_client),
) -> AgentMandateResponse:
    """Compile natural language strategy prompt into a structured AgentMandate."""
    try:
        resp = await generate_mandate_async(client, req)
    except Exception as exc:
        logger.exception("Unexpected error during mandate generation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate agent mandate due to an internal server error.",
        ) from exc

    if not resp.success or resp.mandate is None:
        error_msg = (
            resp.error or "Failed to compile natural language strategy into a valid mandate."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    return resp


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and confirm an AI trading agent",
    description=(
        "Persists the confirmed agent configuration and structured mandate atomically into PostgreSQL. "
        "The agent is initialized with READY status, prepared for simulation."
    ),
)
async def create_agent_endpoint(
    req: AgentCreateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Confirm and persist agent configuration atomically."""
    # 1. Enforce active agent name uniqueness
    existing_stmt = select(Agent.id).where(
        Agent.name == req.agent_name,
        Agent.status.in_(ACTIVE_AGENT_STATUSES),
    )
    existing_res = await db.execute(existing_stmt)
    if existing_res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active agent with name '{req.agent_name}' already exists.",
        )

    # 2. Check associated simulation if requested
    sim_obj: Optional[SimulationRun] = None
    if req.simulation_id:
        sim_stmt = select(SimulationRun).where(SimulationRun.id == req.simulation_id)
        sim_res = await db.execute(sim_stmt)
        sim_obj = sim_res.scalar_one_or_none()
        if sim_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Associated simulation '{req.simulation_id}' not found.",
            )
        if sim_obj.agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Simulation '{req.simulation_id}' is already associated with another agent.",
            )
        if sim_obj.status in (
            SimulationStatus.RUNNING,
            SimulationStatus.COMPLETED,
            SimulationStatus.STOPPED,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot associate agent with simulation in status '{sim_obj.status.value}'.",
            )

    try:
        # 3. Resolve target Instrument
        instrument = await get_or_create_instrument(db, req.mandate.instrument)

        # 4. Determine strategy_prompt fallback
        strategy_prompt = (
            req.strategy_prompt
            or req.mandate.rationale
            or f"Declarative {req.mandate.strategy_style} strategy for {req.agent_name} on {req.mandate.instrument}"
        )

        # 5. Instantiate Agent
        agent = Agent(
            name=req.agent_name,
            description=req.description or req.mandate.rationale,
            status=AgentStatus.READY,
            instrument_id=instrument.id,
            timeframe=req.mandate.timeframe,
            initial_capital=req.initial_capital,
            max_risk_per_trade=req.mandate.risk_per_trade,
            max_position_exposure=req.mandate.max_position_exposure,
            max_daily_loss=req.mandate.max_daily_loss,
            strategy_prompt=strategy_prompt,
        )
        db.add(agent)
        await db.flush()

        # 6. Instantiate AgentConfig (Structured Mandate)
        config = AgentConfig(
            agent_id=agent.id,
            strategy_style=req.mandate.strategy_style,
            objectives=req.mandate.objectives,
            preferred_indicators=req.mandate.preferred_indicators,
            raw_mandate=req.mandate.model_dump(mode="json"),
        )
        db.add(config)

        # 7. Associate simulation if provided
        if sim_obj is not None:
            sim_obj.agent_id = agent.id

        await db.commit()
        await db.refresh(agent)
        return _build_agent_response(
            agent,
            instrument.symbol,
            simulation_id=req.simulation_id,
            message="Agent confirmed and initialized successfully.",
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Failed to persist confirmed agent")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist agent configuration.",
        ) from exc


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List agents with optional filtering",
    description="Retrieve paginated list of trading agents, optionally filtered by lifecycle status.",
)
async def list_agents_endpoint(
    status: Optional[AgentStatus] = Query(None, description="Filter agents by lifecycle status"),
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db_session),
) -> AgentListResponse:
    """List agents with optional status filter and pagination."""
    query = select(Agent, Instrument.symbol).join(Instrument, Agent.instrument_id == Instrument.id)
    count_query = select(func.count(Agent.id))

    if status is not None:
        query = query.where(Agent.status == status)
        count_query = count_query.where(Agent.status == status)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one() or 0

    query = query.order_by(Agent.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(query)
    rows = res.all()

    agents_list = []
    for agent_row, inst_symbol in rows:
        sim_stmt = (
            select(SimulationRun.id)
            .where(SimulationRun.agent_id == agent_row.id)
            .order_by(SimulationRun.created_at.desc())
            .limit(1)
        )
        sim_res = await db.execute(sim_stmt)
        sim_id = sim_res.scalar_one_or_none()
        agents_list.append(_build_agent_response(agent_row, inst_symbol, simulation_id=sim_id))

    return AgentListResponse(agents=agents_list, total=total, count=len(agents_list))


@router.get(
    "/{id}",
    response_model=AgentResponse,
    summary="Get agent details by ID",
    description="Retrieve authoritative configuration, structured mandate, and lifecycle status of a specific agent.",
)
async def get_agent_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Retrieve an agent by ID."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    return _build_agent_response(agent, inst_symbol, simulation_id=sim_id)


@router.get(
    "/{id}/status",
    response_model=AgentStatusResponse,
    summary="Get agent lifecycle status",
    description="Retrieve current authoritative lifecycle status of an agent.",
)
async def get_agent_status_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
) -> AgentStatusResponse:
    """Retrieve agent status."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    return AgentStatusResponse(
        agent_id=agent.id,
        name=agent.name,
        status=agent.status,
        instrument=inst_symbol,
        timeframe=agent.timeframe,
        simulation_id=sim_id,
        updated_at=agent.updated_at,
    )


@router.patch(
    "/{id}",
    response_model=AgentResponse,
    summary="Update mutable agent metadata",
    description=(
        "Update mutable presentation fields (name, description). "
        "Quantitative risk parameters and strategy mandate remain immutable."
    ),
)
async def update_agent_endpoint(
    id: str,
    req: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
) -> AgentResponse:
    """Update mutable agent metadata."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    if req.name is not None and req.name != agent.name:
        existing_stmt = select(Agent.id).where(
            Agent.name == req.name,
            Agent.id != id,
            Agent.status.in_(ACTIVE_AGENT_STATUSES),
        )
        existing_res = await db.execute(existing_stmt)
        if existing_res.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An active agent with name '{req.name}' already exists.",
            )
        agent.name = req.name

    if req.description is not None:
        agent.description = req.description

    await db.commit()
    await db.refresh(agent)

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    return _build_agent_response(
        agent,
        inst_symbol,
        simulation_id=sim_id,
        message="Agent updated successfully.",
    )


@router.post(
    "/{id}/start",
    response_model=AgentResponse,
    summary="Start an agent",
    description="Transition agent lifecycle status to RUNNING.",
)
async def start_agent_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    sim_service: SimulationService = Depends(get_simulation_service_dep),
) -> AgentResponse:
    """Start an agent."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    if agent.status == AgentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a completed agent.",
        )
    if agent.status in (AgentStatus.RUNNING, AgentStatus.ANALYZING, AgentStatus.WAITING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is already running.",
        )
    if agent.status == AgentStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is paused. Use /resume to continue execution.",
        )

    agent.status = AgentStatus.RUNNING
    await db.commit()
    await db.refresh(agent)

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    if sim_id and sim_id in getattr(sim_service, "_sessions", {}):
        try:
            session = sim_service._sessions[sim_id]
            if session.clock.state.value == "CREATED":
                await sim_service.start_simulation(sim_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start linked simulation %s: %s", sim_id, exc)

    return _build_agent_response(
        agent,
        inst_symbol,
        simulation_id=sim_id,
        message="Agent started successfully.",
    )


@router.post(
    "/{id}/pause",
    response_model=AgentResponse,
    summary="Pause a running agent",
    description="Transition agent lifecycle status from RUNNING to PAUSED.",
)
async def pause_agent_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    sim_service: SimulationService = Depends(get_simulation_service_dep),
) -> AgentResponse:
    """Pause an agent."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    if agent.status not in (AgentStatus.RUNNING, AgentStatus.ANALYZING, AgentStatus.WAITING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent is not running (current status: {agent.status.value}).",
        )

    agent.status = AgentStatus.PAUSED
    await db.commit()
    await db.refresh(agent)

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    if sim_id and sim_id in getattr(sim_service, "_sessions", {}):
        try:
            await sim_service.pause_simulation(sim_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to pause linked simulation %s: %s", sim_id, exc)

    return _build_agent_response(
        agent,
        inst_symbol,
        simulation_id=sim_id,
        message="Agent paused successfully.",
    )


@router.post(
    "/{id}/resume",
    response_model=AgentResponse,
    summary="Resume a paused agent",
    description="Transition agent lifecycle status from PAUSED to RUNNING.",
)
async def resume_agent_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    sim_service: SimulationService = Depends(get_simulation_service_dep),
) -> AgentResponse:
    """Resume an agent."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    if agent.status != AgentStatus.PAUSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent is not paused (current status: {agent.status.value}).",
        )

    agent.status = AgentStatus.RUNNING
    await db.commit()
    await db.refresh(agent)

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    if sim_id and sim_id in getattr(sim_service, "_sessions", {}):
        try:
            await sim_service.resume_simulation(sim_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resume linked simulation %s: %s", sim_id, exc)

    return _build_agent_response(
        agent,
        inst_symbol,
        simulation_id=sim_id,
        message="Agent resumed successfully.",
    )


@router.post(
    "/{id}/stop",
    response_model=AgentResponse,
    summary="Stop an agent",
    description="Transition agent lifecycle status to COMPLETED.",
)
async def stop_agent_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    sim_service: SimulationService = Depends(get_simulation_service_dep),
) -> AgentResponse:
    """Stop an agent."""
    stmt = (
        select(Agent, Instrument.symbol)
        .join(Instrument, Agent.instrument_id == Instrument.id)
        .where(Agent.id == id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )
    agent, inst_symbol = row[0], row[1]

    if agent.status == AgentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is already completed.",
        )

    agent.status = AgentStatus.COMPLETED
    await db.commit()
    await db.refresh(agent)

    sim_stmt = (
        select(SimulationRun.id)
        .where(SimulationRun.agent_id == agent.id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    )
    sim_res = await db.execute(sim_stmt)
    sim_id = sim_res.scalar_one_or_none()

    if sim_id and sim_id in getattr(sim_service, "_sessions", {}):
        try:
            await sim_service.stop_simulation(sim_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to stop linked simulation %s: %s", sim_id, exc)

    return _build_agent_response(
        agent,
        inst_symbol,
        simulation_id=sim_id,
        message="Agent stopped successfully.",
    )


@router.delete(
    "/{id}",
    summary="Delete an agent",
    description="Delete an inactive agent and all associated configurations.",
)
async def delete_agent_endpoint(
    id: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete an agent."""
    stmt = select(Agent).where(Agent.id == id)
    res = await db.execute(stmt)
    agent = res.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{id}' not found.",
        )

    if agent.status in (AgentStatus.RUNNING, AgentStatus.ANALYZING, AgentStatus.WAITING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a running agent. Please stop or pause the agent first.",
        )

    # Disassociate linked simulations to explicitly clear foreign key across all dialects
    await db.execute(
        update(SimulationRun).where(SimulationRun.agent_id == id).values(agent_id=None)
    )

    await db.delete(agent)
    await db.commit()
    return {"success": True, "message": f"Agent '{id}' deleted successfully."}
