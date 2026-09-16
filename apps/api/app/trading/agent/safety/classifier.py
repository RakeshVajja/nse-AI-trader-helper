"""Failure classification logic for Phase 8E: Agent Failure Handling & Auto-Pause.

Maps DecisionCycleResult outcomes and GeminiErrorType taxonomies into deterministic
FailureCategory definitions, determining retryability while sanitizing diagnostic messages.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from app.trading.agent.cycle.schemas import CycleStatus, DecisionCycleResult
from app.trading.agent.safety.schemas import FailureCategory

# Patterns that might contain sensitive credentials or internal paths
_API_KEY_PATTERN = re.compile(r"(AIza[0-9A-Za-z-_]{35}|key=[^\s&]+)", re.IGNORECASE)
_CREDENTIAL_PATTERN = re.compile(
    r"(bearer\s+[A-Za-z0-9_\-\.]+|token=[^\s&]+|secret=[^\s&]+|password=[^\s&]+)",
    re.IGNORECASE,
)
_PATH_PATTERN = re.compile(
    r"(/Users/[^\s:]+|/home/[^\s:]+|/tmp/[^\s:]+|/app/[^\s:]+|/var/[^\s:]+|[a-zA-Z]:\\[^\s:]+)"
)


def sanitize_error_message(error: Optional[str]) -> str:
    """Sanitize error messages to prevent credentials, secrets, or internal paths from leaking."""
    if not error:
        return "Unknown error."
    clean = str(error).strip()
    # Strip raw stack trace if present
    if "Traceback (most recent call last):" in clean:
        prefix = clean.split("Traceback (most recent call last):")[0].strip()
        clean = prefix or "Internal exception encountered."
    clean = _API_KEY_PATTERN.sub("[REDACTED_API_KEY]", clean)
    clean = _CREDENTIAL_PATTERN.sub("[REDACTED_CREDENTIAL]", clean)
    clean = _PATH_PATTERN.sub("[REDACTED_PATH]", clean)
    # Bound maximum length of user-facing diagnostic
    if len(clean) > 200:
        clean = clean[:197] + "..."
    return clean


def classify_cycle_result(
    result: DecisionCycleResult,
) -> Tuple[Optional[FailureCategory], bool, Optional[str]]:
    """Classify a DecisionCycleResult into a failure category and determine retryability.

    Returns:
        Tuple of (category, is_retryable, sanitized_error_message)

    Non-failure outcomes:
        - SUCCESS, TOOL_ORDER_STAGED, DECISION_ORDER_STAGED, NO_ACTION, SKIPPED_DUPLICATE
          return (None, False, None).
        - Normal risk rejections during tool execution or reconciliation are domain guards,
          NOT agent failures, and return (None, False, None).
    """
    # 1. Non-failure statuses
    if result.status in (
        CycleStatus.SUCCESS,
        CycleStatus.TOOL_ORDER_STAGED,
        CycleStatus.DECISION_ORDER_STAGED,
        CycleStatus.NO_ACTION,
        CycleStatus.SKIPPED_DUPLICATE,
    ):
        return None, False, None

    err_str = (result.error or "").lower()

    # Normal risk checks (domain guards, not agent failures)
    if any(
        k in err_str
        for k in (
            "risk check failed",
            "risk limit violated",
            "order rejected by risk engine",
            "position limit",
            "capital limit",
        )
    ):
        return None, False, None

    sanitized_err = sanitize_error_message(result.error)

    # 2. Maximum reasoning turns exhausted
    if result.status == CycleStatus.MAX_TURNS_EXCEEDED:
        return (
            FailureCategory.MAX_TURNS_EXCEEDED,
            False,
            sanitized_err or "Maximum reasoning turns exceeded without decision.",
        )

    # 3. Check for tool execution crashes if any tool failed with internal exception
    for tex in result.tool_executions:
        if not tex.success and tex.error_type in (
            "HANDLER_EXCEPTION",
            "UNHANDLED_EXCEPTION",
            "EXECUTION_ERROR",
        ):
            return (
                FailureCategory.TOOL_EXECUTION_FAILURE,
                False,
                f"Tool execution failed in {tex.tool_name}: {sanitize_error_message(tex.error)}",
            )

    # 4. Check for explicit tool execution crash in error text
    if any(
        k in err_str
        for k in ("tool execution crashed", "tool execution failed", "zerodivisionerror")
    ):
        return FailureCategory.TOOL_EXECUTION_FAILURE, False, sanitized_err

    # 5. Unauthorized or malformed tool call from model (Permanent)
    if any(
        k in err_str
        for k in (
            "tool_call_error",
            "unauthorized tool",
            "unregistered tool",
            "unknown tool",
            "tool call error",
        )
    ):
        return FailureCategory.TOOL_CALL_ERROR, False, sanitized_err

    # 6. Authentication errors (Permanent)
    if any(
        k in err_str
        for k in (
            "auth_error",
            "unauthorized access",
            "unauthorized",
            "invalid api key",
            "401",
            "403",
            "permission",
            "api key invalid",
            "authentication",
        )
    ):
        return FailureCategory.AUTHENTICATION, False, sanitized_err

    # 7. Rate limiting / quota errors (Permanent within immediate bar, require manual quota renewal or wait)
    if any(
        k in err_str
        for k in (
            "rate_limit",
            "resourceexhausted",
            "resource_exhausted",
            "quota",
            "429",
            "too many requests",
        )
    ):
        return FailureCategory.RATE_LIMIT, False, sanitized_err

    # 8. Structured output validation / malformed JSON (Permanent)
    if any(
        k in err_str
        for k in (
            "structured_output",
            "malformed_response",
            "malformed",
            "jsondecodeerror",
            "validation error",
            "schema",
        )
    ):
        return FailureCategory.MALFORMED_OUTPUT, False, sanitized_err

    # 9. Transient API errors: timeouts, network, 5xx (Retryable)
    if any(
        k in err_str
        for k in (
            "api_error",
            "timeout",
            "timed out",
            "deadline",
            "500",
            "502",
            "503",
            "504",
            "connection",
            "network",
            "transient",
            "unavailable",
            "bad gateway",
            "connection reset",
        )
    ):
        return FailureCategory.API_TRANSIENT, True, sanitized_err

    # 10. Fallback unexpected internal exception (Permanent)
    return (
        FailureCategory.INTERNAL_EXCEPTION,
        False,
        sanitized_err or "Unexpected internal cycle failure.",
    )
