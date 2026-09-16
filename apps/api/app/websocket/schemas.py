"""Pydantic v2 schemas for Phase 10A WebSocket real-time event streaming.

Strictly aligned with Sections 51 and 52 of PROJECT_SPECIFICATION.md.
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SimulationEventType(str, enum.Enum):
    """Authoritative event types defined in Section 52 of specification."""

    CANDLE_UPDATE = "candle_update"
    AGENT_STARTED = "agent_started"
    AGENT_ANALYZING = "agent_analyzing"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AGENT_DECISION = "agent_decision"
    RISK_CHECK = "risk_check"
    ORDER_EXECUTED = "order_executed"
    POSITION_UPDATED = "position_updated"
    PORTFOLIO_UPDATED = "portfolio_updated"
    SIMULATION_COMPLETE = "simulation_complete"
    ERROR = "error"
    INITIAL_STATE = "initial_state"


class SimulationEvent(BaseModel):
    """Unified event envelope for real-time WebSocket communication."""

    model_config = ConfigDict(extra="forbid")

    event_type: SimulationEventType = Field(
        ...,
        description="Categorized event type matching Section 52",
    )
    simulation_id: str = Field(
        ...,
        description="ID of the simulation session emitting this event",
    )
    sequence: int = Field(
        ...,
        ge=1,
        description="Monotonically increasing sequence number per simulation",
    )
    virtual_timestamp: Optional[str] = Field(
        default=None,
        description="Virtual market/simulation time in ISO 8601 UTC format",
    )
    wall_clock_timestamp: str = Field(
        ...,
        description="Real-world wall-clock emission time in ISO 8601 UTC format",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured event-specific payload",
    )


# ----------------------------------------------------------------------
# Event-Specific Typed Payloads
# ----------------------------------------------------------------------


class CandleDataPayload(BaseModel):
    """Payload representing a single OHLCV candle bar."""

    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleUpdatePayload(BaseModel):
    """Payload for 'candle_update' event."""

    step_index: int
    candle: CandleDataPayload


class AgentStartedPayload(BaseModel):
    """Payload for 'agent_started' event."""

    agent_id: str
    agent_name: str
    status: str
    strategy_style: Optional[str] = None


class AgentAnalyzingPayload(BaseModel):
    """Payload for 'agent_analyzing' event."""

    agent_id: str
    candle_timestamp: str
    step_index: int


class ToolCallPayload(BaseModel):
    """Payload for 'tool_call' event (sanitized)."""

    agent_id: str
    tool_name: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)


class ToolResultPayload(BaseModel):
    """Payload for 'tool_result' event (sanitized)."""

    agent_id: str
    tool_name: str
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AgentDecisionPayload(BaseModel):
    """Payload for 'agent_decision' event."""

    agent_id: Optional[str] = None
    action: str
    confidence: float
    quantity: Optional[int] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str
    market_regime: Optional[str] = None


class RiskCheckPayload(BaseModel):
    """Payload for 'risk_check' event."""

    order_id: str
    passed: bool
    reason: str
    side: Optional[str] = None
    quantity: Optional[int] = None
    risk_parameters: Optional[Dict[str, Any]] = None


class OrderExecutedPayload(BaseModel):
    """Payload for 'order_executed' event."""

    order_id: str
    trade_id: Optional[str] = None
    side: str
    quantity: int
    execution_price: float
    market_price: Optional[float] = None
    slippage_cost: float = 0.0
    transaction_cost: float = 0.0
    status: str
    rejection_reason: Optional[str] = None
    is_auto_exit: bool = False


class PositionItemPayload(BaseModel):
    """Payload for an individual open position."""

    symbol: str
    quantity: int
    average_entry_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    is_open: bool = True


class PositionUpdatedPayload(BaseModel):
    """Payload for 'position_updated' event."""

    positions: List[PositionItemPayload] = Field(default_factory=list)


class PortfolioUpdatedPayload(BaseModel):
    """Payload for 'portfolio_updated' event."""

    cash: float
    portfolio_value: float
    gross_pnl: float
    net_pnl: float
    total_return_pct: float
    exposure_pct: float
    open_positions_count: int


class SimulationCompletePayload(BaseModel):
    """Payload for 'simulation_complete' event."""

    status: str = "COMPLETED"
    total_steps: int
    final_portfolio_value: float
    total_return_pct: float
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    """Payload for 'error' event."""

    code: str
    message: str


class InitialStatePayload(BaseModel):
    """Payload sent immediately upon WebSocket connection."""

    simulation_id: str
    status: str
    symbol: str
    timeframe: str
    step_index: int = 0
    total_candles: int = 0
    progress_pct: float = 0.0
    current_time: Optional[str] = None
    portfolio: Optional[PortfolioUpdatedPayload] = None
    positions: List[PositionItemPayload] = Field(default_factory=list)
