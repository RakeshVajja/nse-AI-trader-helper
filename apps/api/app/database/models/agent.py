"""SQLAlchemy models for AI agents, configurations, decisions, and Gemini token telemetry."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
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


class AgentStatus(str, enum.Enum):
    """Lifecycle states of an AI agent."""

    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    COMPLETED = "COMPLETED"


class AgentAction(str, enum.Enum):
    """Actions emitted by the reasoning agent."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Agent(Base, TimestampMixin):
    """Trading agent instance definition and risk parameters."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False, length=20),
        default=AgentStatus.CREATED,
        nullable=False,
    )
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(10), default="15m", nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0, nullable=False)
    max_risk_per_trade: Mapped[float] = mapped_column(Float, default=0.02, nullable=False)
    max_position_exposure: Mapped[float] = mapped_column(Float, default=0.25, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    strategy_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    config: Mapped[Optional[AgentConfig]] = relationship(
        "AgentConfig",
        back_populates="agent",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    decisions: Mapped[List[AgentDecision]] = relationship(
        "AgentDecision", back_populates="agent", cascade="all, delete-orphan", lazy="selectin"
    )
    usages: Mapped[List[AgentUsage]] = relationship(
        "AgentUsage", back_populates="agent", cascade="all, delete-orphan", lazy="selectin"
    )


class AgentConfig(Base, TimestampMixin):
    """Parsed structured trading mandate created by Gemini from prompt."""

    __tablename__ = "agent_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    strategy_style: Mapped[str] = mapped_column(String(50), nullable=False)
    objectives: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_indicators: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_mandate: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    agent: Mapped[Agent] = relationship("Agent", back_populates="config", lazy="selectin")


class AgentDecision(Base, TimestampMixin):
    """Individual decision log produced by Gemini reasoning cycle."""

    __tablename__ = "agent_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    simulation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[AgentAction] = mapped_column(
        Enum(AgentAction, native_enum=False, length=10), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    observations: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    tools_used: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    market_regime: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # Relationships
    agent: Mapped[Agent] = relationship("Agent", back_populates="decisions", lazy="selectin")
    tool_calls: Mapped[List[AgentToolCall]] = relationship(
        "AgentToolCall", back_populates="decision", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_agent_decision_search", "agent_id", "simulation_id", "candle_timestamp"),
    )


class AgentToolCall(Base, TimestampMixin):
    """Individual tool execution invoked by Gemini."""

    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    decision_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("agent_decisions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_args: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    tool_result: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationships
    decision: Mapped[Optional[AgentDecision]] = relationship(
        "AgentDecision", back_populates="tool_calls", lazy="selectin"
    )


class AgentUsage(Base, TimestampMixin):
    """Token consumption, latency, and cost accounting for Gemini calls."""

    __tablename__ = "agent_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    simulation_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationships
    agent: Mapped[Agent] = relationship("Agent", back_populates="usages", lazy="selectin")
