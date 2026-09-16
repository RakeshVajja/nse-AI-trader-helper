"""Phase 8E: Agent Failure Handling & Auto-Pause package.

Exports:
- AgentFailureHandler: Policy controller managing retries, failure tracking, and auto-pause
- AgentFailureState: Immutable state schema tracking failure counts and pause status
- AgentSafetyService: Service integrating simulation pause control and DB persistence
- FailureCategory: Categorized failure taxonomy
- FailurePolicyConfig: Configuration for retry boundaries and auto-pause thresholds
- classify_cycle_result: Classification function mapping cycle results to failure categories
- sanitize_error_message: Sanitization helper preventing credentials or secrets leakage
"""

from __future__ import annotations

from app.trading.agent.safety.classifier import (
    classify_cycle_result,
    sanitize_error_message,
)
from app.trading.agent.safety.handler import AgentFailureHandler
from app.trading.agent.safety.schemas import (
    AgentFailureState,
    FailureCategory,
    FailurePolicyConfig,
)
from app.trading.agent.safety.service import AgentSafetyService

__all__ = [
    "AgentFailureHandler",
    "AgentFailureState",
    "AgentSafetyService",
    "FailureCategory",
    "FailurePolicyConfig",
    "classify_cycle_result",
    "sanitize_error_message",
]
