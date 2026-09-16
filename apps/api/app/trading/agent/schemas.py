"""Pydantic schemas for typed agent tools and structured output (Phase 7A).

All schemas strictly enforce:
- model_config = ConfigDict(extra="forbid", frozen=True)
- Strong typing and enum constraints
- Strict numeric and range bounds
- Immutability and explicit error structures
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.indicators.schemas import (
    TrendRegime,
    TrendSignalDetails,
    VolatilityMetrics,
    VolatilityRegime,
)
from app.trading.schemas import OrderSide, OrderStatus, OrderType

# ==============================================================================
# Tool 1: get_market_data
# ==============================================================================


class MarketCandleSchema(BaseModel):
    """OHLCV candlestick representation for agent market data perception."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime = Field(..., description="UTC candle open timestamp")
    open: float = Field(..., gt=0.0, description="Candle opening price")
    high: float = Field(..., gt=0.0, description="Candle highest price")
    low: float = Field(..., gt=0.0, description="Candle lowest price")
    close: float = Field(..., gt=0.0, description="Candle closing price")
    volume: float = Field(..., ge=0.0, description="Candle trading volume")


class GetMarketDataInput(BaseModel):
    """Input parameters for get_market_data tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lookback: int = Field(
        default=10, ge=1, le=100, description="Number of recent candles to retrieve"
    )
    symbol: Optional[str] = Field(
        None,
        description="Optional symbol override; must match active simulation instrument if supplied",
    )


class GetMarketDataOutput(BaseModel):
    """Output payload for get_market_data tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., description="Trading symbol")
    timeframe: str = Field(..., description="Candle timeframe")
    current_candle: MarketCandleSchema = Field(..., description="Most recent completed candle t")
    recent_candles: List[MarketCandleSchema] = Field(
        ..., description="Recent historical candles up to and including candle t"
    )
    current_price: float = Field(..., gt=0.0, description="Current price (close of candle t)")
    price_change: float = Field(..., description="Price change from previous candle close")
    price_change_pct: float = Field(
        ..., description="Percentage price change from previous candle close"
    )
    current_volume: float = Field(..., ge=0.0, description="Volume of candle t")


# ==============================================================================
# Tool 2: get_indicators
# ==============================================================================


class GetIndicatorsInput(BaseModel):
    """Input parameters for get_indicators tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Optional[str] = Field(
        None,
        description="Optional symbol override; must match active simulation instrument if supplied",
    )


class GetIndicatorsOutput(BaseModel):
    """Output payload for get_indicators tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., description="Trading symbol")
    timestamp: datetime = Field(..., description="Timestamp of calculation (candle t)")
    close: float = Field(..., gt=0.0, description="Close price at candle t")
    ema_9: Optional[float] = Field(None, description="9-period EMA or None during warmup")
    ema_20: Optional[float] = Field(None, description="20-period EMA or None during warmup")
    sma_50: Optional[float] = Field(None, description="50-period SMA or None during warmup")
    rsi_14: Optional[float] = Field(
        None, ge=0.0, le=100.0, description="14-period RSI (0-100) or None during warmup"
    )
    macd: Optional[float] = Field(None, description="MACD line or None during warmup")
    macd_signal: Optional[float] = Field(None, description="MACD signal line or None during warmup")
    macd_histogram: Optional[float] = Field(
        None, description="MACD histogram or None during warmup"
    )
    is_warmed_up: bool = Field(
        default=False, description="True if core indicator warmup requirements are fulfilled"
    )


# ==============================================================================
# Tool 3: get_market_regime
# ==============================================================================


class GetMarketRegimeInput(BaseModel):
    """Input parameters for get_market_regime tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Optional[str] = Field(
        None,
        description="Optional symbol override; must match active simulation instrument if supplied",
    )


class GetMarketRegimeOutput(BaseModel):
    """Output payload for get_market_regime tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., description="Trading symbol")
    timestamp: datetime = Field(..., description="Timestamp of evaluation (candle t)")
    trend_regime: Optional[TrendRegime] = Field(
        None, description="BULLISH, BEARISH, SIDEWAYS, or None if warmup incomplete"
    )
    volatility_regime: Optional[VolatilityRegime] = Field(
        None, description="HIGH, NORMAL, LOW, or None if warmup incomplete"
    )
    trend_signals: Optional[TrendSignalDetails] = Field(
        None, description="Detailed 4-indicator trend voting breakdown"
    )
    volatility_metrics: Optional[VolatilityMetrics] = Field(
        None, description="Historical rolling percentile volatility metrics"
    )


# ==============================================================================
# Tool 4: get_position
# ==============================================================================


class GetPositionInput(BaseModel):
    """Input parameters for get_position tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: Optional[str] = Field(
        None,
        description="Optional symbol override; defaults to active simulation instrument",
    )


class GetPositionOutput(BaseModel):
    """Output payload for get_position tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., description="Trading symbol")
    is_open: bool = Field(..., description="True if position is currently active")
    quantity: int = Field(..., ge=0, description="Active position quantity (shares)")
    average_entry_price: Optional[float] = Field(
        None, gt=0.0, description="Weighted average entry price"
    )
    current_price: float = Field(..., gt=0.0, description="Current market price (candle t close)")
    market_value: float = Field(..., ge=0.0, description="Current market value of position")
    stop_loss: Optional[float] = Field(
        None, gt=0.0, description="Protective stop loss trigger price"
    )
    take_profit: Optional[float] = Field(None, gt=0.0, description="Profit target trigger price")
    unrealized_pnl: float = Field(..., description="Gross unrealized profit/loss in INR")
    unrealized_pnl_pct: float = Field(..., description="Gross unrealized profit/loss percentage")
    entry_time: Optional[datetime] = Field(None, description="Timestamp of initial entry")


# ==============================================================================
# Tool 5: get_portfolio
# ==============================================================================


class GetPortfolioInput(BaseModel):
    """Input parameters for get_portfolio tool (accepts no arguments)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class GetPortfolioOutput(BaseModel):
    """Output payload for get_portfolio tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_capital: float = Field(..., gt=0.0, description="Initial starting equity")
    cash: float = Field(..., description="Available cash balance")
    total_market_value: float = Field(
        ..., ge=0.0, description="Aggregate market value of open positions"
    )
    total_portfolio_value: float = Field(
        ..., description="Total portfolio equity (cash + market value)"
    )
    realized_gross_pnl: float = Field(
        default=0.0, description="Cumulative realized gross profit/loss"
    )
    realized_net_pnl: float = Field(default=0.0, description="Cumulative realized net profit/loss")
    unrealized_gross_pnl: float = Field(default=0.0, description="Unrealized gross profit/loss")
    total_transaction_costs: float = Field(
        default=0.0, ge=0.0, description="Total transaction fees incurred"
    )
    total_slippage_cost: float = Field(
        default=0.0, ge=0.0, description="Total slippage impact incurred"
    )
    gross_pnl: float = Field(
        default=0.0, description="Total gross PnL = realized_gross + unrealized_gross"
    )
    net_pnl: float = Field(
        default=0.0, description="Total net PnL = gross_pnl - total_transaction_costs"
    )
    total_return_pct: float = Field(
        default=0.0, description="Total return percentage = (net_pnl / initial_capital) * 100"
    )
    exposure_pct: float = Field(
        ..., ge=0.0, le=100.0, description="Exposure fraction = (market_value / equity) * 100"
    )
    daily_starting_equity: float = Field(
        ..., gt=0.0, description="Starting equity at beginning of current trading day"
    )
    daily_realized_pnl: float = Field(default=0.0, description="Realized PnL accumulated today")
    open_positions_count: int = Field(default=0, ge=0, description="Count of active open positions")


# ==============================================================================
# Tool 6: get_trade_history
# ==============================================================================


class TradeRecordSchema(BaseModel):
    """Record of a closed trade execution for agent history inspection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: str = Field(..., description="Unique trade identifier")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(default=OrderSide.BUY, description="Position side")
    quantity: int = Field(..., gt=0, description="Executed quantity")
    entry_price: float = Field(..., gt=0.0, description="Average entry fill price")
    exit_price: float = Field(..., gt=0.0, description="Exit fill price")
    gross_pnl: float = Field(..., description="Gross P&L = (exit - entry) * quantity")
    net_pnl: float = Field(..., description="Net P&L = gross_pnl - transaction_costs")
    transaction_costs: float = Field(
        default=0.0, ge=0.0, description="Commissions and transaction fees"
    )
    slippage_cost: float = Field(default=0.0, ge=0.0, description="Estimated slippage impact")
    entry_time: datetime = Field(..., description="Timestamp of trade entry (UTC)")
    exit_time: datetime = Field(..., description="Timestamp of trade exit (UTC)")
    exit_reason: str = Field(
        default="MANUAL_EXIT", description="Exit reason (e.g. STOP_LOSS, TAKE_PROFIT, MANUAL_EXIT)"
    )


class GetTradeHistoryInput(BaseModel):
    """Input parameters for get_trade_history tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    limit: int = Field(default=10, ge=1, le=50, description="Max trade records to retrieve")
    symbol: Optional[str] = Field(None, description="Optional symbol filter")


class GetTradeHistoryOutput(BaseModel):
    """Output payload for get_trade_history tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trades: List[TradeRecordSchema] = Field(
        default_factory=list, description="Historical sequence of closed trade records"
    )
    total_closed_trades: int = Field(
        default=0, ge=0, description="Total number of closed trades in session"
    )


# ==============================================================================
# Tool 7: calculate_position_size
# ==============================================================================


class CalculatePositionSizeInput(BaseModel):
    """Input parameters for calculate_position_size tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_price: float = Field(..., gt=0.0, description="Planned entry reference price")
    stop_loss_price: float = Field(..., gt=0.0, description="Planned protective stop-loss price")
    risk_per_trade: Optional[float] = Field(
        None, gt=0.0, le=1.0, description="Optional risk override fraction (e.g. 0.02)"
    )
    symbol: Optional[str] = Field(
        None, description="Optional symbol; defaults to active simulation instrument"
    )


class CalculatePositionSizeOutput(BaseModel):
    """Output payload for calculate_position_size tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_quantity: int = Field(
        ..., ge=0, description="Safe integer share quantity (0 if sizing rejected)"
    )
    estimated_execution_price: float = Field(
        ..., gt=0.0, description="Estimated fill price with slippage applied"
    )
    estimated_cost: float = Field(
        ..., ge=0.0, description="Estimated total cash required including fees"
    )
    risk_amount: float = Field(
        ..., ge=0.0, description="Estimated monetary risk = quantity * (entry - SL)"
    )
    risk_pct_of_portfolio: float = Field(
        ..., ge=0.0, description="Percentage of portfolio equity risked"
    )
    position_exposure_pct: float = Field(
        ..., ge=0.0, description="Percentage of portfolio equity committed to position"
    )
    status: str = Field(..., description="'APPROVED' if target_quantity > 0, otherwise 'REJECTED'")
    reason: Optional[str] = Field(
        None, description="Diagnostic explanation if sizing resulted in 0 shares"
    )


# ==============================================================================
# Tool 8: place_simulated_order
# ==============================================================================


class PlaceSimulatedOrderInput(BaseModel):
    """Input parameters for place_simulated_order tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    side: OrderSide = Field(..., description="Order side: BUY or SELL")
    quantity: int = Field(..., gt=0, description="Quantity of shares to execute")
    order_type: OrderType = Field(
        default=OrderType.MARKET, description="Order execution type (MARKET)"
    )
    stop_loss: Optional[float] = Field(
        None, gt=0.0, description="Protective stop loss trigger price"
    )
    take_profit: Optional[float] = Field(None, gt=0.0, description="Profit target trigger price")
    reason: str = Field(..., min_length=1, description="Agent rationale for this order")

    @field_validator("reason")
    @classmethod
    def validate_reason_non_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("reason cannot be empty or whitespace only")
        return clean


class PlaceSimulatedOrderOutput(BaseModel):
    """Output payload for place_simulated_order tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(..., description="True if order passed risk validation and was staged")
    order_id: Optional[str] = Field(None, description="Unique order ID if staged, None if rejected")
    status: OrderStatus = Field(
        ..., description="OrderStatus.PENDING if staged, OrderStatus.REJECTED if risk failed"
    )
    decision_price: float = Field(
        ..., gt=0.0, description="Decision close price at candle t used as reference"
    )
    execution_stage: str = Field(
        ..., description="'QUEUED_FOR_NEXT_OPEN' if staged, 'REJECTED' if risk failed"
    )
    rejection_reason: Optional[str] = Field(
        None, description="Diagnostic reason if order was rejected by RiskEngine"
    )
    risk_metrics: Optional[Dict[str, float]] = Field(
        None, description="Risk check metrics (equity, cash, exposure, trade risk)"
    )


# ==============================================================================
# Tool 9: close_simulated_position
# ==============================================================================


class CloseSimulatedPositionInput(BaseModel):
    """Input parameters for close_simulated_position tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quantity: Optional[int] = Field(
        None, gt=0, description="Shares to close. If None, closes entire position."
    )
    reason: str = Field(
        default="AGENT_CLOSE", min_length=1, description="Rationale for closing position"
    )

    @field_validator("reason")
    @classmethod
    def validate_reason_non_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("reason cannot be empty or whitespace only")
        return clean


class CloseSimulatedPositionOutput(BaseModel):
    """Output payload for close_simulated_position tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(..., description="True if position close was validated and staged")
    order_id: Optional[str] = Field(None, description="Unique order ID if staged, None if rejected")
    status: str = Field(..., description="'QUEUED_FOR_NEXT_OPEN' if staged, 'REJECTED' if failed")
    closed_quantity: int = Field(..., ge=0, description="Number of shares staged for liquidation")
    remaining_quantity: int = Field(
        ..., ge=0, description="Position shares remaining after execution"
    )
    rejection_reason: Optional[str] = Field(
        None, description="Diagnostic reason if close request failed"
    )


# ==============================================================================
# Safe Execution Envelope: ToolExecutionResult
# ==============================================================================


class ToolErrorType(str, Enum):
    """Categorized tool execution error codes."""

    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    RISK_REJECTION = "RISK_REJECTION"
    STATE_ERROR = "STATE_ERROR"
    ORDER_ALREADY_STAGED = "ORDER_ALREADY_STAGED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolExecutionResult(BaseModel):
    """Standard execution envelope returned by tool execution harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(..., description="Name of the invoked tool")
    success: bool = Field(..., description="True if tool executed successfully")
    data: Optional[Dict[str, Any]] = Field(None, description="Structured output payload on success")
    error: Optional[str] = Field(None, description="Diagnostic error message on failure")
    error_type: Optional[ToolErrorType] = Field(
        None, description="Categorized error type on failure"
    )


# ==============================================================================
# Agent Structured Output: AgentDecision (Section 39)
# ==============================================================================


class AgentAction(str, Enum):
    """Discrete trade action choices for the AI agent."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class AgentDecision(BaseModel):
    """Structured decision emitted by Gemini agent at each evaluation cycle (Section 39)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: AgentAction = Field(..., description="Action choice: BUY, SELL, or HOLD")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )
    quantity: Optional[int] = Field(
        None, gt=0, description="Quantity to trade if action is BUY or SELL"
    )
    stop_loss: Optional[float] = Field(
        None, gt=0.0, description="Protective stop-loss price if BUY"
    )
    take_profit: Optional[float] = Field(
        None, gt=0.0, description="Take-profit target price if BUY"
    )
    reason: str = Field(..., min_length=1, description="Non-empty rationale behind decision")
    observations: List[str] = Field(
        default_factory=list, description="Key market observations noted by agent"
    )
    tools_used: List[str] = Field(
        default_factory=list, description="List of tool names invoked during evaluation"
    )

    @field_validator("reason")
    @classmethod
    def validate_reason_non_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("reason cannot be empty or whitespace only")
        return clean
