"""Pydantic schemas and typed request/response boundaries for Gemini integration (Phase 8A).

Enforces:
- model_config = ConfigDict(extra="forbid", frozen=True)
- Strong typing and explicit categorization of responses and errors
- Clean domain isolation preventing google.genai types from leaking outside this package
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.trading.agent.schemas import AgentDecision


class GeminiErrorType(str, Enum):
    """Categorized error taxonomy for Gemini API interactions."""

    API_ERROR = "API_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    STRUCTURED_OUTPUT_ERROR = "STRUCTURED_OUTPUT_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    TOOL_CALL_ERROR = "TOOL_CALL_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"


class GeminiIntegrationError(Exception):
    """Base exception for all Gemini integration errors."""

    def __init__(
        self,
        message: str,
        error_type: GeminiErrorType = GeminiErrorType.API_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.details = details or {}


class GeminiStructuredOutputError(GeminiIntegrationError):
    """Exception raised when model output fails validation against AgentDecision."""

    def __init__(self, message: str, raw_text: Optional[str] = None) -> None:
        super().__init__(
            message=message,
            error_type=GeminiErrorType.STRUCTURED_OUTPUT_ERROR,
            details={"raw_text": raw_text},
        )
        self.raw_text = raw_text


class GeminiToolCall(BaseModel):
    """Untrusted function call request emitted by the Gemini model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., description="Target tool name requested by model")
    args: Dict[str, Any] = Field(
        default_factory=dict, description="Raw keyword arguments supplied by model"
    )
    call_id: Optional[str] = Field(default=None, description="Optional call identifier from SDK")


class GeminiToolResponse(BaseModel):
    """Tool execution output envelope formatted to feed back into Gemini conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., description="Name of the invoked tool")
    response: Dict[str, Any] = Field(
        ..., description="Structured dictionary response from tool execution"
    )


class GeminiMessage(BaseModel):
    """Internal message turn representation for multi-turn Gemini exchanges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str = Field(..., description="Turn participant: 'user', 'model', or 'tool'")
    content: Optional[str] = Field(default=None, description="Textual content for turn")
    tool_calls: List[GeminiToolCall] = Field(
        default_factory=list, description="Tool calls emitted by model during this turn"
    )
    tool_responses: List[GeminiToolResponse] = Field(
        default_factory=list, description="Tool outputs provided back during this turn"
    )


class GeminiRequest(BaseModel):
    """Structured request payload dispatched to Gemini model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: Optional[str] = Field(
        default=None, description="Primary prompt text for single-turn requests"
    )
    system_instruction: Optional[str] = Field(
        default=None, description="System instruction guiding model reasoning"
    )
    messages: List[GeminiMessage] = Field(
        default_factory=list, description="Sequential multi-turn message history"
    )
    tools_enabled: bool = Field(
        default=False, description="Whether to attach tool declarations to request"
    )
    allowed_tool_names: Optional[List[str]] = Field(
        default=None,
        description="Optional subset of Phase 7 tools to expose. If None, exposes all registered tools.",
    )
    structured_output: bool = Field(
        default=True,
        description="Whether to enforce structured output conforming to AgentDecision schema",
    )
    temperature: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Optional temperature override for this request",
    )


class GeminiResponse(BaseModel):
    """Standardized response envelope returned by GeminiClient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    success: bool = Field(
        ..., description="True if generation succeeded and outputs conform to schema"
    )
    decision: Optional[AgentDecision] = Field(
        default=None, description="Parsed and validated AgentDecision when structured_output=True"
    )
    tool_calls: List[GeminiToolCall] = Field(
        default_factory=list, description="Tool calls requested by model"
    )
    raw_text: Optional[str] = Field(default=None, description="Raw text generated by the model")
    prompt_tokens: int = Field(default=0, ge=0, description="Tokens consumed by input prompt")
    completion_tokens: int = Field(
        default=0, ge=0, description="Tokens generated by candidate output"
    )
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed in interaction")
    latency_ms: float = Field(
        default=0.0, ge=0.0, description="End-to-end request latency in milliseconds"
    )
    finish_reason: Optional[str] = Field(
        default=None, description="Finish reason from model candidate (e.g. STOP, MAX_TOKENS)"
    )
    error: Optional[str] = Field(
        default=None, description="Diagnostic error message if generation failed"
    )
    error_type: Optional[GeminiErrorType] = Field(
        default=None, description="Categorized error type if generation failed"
    )
