"""Phase 8D: Compact Bounded Agent Memory package.

Exports:
- MemoryDecisionRecord: Compact record of a historical agent decision
- MemoryTradeRecord: Compact record of a closed trade
- AgentMemory: Bounded container of recent decisions (<=5) and trades (<=10)
- AgentMemoryService: Service for extracting and recording bounded agent memory
"""

from __future__ import annotations

from app.trading.agent.memory.schemas import (
    MAX_RECENT_DECISIONS,
    MAX_RECENT_TRADES,
    AgentMemory,
    MemoryDecisionRecord,
    MemoryTradeRecord,
)
from app.trading.agent.memory.service import AgentMemoryService

__all__ = [
    "MAX_RECENT_DECISIONS",
    "MAX_RECENT_TRADES",
    "AgentMemory",
    "AgentMemoryService",
    "MemoryDecisionRecord",
    "MemoryTradeRecord",
]
