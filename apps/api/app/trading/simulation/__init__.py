"""Simulation package for historical replay, virtual clock, and backtesting."""

from app.trading.simulation.clock import (
    VALID_PLAYBACK_SPEEDS,
    InvalidStateTransitionError,
    SimulationClock,
    SimulationClockError,
    SimulationClockStatus,
    SimulationLifecycleState,
    StepCallback,
)
from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    DuplicateTimestampError,
    EmptyDatasetError,
    OutOfOrderCandleError,
    ReplayContext,
    ReplayError,
    ReplayStepResult,
    ReplaySummary,
    StrategyCallable,
    load_historical_candles_from_db,
)
from app.trading.simulation.schemas import (
    DecisionResponse,
    PerformanceMetricsResponse,
    SimulationCreateRequest,
    SimulationResponse,
    TradeResponse,
)
from app.trading.simulation.service import (
    SimulationService,
    SimulationSession,
    get_simulation_service,
)

__all__ = [
    "VALID_PLAYBACK_SPEEDS",
    "ChronologicalReplayEngine",
    "DecisionResponse",
    "DuplicateTimestampError",
    "EmptyDatasetError",
    "InvalidStateTransitionError",
    "OutOfOrderCandleError",
    "PerformanceMetricsResponse",
    "ReplayContext",
    "ReplayError",
    "ReplayStepResult",
    "ReplaySummary",
    "SimulationClock",
    "SimulationClockError",
    "SimulationClockStatus",
    "SimulationCreateRequest",
    "SimulationLifecycleState",
    "SimulationResponse",
    "SimulationService",
    "SimulationSession",
    "StepCallback",
    "StrategyCallable",
    "TradeResponse",
    "get_simulation_service",
    "load_historical_candles_from_db",
]
