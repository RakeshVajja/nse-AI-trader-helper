"""Pydantic schemas and request/response models for Phase 8B Agent Mandate."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models.agent import AgentStatus
from app.trading.agent.gemini.schemas import GeminiErrorType
from app.trading.agent.mandate.constants import (
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MAX_DAILY_LOSS,
    DEFAULT_MAX_POSITION_EXPOSURE,
    DEFAULT_RISK_PER_TRADE,
    DEFAULT_TIMEFRAME,
    SUPPORTED_INDICATORS,
    SUPPORTED_INSTRUMENTS,
    SUPPORTED_TIMEFRAMES,
)


class StrategyStyle(str, Enum):
    """Supported high-level strategy styles."""

    MOMENTUM = "momentum"
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    SCALPING = "scalping"
    HYBRID = "hybrid"
    CUSTOM = "custom"


class MandateGenerationError(Exception):
    """Exception raised when natural language strategy cannot be compiled into a valid mandate."""

    def __init__(
        self,
        message: str,
        error_type: GeminiErrorType = GeminiErrorType.STRUCTURED_OUTPUT_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.details = details or {}


class AgentMandate(BaseModel):
    """Structured, validated declarative trading strategy mandate.

    This represents the user's persistent trading intent and risk boundaries,
    derived from natural language. It is strictly a DECLARATIVE STRATEGY SPECIFICATION,
    completely separate from per-candle AgentDecision runtime execution actions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_style: str = Field(
        ...,
        description="High-level strategy style classification (e.g. momentum, trend_following)",
    )
    objectives: List[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of concise strategic objectives",
    )
    preferred_indicators: List[str] = Field(
        ...,
        description="List of canonical indicators from supported vocabulary: EMA9, EMA20, SMA50, RSI14, MACD, ATR14",
    )
    instrument: str = Field(
        ...,
        description="Target NSE equity or index symbol",
    )
    timeframe: str = Field(
        default=DEFAULT_TIMEFRAME,
        description="Execution timeframe: 5m, 15m, 30m, 1h, 1d",
    )
    risk_per_trade: float = Field(
        default=DEFAULT_RISK_PER_TRADE,
        ge=0.001,
        le=0.10,
        description="Maximum fraction of equity risked per trade (0.1% to 10%)",
    )
    max_position_exposure: float = Field(
        default=DEFAULT_MAX_POSITION_EXPOSURE,
        ge=0.01,
        le=1.0,
        description="Maximum fraction of portfolio allocated to a single position (1% to 100%)",
    )
    max_daily_loss: float = Field(
        default=DEFAULT_MAX_DAILY_LOSS,
        ge=0.01,
        le=0.50,
        description="Maximum daily cumulative loss limit (1% to 50%)",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Concise model summary explaining the translated mandate",
    )

    @field_validator("preferred_indicators")
    @classmethod
    def validate_indicators(cls, indicators: List[str]) -> List[str]:
        """Ensure all requested indicators belong to the supported quantitative vocabulary."""
        if not indicators:
            raise ValueError("Mandate must include at least one preferred indicator.")
        cleaned: List[str] = []
        for ind in indicators:
            ind_clean = str(ind).strip().upper().replace(" ", "").replace("_", "")
            # Canonicalize names
            if ind_clean in ("RSI", "RSI14"):
                canonical = "RSI14"
            elif ind_clean in ("EMA9",):
                canonical = "EMA9"
            elif ind_clean in ("EMA20",):
                canonical = "EMA20"
            elif ind_clean in ("SMA50",):
                canonical = "SMA50"
            elif ind_clean in ("MACD",):
                canonical = "MACD"
            elif ind_clean in ("ATR", "ATR14"):
                canonical = "ATR14"
            else:
                canonical = ind_clean

            if canonical not in SUPPORTED_INDICATORS:
                raise ValueError(
                    f"Unsupported indicator '{ind}'. Must be one of: {sorted(SUPPORTED_INDICATORS)}"
                )
            if canonical not in cleaned:
                cleaned.append(canonical)
        return cleaned

    @field_validator("instrument")
    @classmethod
    def validate_instrument(cls, inst: str) -> str:
        """Ensure instrument is an authorized NSE equity or index."""
        inst_clean = inst.strip().upper()
        if inst_clean not in SUPPORTED_INSTRUMENTS:
            raise ValueError(
                f"Unsupported instrument '{inst}'. Must be one of: {sorted(SUPPORTED_INSTRUMENTS)}"
            )
        return inst_clean

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, tf: str) -> str:
        """Ensure timeframe is one of the supported resolutions."""
        tf_clean = tf.strip().lower()
        if tf_clean not in SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{tf}'. Must be one of: {sorted(SUPPORTED_TIMEFRAMES)}"
            )
        return tf_clean

    @field_validator("objectives")
    @classmethod
    def validate_objectives(cls, objs: List[str]) -> List[str]:
        """Ensure objectives are non-empty meaningful strings."""
        cleaned = [o.strip() for o in objs if o and o.strip()]
        if not cleaned:
            raise ValueError("Objectives list cannot be empty.")
        return cleaned


class AgentMandateCreateRequest(BaseModel):
    """Input payload for generating an agent mandate from a natural language prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique descriptive name for the trading agent",
    )
    strategy_prompt: str = Field(
        ...,
        min_length=3,
        max_length=3000,
        description="Natural-language description of the user's trading strategy",
    )
    instrument: Optional[str] = Field(
        default="RELIANCE",
        description="Target NSE equity or index symbol (default: RELIANCE)",
    )
    timeframe: Optional[str] = Field(
        default=DEFAULT_TIMEFRAME,
        description="Execution timeframe (default: 15m)",
    )
    initial_capital: Optional[float] = Field(
        default=DEFAULT_INITIAL_CAPITAL,
        gt=0.0,
        description="Initial virtual cash capital in INR (default: 100,000)",
    )
    max_risk_per_trade: Optional[float] = Field(
        default=DEFAULT_RISK_PER_TRADE,
        ge=0.001,
        le=0.10,
        description="Risk per trade override (default: 0.02 / 2%)",
    )
    max_position_exposure: Optional[float] = Field(
        default=DEFAULT_MAX_POSITION_EXPOSURE,
        ge=0.01,
        le=1.0,
        description="Max position exposure override (default: 0.25 / 25%)",
    )
    max_daily_loss: Optional[float] = Field(
        default=DEFAULT_MAX_DAILY_LOSS,
        ge=0.01,
        le=0.50,
        description="Max daily loss override (default: 0.05 / 5%)",
    )


class AgentMandateResponse(BaseModel):
    """Standard response envelope returned after mandate generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(
        ...,
        description="True if generation and validation succeeded",
    )
    mandate: Optional[AgentMandate] = Field(
        default=None,
        description="Parsed and validated AgentMandate",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Optional persisted Agent identifier if saved in database",
    )
    prompt_tokens: int = Field(
        default=0,
        ge=0,
        description="Prompt tokens consumed by Gemini generation",
    )
    completion_tokens: int = Field(
        default=0,
        ge=0,
        description="Candidate completion tokens consumed",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total tokens consumed in interaction",
    )
    latency_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="LLM generation latency in milliseconds",
    )
    error: Optional[str] = Field(
        default=None,
        description="Diagnostic error message if generation failed",
    )
    error_type: Optional[GeminiErrorType] = Field(
        default=None,
        description="Categorized error type if generation failed",
    )


class AgentCreateRequest(BaseModel):
    """Request payload for confirming and persisting an AI trading agent (Phase 9B/9C)."""

    model_config = ConfigDict(extra="ignore")

    agent_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique descriptive name for the trading agent",
    )
    initial_capital: float = Field(
        default=DEFAULT_INITIAL_CAPITAL,
        gt=0.0,
        description="Initial virtual cash capital in INR (default: 100,000)",
    )
    mandate: AgentMandate = Field(
        ...,
        description="Confirmed and validated declarative trading mandate",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional human-readable description",
    )
    strategy_prompt: Optional[str] = Field(
        default=None,
        description="Optional original natural language strategy prompt",
    )
    simulation_id: Optional[str] = Field(
        default=None,
        description="Optional associated simulation run ID to link",
    )

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Agent name cannot be empty or whitespace.")
        return clean


class AgentUpdateRequest(BaseModel):
    """Request payload for updating mutable agent metadata."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Updated descriptive name for the trading agent",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Updated agent description",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        if not clean:
            raise ValueError("Agent name cannot be empty or whitespace.")
        return clean


class AgentResponse(BaseModel):
    """Authoritative response schema representing an AI trading agent (Phase 9C)."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str = Field(
        ...,
        description="Unique agent ID (compatible with frontend AgentConfirmResponse)",
    )
    id: str = Field(
        ...,
        description="Unique agent ID (canonical REST identifier)",
    )
    name: str = Field(
        ...,
        description="Descriptive agent name",
    )
    status: AgentStatus = Field(
        ...,
        description="Authoritative agent lifecycle status",
    )
    instrument: str = Field(
        ...,
        description="Target NSE equity or index symbol",
    )
    timeframe: str = Field(
        ...,
        description="Execution candle timeframe (e.g. 15m)",
    )
    initial_capital: float = Field(
        ...,
        description="Initial cash allocation in INR",
    )
    max_risk_per_trade: float = Field(
        ...,
        description="Maximum fraction of equity risked per trade",
    )
    max_position_exposure: float = Field(
        ...,
        description="Maximum fraction allocated to a single position",
    )
    max_daily_loss: float = Field(
        ...,
        description="Maximum daily cumulative loss limit",
    )
    strategy_prompt: str = Field(
        ...,
        description="Natural language prompt or declarative summary",
    )
    strategy_style: str = Field(
        ...,
        description="Strategy style classification",
    )
    objectives: List[str] = Field(
        default_factory=list,
        description="List of strategic objectives",
    )
    preferred_indicators: List[str] = Field(
        default_factory=list,
        description="List of preferred indicators",
    )
    raw_mandate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full raw mandate specification",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="Model explanation / rationale",
    )
    simulation_id: Optional[str] = Field(
        default=None,
        description="Associated simulation run ID if linked",
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Creation timestamp",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp",
    )
    message: Optional[str] = Field(
        default=None,
        description="Diagnostic or confirmation message",
    )


class AgentStatusResponse(BaseModel):
    """Authoritative lifecycle status response for an agent."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: str = Field(
        ...,
        description="Unique agent ID",
    )
    name: str = Field(
        ...,
        description="Descriptive agent name",
    )
    status: AgentStatus = Field(
        ...,
        description="Current lifecycle status",
    )
    instrument: str = Field(
        ...,
        description="Target NSE equity or index symbol",
    )
    timeframe: str = Field(
        ...,
        description="Candle timeframe",
    )
    simulation_id: Optional[str] = Field(
        default=None,
        description="Associated simulation ID if linked",
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last status update timestamp",
    )


class AgentListResponse(BaseModel):
    """Paginated list of trading agents."""

    model_config = ConfigDict(from_attributes=True)

    agents: List[AgentResponse] = Field(
        default_factory=list,
        description="List of agent instances",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total matching agents count",
    )
    count: int = Field(
        ...,
        ge=0,
        description="Number of agents returned in this page",
    )
