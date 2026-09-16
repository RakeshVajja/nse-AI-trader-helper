"""Pydantic schemas for simulation REST API requests and responses (Phase 6D)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.trading.simulation.clock import VALID_PLAYBACK_SPEEDS


class SimulationCreateRequest(BaseModel):
    """Payload for creating a new historical simulation run."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="NSE Trading symbol (e.g. RELIANCE, TCS, INFY)",
    )
    timeframe: str = Field(
        default="15m",
        description="Candle timeframe interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)",
    )
    start_date: datetime = Field(
        ...,
        description="Start of historical replay window (UTC ISO 8601)",
    )
    end_date: datetime = Field(
        ...,
        description="End of historical replay window (UTC ISO 8601)",
    )
    initial_capital: float = Field(
        default=100000.0,
        gt=0.0,
        description="Starting cash portfolio balance in INR (default 1,00,000.0)",
    )
    is_baseline: bool = Field(
        default=True,
        description="Whether to run the deterministic EMA 9/20 crossover benchmark baseline",
    )
    speed: float = Field(
        default=1.0,
        description="Initial playback speed multiplier (0.5, 1.0, 2.0, 5.0, 10.0)",
    )

    # Execution configuration overrides
    slippage_pct: Optional[float] = Field(
        default=0.0005,
        ge=0.0,
        description="Execution slippage rate (default 0.05% = 0.0005)",
    )
    brokerage_rate: Optional[float] = Field(
        default=0.0003,
        ge=0.0,
        description="Brokerage transaction fee rate (default 0.03% = 0.0003)",
    )
    fixed_fee_per_order: Optional[float] = Field(
        default=0.0,
        ge=0.0,
        description="Fixed transaction fee per order in INR",
    )

    # Risk configuration overrides
    max_risk_per_trade: Optional[float] = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Maximum risk per trade as fraction of equity (default 2% = 0.02)",
    )
    max_position_exposure: Optional[float] = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Maximum single position exposure fraction (default 25% = 0.25)",
    )
    max_portfolio_exposure: Optional[float] = Field(
        default=1.00,
        ge=0.0,
        le=2.0,
        description="Maximum aggregate portfolio exposure fraction (default 100% = 1.0)",
    )
    max_daily_loss: Optional[float] = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Maximum daily loss fraction (default 5% = 0.05)",
    )

    @model_validator(mode="after")
    def validate_dates_and_speed(self) -> SimulationCreateRequest:
        """Validate date chronological ordering and playback speed multiplier."""
        s_utc = (
            self.start_date.replace(tzinfo=timezone.utc)
            if self.start_date.tzinfo is None
            else self.start_date
        )
        e_utc = (
            self.end_date.replace(tzinfo=timezone.utc)
            if self.end_date.tzinfo is None
            else self.end_date
        )

        if s_utc > e_utc:
            raise ValueError(
                f"start_date ({self.start_date.isoformat()}) must be before or equal to "
                f"end_date ({self.end_date.isoformat()})"
            )

        if self.speed not in VALID_PLAYBACK_SPEEDS:
            speeds_str = ", ".join(str(s) for s in VALID_PLAYBACK_SPEEDS)
            raise ValueError(
                f"Unsupported playback speed '{self.speed}'. Supported speeds: {speeds_str}"
            )

        return self


class SimulationResponse(BaseModel):
    """Detailed response schema representing a historical simulation run."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique simulation session ID")
    instrument_id: int = Field(..., description="ID of the simulated instrument")
    symbol: str = Field(..., description="Trading symbol (e.g. RELIANCE)")
    timeframe: str = Field(..., description="Candle interval (e.g. 15m)")
    start_date: datetime = Field(..., description="Replay window start (UTC)")
    end_date: datetime = Field(..., description="Replay window end (UTC)")
    initial_capital: float = Field(..., description="Starting capital in INR")
    final_portfolio_value: Optional[float] = Field(
        None, description="Current or final total portfolio equity"
    )
    total_return_pct: Optional[float] = Field(
        None, description="Net return percentage on starting capital"
    )
    status: str = Field(
        ..., description="Lifecycle status (CREATED, RUNNING, PAUSED, STOPPED, COMPLETED)"
    )
    is_baseline: bool = Field(..., description="Whether baseline EMA strategy is used")
    speed: float = Field(..., description="Current playback speed multiplier")
    current_time: Optional[datetime] = Field(
        None, description="Current virtual simulation timestamp"
    )
    step_index: int = Field(default=0, description="Completed simulation candle steps")
    total_candles: int = Field(default=0, description="Total candles in the replay series")
    progress_pct: float = Field(
        default=0.0, description="Replay completion percentage (0.0 to 100.0)"
    )
    metrics: Optional[Dict[str, Any]] = Field(
        default=None, description="Summary performance and configuration metrics"
    )
    created_at: Optional[datetime] = Field(None, description="Session creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Session update timestamp")


class TradeResponse(BaseModel):
    """Schema representing an executed simulation trade."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique trade ID")
    simulation_id: str = Field(..., description="Associated simulation run ID")
    order_id: Optional[str] = Field(None, description="Associated order ID")
    instrument_id: int = Field(..., description="Instrument ID")
    symbol: str = Field(..., description="Trading symbol")
    side: str = Field(..., description="Trade side (BUY or SELL)")
    quantity: int = Field(..., description="Executed quantity")
    entry_price: float = Field(..., description="Entry fill price")
    exit_price: Optional[float] = Field(None, description="Exit fill price")
    gross_pnl: Optional[float] = Field(None, description="Gross profit or loss")
    net_pnl: Optional[float] = Field(None, description="Net profit or loss after transaction costs")
    transaction_costs: float = Field(default=0.0, description="Total transaction fees incurred")
    slippage_cost: float = Field(default=0.0, description="Estimated slippage cost")
    is_closed: bool = Field(default=False, description="True if position has been closed")
    entry_time: datetime = Field(..., description="Entry execution timestamp (UTC)")
    exit_time: Optional[datetime] = Field(None, description="Exit execution timestamp (UTC)")


class PerformanceMetricsResponse(BaseModel):
    """Comprehensive performance metrics matching Section 58 of specification."""

    model_config = ConfigDict(from_attributes=True)

    simulation_id: str = Field(..., description="Simulation run ID")
    initial_capital: float = Field(..., description="Initial starting capital")
    final_portfolio_value: float = Field(..., description="Final total portfolio equity")
    gross_pnl: float = Field(..., description="Total gross profit/loss")
    net_pnl: float = Field(..., description="Total net profit/loss")
    total_return_pct: float = Field(..., description="Net total return percentage")
    transaction_costs: float = Field(..., description="Total transaction fees")
    slippage_cost: float = Field(..., description="Total slippage cost impact")
    total_trades: int = Field(..., description="Total closed trades count")
    winning_trades: int = Field(..., description="Number of profitable trades")
    losing_trades: int = Field(..., description="Number of losing trades")
    win_rate_pct: float = Field(..., description="Winning trade percentage (0.0 to 100.0)")
    average_win: float = Field(..., description="Average net gain of winning trades")
    average_loss: float = Field(..., description="Average net loss of losing trades")
    profit_factor: float = Field(..., description="Gross profit divided by gross loss")
    max_drawdown_pct: float = Field(..., description="Peak-to-trough maximum drawdown percentage")
    exposure_pct: float = Field(..., description="Current portfolio exposure percentage")
    open_positions_count: int = Field(..., description="Number of open positions")


class DecisionResponse(BaseModel):
    """Schema representing an authoritative strategy decision event."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique decision ID")
    simulation_id: str = Field(..., description="Associated simulation run ID")
    candle_timestamp: datetime = Field(..., description="Candle timestamp for the decision (UTC)")
    action: str = Field(..., description="Action taken: BUY, SELL, or HOLD")
    confidence: float = Field(
        default=1.0, description="Decision confidence (1.0 for deterministic)"
    )
    quantity: Optional[int] = Field(None, description="Target share quantity if order generated")
    stop_loss: Optional[float] = Field(None, description="Stop loss price trigger attached")
    take_profit: Optional[float] = Field(None, description="Take profit price trigger attached")
    reason: str = Field(default="", description="Mathematical signal or reasoning rationale")
    market_regime: Optional[str] = Field(
        None, description="Descriptive market regime context if recorded"
    )
