"""Typed Pydantic schemas for Phase 8D: Compact Bounded Agent Memory.

Enforces:
- Maximum 5 recent AgentDecision records
- Maximum 10 recent closed TradeRecord items
- Deterministic most-recent-first ordering
- Payload boundedness via string truncation
- Complete separation of historical context from authoritative current state
- No raw SDK objects or chain-of-thought
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.trading.agent.schemas import AgentAction
from app.trading.schemas import OrderSide

MAX_RECENT_DECISIONS: int = 5
MAX_RECENT_TRADES: int = 10
MAX_REASON_LENGTH: int = 150
MAX_OBSERVATION_LENGTH: int = 80
MAX_OBSERVATIONS_COUNT: int = 2


class MemoryDecisionRecord(BaseModel):
    """Compact summary of a historical agent decision for bounded memory context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candle_timestamp: datetime = Field(
        ..., description="Timestamp of the completed candle when decision was rendered (UTC)"
    )
    action: AgentAction = Field(..., description="Action chosen by the agent: BUY, SELL, or HOLD")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Agent decision confidence score")
    quantity: Optional[int] = Field(None, gt=0, description="Quantity traded, if applicable")
    reason: str = Field(..., description="Concise non-empty rationale, bounded in length")
    observations: List[str] = Field(
        default_factory=list,
        description="Top concise market observations (bounded to max 2 items)",
    )
    status: Optional[str] = Field(
        None, description="Cycle reconciliation status (e.g. TOOL_ORDER_STAGED, NO_ACTION)"
    )
    staged_order_id: Optional[str] = Field(
        None, description="Order ID staged during that cycle, if any"
    )

    @field_validator("candle_timestamp", mode="before")
    @classmethod
    def _ensure_aware(cls, value: datetime) -> datetime:
        """Ensure candle_timestamp has UTC timezone."""
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def _truncate_reason(cls, value: str) -> str:
        """Enforce strict length boundary on decision rationale."""
        if not value:
            return "No reason recorded."
        val_str = str(value).strip()
        if len(val_str) > MAX_REASON_LENGTH:
            return val_str[: MAX_REASON_LENGTH - 3] + "..."
        return val_str

    @field_validator("observations", mode="before")
    @classmethod
    def _bound_observations(cls, value: List[str]) -> List[str]:
        """Bound observations to top items and bounded character lengths."""
        if not value:
            return []
        bounded: List[str] = []
        for item in value[:MAX_OBSERVATIONS_COUNT]:
            s = str(item).strip()
            if len(s) > MAX_OBSERVATION_LENGTH:
                s = s[: MAX_OBSERVATION_LENGTH - 3] + "..."
            if s:
                bounded.append(s)
        return bounded


class MemoryTradeRecord(BaseModel):
    """Compact summary of an executed and closed trade for bounded memory context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: str = Field(..., description="Unique trade identifier")
    symbol: str = Field(..., description="Trading instrument symbol")
    side: OrderSide = Field(..., description="Trade side (BUY/SELL)")
    quantity: int = Field(..., gt=0, description="Executed trade quantity")
    entry_price: float = Field(..., gt=0.0, description="Average entry fill price")
    exit_price: float = Field(..., gt=0.0, description="Exit fill price")
    gross_pnl: float = Field(..., description="Gross realized profit/loss")
    net_pnl: float = Field(..., description="Net realized profit/loss after transaction costs")
    entry_time: datetime = Field(..., description="Timestamp of trade entry (UTC)")
    exit_time: datetime = Field(..., description="Timestamp of trade exit (UTC)")
    exit_reason: str = Field(
        default="MANUAL_EXIT",
        description="Exit reason (e.g. STOP_LOSS, TAKE_PROFIT, MANUAL_EXIT)",
    )

    @field_validator("entry_time", "exit_time", mode="before")
    @classmethod
    def _ensure_aware(cls, value: datetime) -> datetime:
        """Ensure trade timestamps have UTC timezone."""
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class AgentMemory(BaseModel):
    """Bounded, compact container of historical agent decisions and closed trades."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recent_decisions: List[MemoryDecisionRecord] = Field(
        default_factory=list,
        max_length=MAX_RECENT_DECISIONS,
        description="Last N decisions (max 5), ordered most-recent-first",
    )
    recent_trades: List[MemoryTradeRecord] = Field(
        default_factory=list,
        max_length=MAX_RECENT_TRADES,
        description="Last M closed trades (max 10), ordered most-recent-first",
    )
    agent_id: Optional[str] = Field(None, description="Associated agent ID")
    simulation_id: Optional[str] = Field(None, description="Associated simulation ID")
    as_of_time: Optional[datetime] = Field(
        None, description="Temporal boundary timestamp (all records <= as_of_time)"
    )

    @field_validator("as_of_time", mode="before")
    @classmethod
    def _ensure_aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Ensure as_of_time has UTC timezone if present."""
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @property
    def is_empty(self) -> bool:
        """Check whether memory contains any historical records."""
        return len(self.recent_decisions) == 0 and len(self.recent_trades) == 0

    def format_prompt_block(self) -> str:
        """Format bounded memory into a structured, clear context block for Gemini.

        Explicitly emphasizes that memory is past history and does NOT represent
        current active positions or account balance.
        """
        if self.is_empty:
            return ""

        lines: List[str] = [
            "=== HISTORICAL AGENT MEMORY (PRIOR CONTEXT ONLY) ===",
            "NOTE: The following records represent past historical cycles and completed trades for context.",
            "They do NOT represent the current account balance, current price, or open position state.\n",
        ]

        # 1. Recent Decisions
        if self.recent_decisions:
            lines.append(f"[Recent Past Decisions (last {len(self.recent_decisions)} <= 5)]:")
            for idx, dec in enumerate(self.recent_decisions, start=1):
                ts_str = dec.candle_timestamp.isoformat()
                qty_str = f", Qty={dec.quantity}" if dec.quantity else ""
                status_str = f", Status={dec.status}" if dec.status else ""
                obs_str = f", Obs={dec.observations}" if dec.observations else ""
                lines.append(
                    f"{idx}. [{ts_str}] Action={dec.action.value}, Conf={dec.confidence:.2f}{qty_str}{status_str}, "
                    f'Reason="{dec.reason}"{obs_str}'
                )
            lines.append("")

        # 2. Recent Closed Trades
        if self.recent_trades:
            lines.append(f"[Recent Closed Trades (last {len(self.recent_trades)} <= 10)]:")
            for idx, tr in enumerate(self.recent_trades, start=1):
                lines.append(
                    f"{idx}. Trade {tr.trade_id} ({tr.symbol}): {tr.side.value} {tr.quantity} shares "
                    f"@ ₹{tr.entry_price:.2f} -> Exit @ ₹{tr.exit_price:.2f}, "
                    f"Net PnL: ₹{tr.net_pnl:,.2f} (Reason: {tr.exit_reason}, Exit Time: {tr.exit_time.isoformat()})"
                )
            lines.append("")

        return "\n".join(lines)
