"""Pydantic schemas and typed data structures for trading, positions, and portfolio tracking."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderSide(str, enum.Enum):
    """Order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    """Order execution type."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, enum.Enum):
    """Lifecycle status of an order."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PositionState(BaseModel):
    """In-memory active state of an instrument position."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading symbol (e.g. RELIANCE)")
    quantity: int = Field(..., ge=0, description="Long position quantity (shares/units)")
    average_entry_price: float = Field(..., gt=0.0, description="Weighted average entry price")
    current_price: float = Field(..., gt=0.0, description="Current mark-to-market price")
    market_value: float = Field(..., description="Current market value (quantity * current_price)")
    unrealized_gross_pnl: float = Field(
        ..., description="Unrealized gross profit/loss ((current - entry) * quantity)"
    )
    unrealized_pnl_pct: float = Field(..., description="Unrealized gross return percentage")
    stop_loss: Optional[float] = Field(None, description="Optional stop-loss price trigger")
    take_profit: Optional[float] = Field(None, description="Optional take-profit price trigger")
    is_open: bool = Field(default=True, description="True if position is currently active")
    entry_time: datetime = Field(..., description="Timestamp of initial position entry (UTC)")
    last_updated: datetime = Field(..., description="Timestamp of most recent price update (UTC)")


class TradeRecord(BaseModel):
    """Immutable record of an executed and closed (or partially closed) trade."""

    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., description="Unique trade identifier")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(default=OrderSide.BUY, description="Position side")
    quantity: int = Field(..., gt=0, description="Number of units/shares executed")
    entry_price: float = Field(..., gt=0.0, description="Average entry price")
    exit_price: float = Field(..., gt=0.0, description="Exit execution price")
    gross_pnl: float = Field(..., description="Gross P&L = (exit_price - entry_price) * quantity")
    net_pnl: float = Field(..., description="Net P&L = gross_pnl - transaction_costs")
    transaction_costs: float = Field(
        default=0.0, ge=0.0, description="Total commissions/fees incurred"
    )
    slippage_cost: float = Field(
        default=0.0, ge=0.0, description="Estimated slippage impact incurred"
    )
    entry_time: datetime = Field(..., description="Timestamp of initial entry (UTC)")
    exit_time: datetime = Field(..., description="Timestamp of trade exit (UTC)")
    exit_reason: str = Field(
        default="MANUAL_EXIT",
        description="Reason for trade exit (e.g. MANUAL_EXIT, STOP_LOSS, TAKE_PROFIT)",
    )


class PortfolioState(BaseModel):
    """Authoritative deterministic snapshot of portfolio accounting state."""

    model_config = ConfigDict(frozen=True)

    initial_capital: float = Field(
        ..., gt=0.0, description="Starting capital balance (e.g. ₹1,00,000)"
    )
    cash: float = Field(..., description="Available cash balance")
    total_market_value: float = Field(
        default=0.0, description="Sum of market values of all open positions"
    )
    total_portfolio_value: float = Field(
        ..., description="Total equity = cash + total_market_value"
    )
    realized_gross_pnl: float = Field(
        default=0.0, description="Cumulative realized gross profit/loss"
    )
    realized_net_pnl: float = Field(default=0.0, description="Cumulative realized net profit/loss")
    unrealized_gross_pnl: float = Field(
        default=0.0, description="Sum of unrealized gross PnL across all open positions"
    )
    total_transaction_costs: float = Field(
        default=0.0, ge=0.0, description="Cumulative transaction fees incurred"
    )
    total_slippage_cost: float = Field(
        default=0.0, ge=0.0, description="Cumulative slippage costs incurred"
    )
    gross_pnl: float = Field(
        default=0.0, description="Total gross PnL = realized_gross_pnl + unrealized_gross_pnl"
    )
    net_pnl: float = Field(
        default=0.0,
        description="Total net PnL = gross_pnl - total_transaction_costs",
    )
    total_return_pct: float = Field(
        default=0.0, description="Total return percentage = (net_pnl / initial_capital) * 100"
    )
    exposure_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Portfolio exposure = (total_market_value / total_portfolio_value) * 100",
    )
    open_positions_count: int = Field(
        default=0, ge=0, description="Number of currently open positions"
    )
    closed_trades_count: int = Field(default=0, ge=0, description="Number of closed trade records")
    win_rate_pct: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Winning trades percentage"
    )
    daily_starting_equity: float = Field(
        ..., gt=0.0, description="Starting equity at the beginning of the current trading day"
    )
    daily_realized_pnl: float = Field(
        default=0.0, description="Realized PnL accumulated during the current trading day"
    )
    positions: Dict[str, PositionState] = Field(
        default_factory=dict, description="Map of symbol -> active PositionState"
    )
    closed_trades: List[TradeRecord] = Field(
        default_factory=list, description="Historical sequence of closed TradeRecords"
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of most recent portfolio update (UTC)",
    )


class OrderRequest(BaseModel):
    """Simulated order request submitted for deterministic execution."""

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique order ID")
    symbol: str = Field(..., description="Trading symbol (e.g. RELIANCE)")
    side: OrderSide = Field(..., description="Order side (BUY or SELL)")
    order_type: OrderType = Field(default=OrderType.MARKET, description="Order execution type")
    quantity: int = Field(..., gt=0, description="Number of shares/units to execute")
    decision_time: datetime = Field(
        ..., description="Timestamp of decision candle t after which order was generated"
    )
    decision_price: Optional[float] = Field(
        None, description="Price at decision time for reference logging (not used for fill)"
    )
    stop_loss: Optional[float] = Field(None, description="Optional protective stop loss")
    take_profit: Optional[float] = Field(None, description="Optional take profit target")
    reason: Optional[str] = Field(None, description="Reason or signal behind order")


class ExecutionConfig(BaseModel):
    """Configurable parameters for deterministic trade execution."""

    model_config = ConfigDict(frozen=True)

    slippage_pct: float = Field(
        default=0.0005, ge=0.0, description="Slippage percentage rate (default 0.05% = 0.0005)"
    )
    brokerage_rate: float = Field(
        default=0.0003,
        ge=0.0,
        description="Brokerage / transaction fee rate (default 0.03% = 0.0003)",
    )
    fixed_fee_per_order: float = Field(
        default=0.0, ge=0.0, description="Fixed transaction fee per order in INR"
    )


class ExecutionResult(BaseModel):
    """Authoritative result of an executed or rejected simulated order."""

    model_config = ConfigDict(frozen=True)

    order_id: str = Field(..., description="Unique order ID")
    status: OrderStatus = Field(..., description="Order execution status")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Order side")
    quantity: int = Field(..., ge=0, description="Filled or requested quantity")
    market_price: Optional[float] = Field(
        None, description="Next candle open price (before slippage)"
    )
    execution_price: Optional[float] = Field(
        None, description="Final filled price with slippage applied"
    )
    transaction_cost: float = Field(default=0.0, description="Transaction fee charged")
    slippage_cost: float = Field(default=0.0, description="Slippage cost impact")
    executed_at: Optional[datetime] = Field(
        None, description="Execution timestamp (next candle open time)"
    )
    decision_time: datetime = Field(..., description="Decision timestamp")
    trade_record: Optional[TradeRecord] = Field(
        None, description="Trade record generated if this execution closed a position"
    )
    rejection_reason: Optional[str] = Field(
        None, description="Explanation if order was rejected or could not execute"
    )


class RiskConfig(BaseModel):
    """Configurable risk parameters for deterministic risk engine."""

    model_config = ConfigDict(frozen=True)

    max_risk_per_trade: float = Field(
        default=0.02,
        ge=0.0,
        le=1.0,
        description="Max risk per trade as fraction of current equity (default 2% = 0.02)",
    )
    max_position_exposure: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Max position exposure as fraction of current equity (default 25% = 0.25)",
    )
    max_portfolio_exposure: float = Field(
        default=1.00,
        ge=0.0,
        le=2.0,
        description="Max aggregate portfolio exposure as fraction of current equity (default 100% = 1.0)",
    )
    max_daily_loss: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Max daily loss as fraction of daily starting equity (default 5% = 0.05)",
    )
    require_stop_loss: bool = Field(
        default=False,
        description="Whether a protective stop-loss is mandatory for BUY orders",
    )
    min_order_quantity: int = Field(
        default=1,
        ge=1,
        description="Minimum order quantity in shares/units",
    )
    max_order_quantity: Optional[int] = Field(
        default=None,
        gt=0,
        description="Optional maximum single order quantity ceiling",
    )


class RiskCheckResult(BaseModel):
    """Authoritative result of deterministic risk validation for an order."""

    model_config = ConfigDict(frozen=True)

    approved: bool = Field(
        ..., description="True if order passes all risk controls, False if rejected"
    )
    order_id: str = Field(..., description="Unique order ID")
    symbol: str = Field(..., description="Trading symbol")
    side: OrderSide = Field(..., description="Order side (BUY or SELL)")
    quantity: int = Field(..., ge=0, description="Order quantity")
    estimated_price: float = Field(..., description="Estimated fill price used for risk checks")
    rejection_reason: Optional[str] = Field(
        None, description="Detailed explanation if order is rejected by risk engine"
    )
    risk_metrics: Dict[str, float] = Field(
        default_factory=dict, description="Calculated risk metrics for transparency"
    )
