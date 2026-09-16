"""Gemini Reasoning Agent integration package (Phase 8A).

Provides isolated, typed Function Calling and Structured Output capabilities
interfacing with Google Gemini models via google-genai.
"""

from app.trading.agent.gemini.client import GeminiClient
from app.trading.agent.gemini.config import GeminiConfig
from app.trading.agent.gemini.schemas import (
    GeminiErrorType,
    GeminiIntegrationError,
    GeminiMessage,
    GeminiRequest,
    GeminiResponse,
    GeminiStructuredOutputError,
    GeminiToolCall,
    GeminiToolResponse,
)
from app.trading.agent.gemini.tools import (
    build_gemini_tools,
    validate_gemini_tool_call,
)

__all__ = [
    "GeminiClient",
    "GeminiConfig",
    "GeminiErrorType",
    "GeminiIntegrationError",
    "GeminiMessage",
    "GeminiRequest",
    "GeminiResponse",
    "GeminiStructuredOutputError",
    "GeminiToolCall",
    "GeminiToolResponse",
    "build_gemini_tools",
    "validate_gemini_tool_call",
]
