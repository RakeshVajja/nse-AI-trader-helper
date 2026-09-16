"""Agent Mandate Creation from Natural-Language Strategy Prompt (Phase 8B).

Provides schema validation, prompt compilation, and persistence for converting
user natural-language strategy specifications into structured, reviewable mandates.
"""

from app.trading.agent.mandate.constants import (
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MAX_DAILY_LOSS,
    DEFAULT_MAX_POSITION_EXPOSURE,
    DEFAULT_RISK_PER_TRADE,
    DEFAULT_TIMEFRAME,
    INDICATOR_SYNONYMS,
    INSTRUMENT_SYNONYMS,
    SUPPORTED_EQUITIES,
    SUPPORTED_INDICATORS,
    SUPPORTED_INDICES,
    SUPPORTED_INSTRUMENTS,
    SUPPORTED_TIMEFRAMES,
    TIMEFRAME_SYNONYMS,
)
from app.trading.agent.mandate.generator import (
    build_mandate_prompt,
    generate_mandate,
    generate_mandate_async,
)
from app.trading.agent.mandate.schemas import (
    AgentCreateRequest,
    AgentListResponse,
    AgentMandate,
    AgentMandateCreateRequest,
    AgentMandateResponse,
    AgentResponse,
    AgentStatusResponse,
    AgentUpdateRequest,
    MandateGenerationError,
    StrategyStyle,
)
from app.trading.agent.mandate.service import (
    create_agent_with_mandate,
    get_or_create_instrument,
)

__all__ = [
    "DEFAULT_INITIAL_CAPITAL",
    "DEFAULT_MAX_DAILY_LOSS",
    "DEFAULT_MAX_POSITION_EXPOSURE",
    "DEFAULT_RISK_PER_TRADE",
    "DEFAULT_TIMEFRAME",
    "INDICATOR_SYNONYMS",
    "INSTRUMENT_SYNONYMS",
    "SUPPORTED_EQUITIES",
    "SUPPORTED_INDICATORS",
    "SUPPORTED_INDICES",
    "SUPPORTED_INSTRUMENTS",
    "SUPPORTED_TIMEFRAMES",
    "TIMEFRAME_SYNONYMS",
    "AgentCreateRequest",
    "AgentListResponse",
    "AgentMandate",
    "AgentMandateCreateRequest",
    "AgentMandateResponse",
    "AgentResponse",
    "AgentStatusResponse",
    "AgentUpdateRequest",
    "MandateGenerationError",
    "StrategyStyle",
    "build_mandate_prompt",
    "create_agent_with_mandate",
    "generate_mandate",
    "generate_mandate_async",
    "get_or_create_instrument",
]
