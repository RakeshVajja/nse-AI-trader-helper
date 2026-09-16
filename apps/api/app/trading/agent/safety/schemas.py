"""Pydantic v2 schemas for Phase 8E: Agent Failure Handling & Auto-Pause.

Enforces:
- model_config = ConfigDict(extra="forbid", frozen=True)
- Deterministic failure categories distinguishing transient vs permanent errors
- Clean domain isolation preventing sensitive internals or credentials from leaking
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FailureCategory(str, Enum):
    """Categorized taxonomy of decision cycle failures."""

    API_TRANSIENT = "API_TRANSIENT"  # 5xx, timeouts, network glitches (Retryable)
    RATE_LIMIT = "RATE_LIMIT"  # 429 ResourceExhausted (Retryable with backoff)
    AUTHENTICATION = "AUTHENTICATION"  # 401/403 invalid API keys (Permanent)
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"  # Validation failed, bad JSON (Retryable once)
    TOOL_CALL_ERROR = "TOOL_CALL_ERROR"  # Unauthorized or malformed tool call (Permanent)
    MAX_TURNS_EXCEEDED = "MAX_TURNS_EXCEEDED"  # Model loop bound reached (Permanent)
    TOOL_EXECUTION_FAILURE = "TOOL_EXECUTION_FAILURE"  # Tool handler unexpected crash (Permanent)
    INTERNAL_EXCEPTION = "INTERNAL_EXCEPTION"  # Unexpected runtime error in cycle (Permanent)
    NONE = "NONE"  # Cycle completed normally (Non-failure)


class FailurePolicyConfig(BaseModel):
    """Configuration governing retry boundaries and auto-pause thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum retry attempts per candle bar for retryable failures",
    )
    initial_backoff_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Base backoff delay in seconds (0.0 for tests and fast simulations)",
    )
    backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        description="Multiplicative backoff factor between consecutive retries",
    )
    max_consecutive_failures: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Consecutive failure threshold before triggering auto-pause",
    )

    @classmethod
    @field_validator("max_consecutive_failures", mode="before")
    def _validate_max_consecutive(cls, v: Any) -> Any:
        return v

    def __init__(self, **data: Any) -> None:
        if "auto_pause_threshold" in data and "max_consecutive_failures" not in data:
            data["max_consecutive_failures"] = data.pop("auto_pause_threshold")
        elif "auto_pause_threshold" in data:
            data.pop("auto_pause_threshold")
        if "retry_delay_seconds" in data and "initial_backoff_seconds" not in data:
            data["initial_backoff_seconds"] = data.pop("retry_delay_seconds")
        elif "retry_delay_seconds" in data:
            data.pop("retry_delay_seconds")
        super().__init__(**data)

    @property
    def auto_pause_threshold(self) -> int:
        return self.max_consecutive_failures

    @property
    def retry_delay_seconds(self) -> float:
        return self.initial_backoff_seconds


class AgentFailureState(BaseModel):
    """Immutable state snapshot tracking failure counts and pause status for an agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(..., description="Target trading agent identifier")
    simulation_id: Optional[str] = Field(
        default=None, description="Associated simulation ID if any"
    )
    consecutive_failures: int = Field(
        default=0, ge=0, description="Current count of consecutive cycle failures"
    )
    total_failures: int = Field(
        default=0, ge=0, description="Lifetime count of cycle failures encountered"
    )
    last_failure_time: Optional[datetime] = Field(
        default=None, description="Timestamp of the most recent failure event (UTC)"
    )
    last_failure_category: Optional[FailureCategory] = Field(
        default=None, description="Category of the most recent failure"
    )
    last_failure_error: Optional[str] = Field(
        default=None, description="Sanitized diagnostic summary of the most recent failure"
    )
    is_paused: bool = Field(default=False, description="Whether the agent is currently auto-paused")
    pause_reason: Optional[str] = Field(
        default=None, description="Explanatory reason why the agent was paused"
    )
    paused_at: Optional[datetime] = Field(
        default=None, description="Timestamp when auto-pause was triggered (UTC)"
    )

    @field_validator("last_failure_time", "paused_at", mode="before")
    @classmethod
    def _ensure_aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Ensure datetimes have UTC timezone."""
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
