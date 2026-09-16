"""Configuration and settings integration for Gemini LLM client (Phase 8A)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings, get_settings


class GeminiConfig(BaseModel):
    """Configuration options for Google GenAI client and model requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: str = Field(
        default="",
        description="Google Gemini API key. If empty, loaded from application settings.",
    )
    model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model identifier (e.g., gemini-2.5-flash).",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.0 for deterministic output).",
    )
    max_output_tokens: Optional[int] = Field(
        default=None,
        gt=0,
        description="Optional upper bound on generated tokens.",
    )
    timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="API request timeout in seconds.",
    )

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> GeminiConfig:
        """Create a GeminiConfig instance derived from active application Settings."""
        s = settings or get_settings()
        return cls(
            api_key=s.GEMINI_API_KEY,
            model=s.GEMINI_MODEL or "gemini-2.5-flash",
        )
