from __future__ import annotations

import enum
from datetime import datetime
from typing import List

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class InstrumentType(str, enum.Enum):
    """Supported NSE Instrument types."""

    EQUITY = "EQUITY"
    INDEX = "INDEX"


class Instrument(Base, TimestampMixin):
    """NSE Stock or Index entity."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), default="NSE", nullable=False)
    instrument_type: Mapped[InstrumentType] = mapped_column(
        Enum(InstrumentType, native_enum=False, length=20),
        default=InstrumentType.EQUITY,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships — use lazy='select' to avoid eagerly fetching all candles/ranges
    # on every instrument query, while still allowing ORM cascade delete to work.
    candles: Mapped[List[Candle]] = relationship(
        "Candle", back_populates="instrument", cascade="all, delete-orphan", lazy="select"
    )
    data_ranges: Mapped[List[MarketDataRange]] = relationship(
        "MarketDataRange", back_populates="instrument", cascade="all, delete-orphan", lazy="select"
    )


class Candle(Base, TimestampMixin):
    """Historical OHLCV candlestick bar."""

    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Relationships
    instrument: Mapped[Instrument] = relationship(
        "Instrument", back_populates="candles", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "timeframe", "timestamp", name="uq_candle_instrument_tf_time"
        ),
        Index("ix_candle_query", "instrument_id", "timeframe", "timestamp"),
    )


class MarketDataRange(Base, TimestampMixin):
    """Metadata tracking earliest/latest stored data for fast lookup."""

    __tablename__ = "market_data_ranges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    earliest_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_candles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    instrument: Mapped[Instrument] = relationship(
        "Instrument", back_populates="data_ranges", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("instrument_id", "timeframe", name="uq_range_instrument_tf"),
    )
