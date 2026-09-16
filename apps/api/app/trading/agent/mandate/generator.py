"""Generator compiling natural-language strategy prompts into structured AgentMandates (Phase 8B)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from pydantic import ValidationError

from app.trading.agent.gemini import GeminiClient, GeminiErrorType, GeminiRequest
from app.trading.agent.mandate.constants import (
    INDICATOR_SYNONYMS,
    INSTRUMENT_SYNONYMS,
    SUPPORTED_INDICATORS,
    SUPPORTED_INSTRUMENTS,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_SYNONYMS,
)
from app.trading.agent.mandate.schemas import (
    AgentMandate,
    AgentMandateCreateRequest,
    AgentMandateResponse,
)

logger = logging.getLogger(__name__)

MANDATE_SYSTEM_INSTRUCTION = f"""You are an expert quantitative trading system compiler.
Your task is to convert a user's natural-language trading strategy into a structured, declarative trading mandate conforming strictly to the requested JSON schema.

STRICT CONSTRAINTS:
1. Supported Technical Indicators ONLY: {sorted(SUPPORTED_INDICATORS)}. Do NOT invent or include unsupported indicators (such as Bollinger Bands, Supertrend, Stochastics, VWAP). If the user asks for unsupported indicators, exclude them and select only the closest supported indicators.
2. Supported Instruments: {sorted(SUPPORTED_INSTRUMENTS)}.
3. Supported Timeframes: {sorted(SUPPORTED_TIMEFRAMES)}.
4. Strategy Styles: 'momentum', 'trend_following', 'mean_reversion', 'breakout', 'scalping', 'hybrid', 'custom'.
5. Objectives: 1 to 5 concise declarative bullet points stating the strategic goal (e.g. 'capture bullish momentum above EMA20', 'avoid choppy consolidations').
6. Declarative Specification: The output is a declarative configuration of intent and boundaries, NOT an execution action. Do NOT output executable code, Python, SQL, shell commands, or specific per-candle trade decisions.

You must output ONLY a valid JSON object matching this schema:
{{
  "strategy_style": "momentum",
  "objectives": [
    "capture bullish momentum",
    "avoid weak setups"
  ],
  "preferred_indicators": [
    "EMA9",
    "EMA20",
    "RSI14",
    "MACD"
  ],
  "instrument": "RELIANCE",
  "timeframe": "15m",
  "risk_per_trade": 0.02,
  "max_position_exposure": 0.25,
  "max_daily_loss": 0.05,
  "rationale": "Translated user momentum strategy prioritizing trend-following with RSI confirmation."
}}
"""


def build_mandate_prompt(request: AgentMandateCreateRequest) -> str:
    """Build the user prompt string providing the strategy text and target configuration."""
    parts = [
        f"Agent Name: {request.agent_name}",
        f"Target Instrument: {request.instrument or 'RELIANCE'}",
        f"Target Timeframe: {request.timeframe or '15m'}",
        f"Max Risk Per Trade: {request.max_risk_per_trade or 0.02}",
        f"Max Position Exposure: {request.max_position_exposure or 0.25}",
        f"Max Daily Loss: {request.max_daily_loss or 0.05}",
        "",
        "User Natural-Language Strategy Description:",
        f'"{request.strategy_prompt.strip()}"',
        "",
        "Compile this strategy into the exact declarative JSON mandate.",
    ]
    return "\n".join(parts)


def _normalize_extracted_dict(
    data: Dict[str, Any], request: AgentMandateCreateRequest
) -> Dict[str, Any]:
    """Normalize indicators, instruments, timeframes, and inject request fallbacks."""
    # 1. Normalize Instrument
    raw_inst = str(data.get("instrument") or request.instrument or "RELIANCE").strip().lower()
    inst = INSTRUMENT_SYNONYMS.get(raw_inst, raw_inst.upper())
    data["instrument"] = inst

    # 2. Normalize Timeframe
    raw_tf = str(data.get("timeframe") or request.timeframe or "15m").strip().lower()
    tf = TIMEFRAME_SYNONYMS.get(raw_tf, raw_tf)
    data["timeframe"] = tf

    # 3. Normalize Indicators
    raw_inds = data.get("preferred_indicators") or []
    if not isinstance(raw_inds, list):
        raw_inds = [raw_inds]

    normalized_inds = []
    for ind in raw_inds:
        clean = str(ind).strip().lower()
        canonical = INDICATOR_SYNONYMS.get(clean)
        if not canonical:
            # Try removing spaces/underscores
            condensed = clean.replace(" ", "").replace("_", "")
            canonical = INDICATOR_SYNONYMS.get(condensed)
        if canonical:
            if canonical not in normalized_inds:
                normalized_inds.append(canonical)
        else:
            # Keep original for Pydantic validator to check against whitelist
            normalized_inds.append(str(ind).strip().upper())
    data["preferred_indicators"] = normalized_inds

    # 4. Fallback risk values if model omitted them
    if data.get("risk_per_trade") is None:
        data["risk_per_trade"] = request.max_risk_per_trade or 0.02
    if data.get("max_position_exposure") is None:
        data["max_position_exposure"] = request.max_position_exposure or 0.25
    if data.get("max_daily_loss") is None:
        data["max_daily_loss"] = request.max_daily_loss or 0.05

    # 5. Objectives validation
    if not data.get("objectives"):
        data["objectives"] = ["Execute strategy according to user prompt rules"]

    return data


def _parse_and_validate_mandate(
    raw_text: str,
    request: AgentMandateCreateRequest,
) -> AgentMandate:
    """Parse raw model JSON string, normalize terms, and validate against AgentMandate schema."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise ValueError(f"Model output is not valid JSON: {err}") from err

    if not isinstance(parsed, dict):
        raise TypeError("Model output JSON must be a dictionary.")

    normalized = _normalize_extracted_dict(parsed, request)
    return AgentMandate.model_validate(normalized)


def generate_mandate(
    client: GeminiClient,
    request: AgentMandateCreateRequest,
) -> AgentMandateResponse:
    """Synchronously generate and validate a structured AgentMandate via GeminiClient."""
    gemini_req = GeminiRequest(
        prompt=build_mandate_prompt(request),
        system_instruction=MANDATE_SYSTEM_INSTRUCTION,
        tools_enabled=False,
        structured_output=False,
        temperature=0.0,
    )

    resp = client.generate(gemini_req)
    if not resp.success:
        return AgentMandateResponse(
            success=False,
            mandate=None,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error=resp.error,
            error_type=resp.error_type,
        )

    if not resp.raw_text:
        return AgentMandateResponse(
            success=False,
            mandate=None,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error="Gemini returned empty text response for mandate generation.",
            error_type=GeminiErrorType.MALFORMED_RESPONSE,
        )

    try:
        mandate = _parse_and_validate_mandate(resp.raw_text, request)
        return AgentMandateResponse(
            success=True,
            mandate=mandate,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error=None,
            error_type=None,
        )
    except (ValidationError, ValueError, TypeError) as val_err:
        logger.warning("Mandate validation failed: %s", val_err)
        return AgentMandateResponse(
            success=False,
            mandate=None,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error=f"Generated mandate failed validation: {val_err}",
            error_type=GeminiErrorType.STRUCTURED_OUTPUT_ERROR,
        )


async def generate_mandate_async(
    client: GeminiClient,
    request: AgentMandateCreateRequest,
) -> AgentMandateResponse:
    """Asynchronously generate and validate a structured AgentMandate via GeminiClient."""
    gemini_req = GeminiRequest(
        prompt=build_mandate_prompt(request),
        system_instruction=MANDATE_SYSTEM_INSTRUCTION,
        tools_enabled=False,
        structured_output=False,
        temperature=0.0,
    )

    resp = await client.generate_async(gemini_req)
    if not resp.success:
        return AgentMandateResponse(
            success=False,
            mandate=None,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error=resp.error,
            error_type=resp.error_type,
        )

    if not resp.raw_text:
        return AgentMandateResponse(
            success=False,
            mandate=None,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error="Gemini returned empty text response for mandate generation.",
            error_type=GeminiErrorType.MALFORMED_RESPONSE,
        )

    try:
        mandate = _parse_and_validate_mandate(resp.raw_text, request)
        return AgentMandateResponse(
            success=True,
            mandate=mandate,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error=None,
            error_type=None,
        )
    except (ValidationError, ValueError, TypeError) as val_err:
        logger.warning("Mandate validation failed: %s", val_err)
        return AgentMandateResponse(
            success=False,
            mandate=None,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=resp.latency_ms,
            error=f"Generated mandate failed validation: {val_err}",
            error_type=GeminiErrorType.STRUCTURED_OUTPUT_ERROR,
        )
