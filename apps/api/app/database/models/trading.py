"""SQLAlchemy models for simulations, orders, trades, positions, and portfolio tracking."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base, TimestampMixin


class SimulationStatus(str, enum.Enum):
    """Execution status of a historical simulation run."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OrderType(str, enum.Enum):
    """Order type for execution."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSide(str, enum.Enum):
    """Order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, enum.Enum):
    """Order lifecycle status."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SimulationRun(Base, TimestampMixin):
    """Historical backtest / simulation session."""

    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(10), default="15m", nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0, nullable=False)
    final_portfolio_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_return_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[SimulationStatus] = mapped_column(
        Enum(SimulationStatus, native_enum=False, length=20),
        default=SimulationStatus.CREATED,
        nullable=False,
    )
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict, nullable=True)

    # Relationships
    orders: Mapped[List[Order]] = relationship(
        "Order", back_populates="simulation", cascade="all, delete-orphan", lazy="selectin"
    )
    trades: Mapped[List[Trade]] = relationship(
        "Trade", back_populates="simulation", cascade="all, delete-orphan", lazy="selectin"
    )
    positions: Mapped[List[Position]] = relationship(
        "Position", back_populates="simulation", cascade="all, delete-orphan", lazy="selectin"
    )
    snapshots: Mapped[List[PortfolioSnapshot]] = relationship(
        "PortfolioSnapshot",
        back_populates="simulation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Order(Base, TimestampMixin):
    """Simulated trade order submitted to the risk & execution engine."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    simulation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, native_enum=False, length=10), default=OrderType.MARKET, nullable=False
    )
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, native_enum=False, length=10), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=15),
        default=OrderStatus.PENDING,
        nullable=False,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    simulation: Mapped[SimulationRun] = relationship(
        "SimulationRun", back_populates="orders", lazy="selectin"
    )
    trades: Mapped[List[Trade]] = relationship("Trade", back_populates="order", lazy="selectin")


class Trade(Base, TimestampMixin):
    """Completed or active simulated executed position trade."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    simulation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, native_enum=False, length=10), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gross_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    transaction_costs: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    simulation: Mapped[SimulationRun] = relationship(
        "SimulationRun", back_populates="trades", lazy="selectin"
    )
    order: Mapped[Optional[Order]] = relationship("Order", back_populates="trades", lazy="selectin")


class Position(Base, TimestampMixin):
    """Current open position in an instrument during simulation."""

    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    simulation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    simulation: Mapped[SimulationRun] = relationship(
        "SimulationRun", back_populates="positions", lazy="selectin"
    )


class PortfolioSnapshot(Base, TimestampMixin):
    """Periodic snapshot of portfolio value and risk exposure during replay."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    simulation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    portfolio_value: Mapped[float] = mapped_column(Float, nullable=False)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    exposure_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    open_positions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    simulation: Mapped[SimulationRun] = relationship(
        "SimulationRun", back_populates="snapshots", lazy="selectin"
    )

    __table_args__ = (Index("ix_snapshot_sim_time", "simulation_id", "timestamp"),)
