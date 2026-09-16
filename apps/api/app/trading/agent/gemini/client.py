"""Gemini client integration with Function Calling and Structured Outputs (Phase 8A)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, List, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.trading.agent.gemini.config import GeminiConfig
from app.trading.agent.gemini.schemas import (
    GeminiErrorType,
    GeminiRequest,
    GeminiResponse,
    GeminiToolCall,
)
from app.trading.agent.gemini.tools import (
    build_gemini_tools,
    validate_gemini_tool_call,
)
from app.trading.agent.harness import (
    ToolRegistry,
    create_default_tool_registry,
)
from app.trading.agent.schemas import AgentDecision

logger = logging.getLogger(__name__)


class GeminiClient:
    """Safe, isolated wrapper over google.genai Client.

    Responsibilities:
    - Derives Function Calling declarations from the frozen Phase 7 ToolRegistry
    - Configures and parses Structured Outputs adhering to the frozen AgentDecision schema
    - Prevents google.genai SDK objects from leaking outside this package
    - Safely traps and classifies SDK and validation errors into typed GeminiResponse envelopes
    """

    def __init__(
        self,
        config: Optional[GeminiConfig] = None,
        registry: Optional[ToolRegistry] = None,
        genai_client: Optional[Any] = None,
    ) -> None:
        self.config = config or GeminiConfig.from_settings()
        self.registry = registry or create_default_tool_registry()

        if genai_client is not None:
            self._client = genai_client
        elif self.config.api_key and self.config.api_key.strip():
            self._client = genai.Client(api_key=self.config.api_key.strip())
        else:
            self._client = None

    def _build_config(self, request: GeminiRequest) -> types.GenerateContentConfig:
        """Construct the SDK GenerateContentConfig based on request options."""
        config_kwargs: dict[str, Any] = {}

        if request.system_instruction:
            config_kwargs["system_instruction"] = request.system_instruction

        temp = request.temperature if request.temperature is not None else self.config.temperature
        config_kwargs["temperature"] = temp

        if self.config.max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = self.config.max_output_tokens

        if request.tools_enabled:
            tools = build_gemini_tools(self.registry, request.allowed_tool_names)
            if tools:
                config_kwargs["tools"] = tools

        if request.structured_output:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = AgentDecision

        return types.GenerateContentConfig(**config_kwargs)

    def _build_contents(self, request: GeminiRequest) -> List[types.Content]:
        """Translate internal GeminiRequest and messages into SDK types.Content list."""
        contents: List[types.Content] = []

        for msg in request.messages:
            parts: List[types.Part] = []
            if msg.content:
                parts.append(types.Part(text=msg.content))
            for tc in msg.tool_calls:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            name=tc.name,
                            args=tc.args,
                            id=tc.call_id,
                        )
                    )
                )
            for tr in msg.tool_responses:
                parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=tr.name,
                            response=tr.response,
                        )
                    )
                )
            if parts:
                contents.append(types.Content(role=msg.role, parts=parts))

        if request.prompt:
            contents.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=request.prompt)],
                )
            )

        return contents

    def _parse_response(
        self,
        raw_response: Any,
        latency_ms: float,
        structured_output_requested: bool,
    ) -> GeminiResponse:
        """Parse, validate, and normalize SDK response into domain GeminiResponse envelope."""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        usage = getattr(raw_response, "usage_metadata", None)
        if usage:
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = getattr(usage, "total_token_count", 0) or 0

        candidates = getattr(raw_response, "candidates", None)
        if not candidates or len(candidates) == 0:
            return GeminiResponse(
                success=False,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                error="Gemini API returned an empty response with no candidates.",
                error_type=GeminiErrorType.MALFORMED_RESPONSE,
            )

        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        finish_reason_str = (
            (finish_reason.name if hasattr(finish_reason, "name") else str(finish_reason))
            if finish_reason is not None
            else None
        )

        if finish_reason_str in (
            "SAFETY",
            "RECITATION",
            "BLOCKLIST",
            "PROHIBITED_CONTENT",
        ):
            return GeminiResponse(
                success=False,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason_str,
                error=f"Model output generation blocked by policy filter: {finish_reason_str}",
                error_type=GeminiErrorType.API_ERROR,
            )

        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            return GeminiResponse(
                success=False,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason_str,
                error="Candidate response contains no content parts.",
                error_type=GeminiErrorType.MALFORMED_RESPONSE,
            )

        tool_calls: List[GeminiToolCall] = []
        text_parts: List[str] = []
        unauthorized_tool_name: Optional[str] = None

        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc:
                fc_name = getattr(fc, "name", "")
                fc_args = dict(getattr(fc, "args", {}) or {})
                call_id = getattr(fc, "id", None)

                if not validate_gemini_tool_call(fc_name, self.registry):
                    unauthorized_tool_name = fc_name

                tool_calls.append(
                    GeminiToolCall(
                        name=fc_name,
                        args=fc_args,
                        call_id=call_id,
                    )
                )

            txt = getattr(part, "text", None)
            if txt:
                text_parts.append(txt)

        raw_text = "".join(text_parts).strip() if text_parts else None

        # Verify no unauthorized tool calls were requested
        if unauthorized_tool_name:
            return GeminiResponse(
                success=False,
                tool_calls=tool_calls,
                raw_text=raw_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason_str,
                error=f"Model requested unauthorized or unregistered tool: '{unauthorized_tool_name}'",
                error_type=GeminiErrorType.TOOL_CALL_ERROR,
            )

        # If model emitted tool calls, return them (function calling turn)
        if tool_calls:
            return GeminiResponse(
                success=True,
                decision=None,
                tool_calls=tool_calls,
                raw_text=raw_text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason_str,
                error=None,
                error_type=None,
            )

        # Handle Structured Output requirement
        if structured_output_requested:
            if not raw_text:
                return GeminiResponse(
                    success=False,
                    raw_text=None,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason_str,
                    error="Model did not produce any text payload for structured AgentDecision output.",
                    error_type=GeminiErrorType.STRUCTURED_OUTPUT_ERROR,
                )

            cleaned_json = raw_text
            if cleaned_json.startswith("```"):
                lines = cleaned_json.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned_json = "\n".join(lines).strip()

            try:
                decision = AgentDecision.model_validate_json(cleaned_json)
                return GeminiResponse(
                    success=True,
                    decision=decision,
                    tool_calls=[],
                    raw_text=raw_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason_str,
                    error=None,
                    error_type=None,
                )
            except (ValidationError, json.JSONDecodeError, ValueError) as val_err:
                logger.warning(
                    "Structured output failed AgentDecision validation: %s",
                    val_err,
                )
                return GeminiResponse(
                    success=False,
                    decision=None,
                    tool_calls=[],
                    raw_text=raw_text,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency_ms,
                    finish_reason=finish_reason_str,
                    error=f"Structured output failed AgentDecision validation: {val_err}",
                    error_type=GeminiErrorType.STRUCTURED_OUTPUT_ERROR,
                )

        # Plain text generation (structured_output=False)
        return GeminiResponse(
            success=True,
            decision=None,
            tool_calls=[],
            raw_text=raw_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason_str,
            error=None,
            error_type=None,
        )

    def _classify_exception(self, exc: Exception) -> tuple[str, GeminiErrorType]:
        """Classify an external SDK or network exception into a typed error."""
        exc_str = str(exc)
        if isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            if code in (401, 403) or "API_KEY" in exc_str or "PERMISSION_DENIED" in exc_str:
                return (f"Gemini API authentication failed: {exc_str}", GeminiErrorType.AUTH_ERROR)
            if code == 429 or "RESOURCE_EXHAUSTED" in exc_str or "quota" in exc_str.lower():
                return (
                    f"Gemini API rate limit or quota exceeded: {exc_str}",
                    GeminiErrorType.RATE_LIMIT_ERROR,
                )
            return (f"Gemini API error ({code}): {exc_str}", GeminiErrorType.API_ERROR)

        if "API_KEY" in exc_str or "credential" in exc_str.lower():
            return (f"Gemini authentication error: {exc_str}", GeminiErrorType.AUTH_ERROR)

        return (
            f"Unexpected error communicating with Gemini: {type(exc).__name__}: {exc_str}",
            GeminiErrorType.API_ERROR,
        )

    def generate(self, request: GeminiRequest) -> GeminiResponse:
        """Synchronously execute a Gemini model generation request."""
        if self._client is None:
            return GeminiResponse(
                success=False,
                error="Gemini API key is not configured and no client was injected.",
                error_type=GeminiErrorType.AUTH_ERROR,
            )

        t0 = time.perf_counter()
        try:
            config = self._build_config(request)
            contents = self._build_contents(request)
            raw_response = self._client.models.generate_content(
                model=self.config.model,
                contents=contents,
                config=config,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return self._parse_response(
                raw_response=raw_response,
                latency_ms=latency_ms,
                structured_output_requested=request.structured_output,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - t0) * 1000.0
            err_msg, err_type = self._classify_exception(exc)
            logger.error("Gemini sync generation failed: %s", err_msg)
            return GeminiResponse(
                success=False,
                latency_ms=latency_ms,
                error=err_msg,
                error_type=err_type,
            )

    async def generate_async(self, request: GeminiRequest) -> GeminiResponse:
        """Asynchronously execute a Gemini model generation request."""
        if self._client is None:
            return GeminiResponse(
                success=False,
                error="Gemini API key is not configured and no client was injected.",
                error_type=GeminiErrorType.AUTH_ERROR,
            )

        t0 = time.perf_counter()
        try:
            config = self._build_config(request)
            contents = self._build_contents(request)
            aio_client = getattr(self._client, "aio", None)
            if aio_client is not None and hasattr(aio_client, "models"):
                raw_response = await aio_client.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=config,
                )
            else:
                # Fallback to sync call if client doesn't support aio
                raw_response = self._client.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=config,
                )

            latency_ms = (time.perf_counter() - t0) * 1000.0
            return self._parse_response(
                raw_response=raw_response,
                latency_ms=latency_ms,
                structured_output_requested=request.structured_output,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - t0) * 1000.0
            err_msg, err_type = self._classify_exception(exc)
            logger.error("Gemini async generation failed: %s", err_msg)
            return GeminiResponse(
                success=False,
                latency_ms=latency_ms,
                error=err_msg,
                error_type=err_type,
            )
