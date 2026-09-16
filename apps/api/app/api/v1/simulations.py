"""Simulation REST API Endpoints (Phase 6D).

Exposes endpoints for creating, controlling, stepping, and inspecting historical simulations
with database persistence in PostgreSQL and lifecycle coordination via SimulationClock.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.trading.simulation.schemas import (
    DecisionResponse,
    PerformanceMetricsResponse,
    SimulationCreateRequest,
    SimulationResponse,
    TradeResponse,
)
from app.trading.simulation.service import SimulationService, get_simulation_service

router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post(
    "",
    response_model=SimulationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new historical simulation run",
    description=(
        "Initialize an isolated historical replay session and persist initial configuration "
        "to PostgreSQL after verifying dataset availability."
    ),
)
async def create_simulation(
    req: SimulationCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Create simulation from configuration."""
    return await service.create_simulation(db=db, req=req)


@router.get(
    "/{id}",
    response_model=SimulationResponse,
    summary="Get current simulation state",
    description="Retrieve authoritative simulation lifecycle status, virtual clock time, progress, and metrics.",
)
async def get_simulation(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Retrieve simulation state."""
    return await service.get_simulation(simulation_id=id, db=db)


@router.post(
    "/{id}/start",
    response_model=SimulationResponse,
    summary="Start simulation playback",
    description="Transition from CREATED to RUNNING and launch background asynchronous playback task.",
)
async def start_simulation(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Start playback."""
    return await service.start_simulation(simulation_id=id, db=db)


@router.post(
    "/{id}/pause",
    response_model=SimulationResponse,
    summary="Pause active simulation playback",
    description="Transition from RUNNING to PAUSED and synchronize progress/metrics to PostgreSQL.",
)
async def pause_simulation(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Pause playback."""
    return await service.pause_simulation(simulation_id=id, db=db)


@router.post(
    "/{id}/resume",
    response_model=SimulationResponse,
    summary="Resume paused simulation playback",
    description="Transition from PAUSED to RUNNING and resume background playback task.",
)
async def resume_simulation(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Resume playback."""
    return await service.resume_simulation(simulation_id=id, db=db)


@router.post(
    "/{id}/step",
    response_model=SimulationResponse,
    summary="Advance simulation by one candle step",
    description="Advance exactly one candle cycle while PAUSED and synchronize progress to database.",
)
async def step_simulation(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Step forward one candle."""
    return await service.step_simulation(simulation_id=id, db=db)


@router.post(
    "/{id}/stop",
    response_model=SimulationResponse,
    summary="Stop simulation playback",
    description="Cleanly terminate playback, finalize portfolio state, and transition to terminal STOPPED.",
)
async def stop_simulation(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationResponse:
    """Stop simulation."""
    return await service.stop_simulation(simulation_id=id, db=db)


@router.get(
    "/{id}/trades",
    response_model=List[TradeResponse],
    summary="Get simulation executed trades",
    description="Retrieve all completed and closed trades for the simulation.",
)
async def get_simulation_trades(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> List[TradeResponse]:
    """Retrieve trades."""
    return await service.get_simulation_trades(simulation_id=id, db=db)


@router.get(
    "/{id}/performance",
    response_model=PerformanceMetricsResponse,
    summary="Get simulation performance metrics",
    description="Retrieve comprehensive performance summary matching Section 58 of specification.",
)
async def get_simulation_performance(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> PerformanceMetricsResponse:
    """Retrieve performance metrics."""
    return await service.get_simulation_performance(simulation_id=id, db=db)


@router.get(
    "/{id}/decisions",
    response_model=List[DecisionResponse],
    summary="Get simulation strategy decisions",
    description="Retrieve chronological strategy decision events (BUY, SELL, HOLD) for the simulation.",
)
async def get_simulation_decisions(
    id: str,
    db: AsyncSession = Depends(get_db_session),
    service: SimulationService = Depends(get_simulation_service),
) -> List[DecisionResponse]:
    """Retrieve decisions."""
    return await service.get_simulation_decisions(simulation_id=id, db=db)
