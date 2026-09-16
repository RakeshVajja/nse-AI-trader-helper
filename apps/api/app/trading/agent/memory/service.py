"""Service layer for Phase 8D Compact Bounded Agent Memory retrieval and recording.

Enforces:
- Authoritative trade sourcing from PortfolioTracker
- Authoritative decision sourcing from DecisionCycleResult / database records
- Strict no-lookahead: decisions < t, trades exit_time <= t
- Isolation by (simulation_id, agent_id)
- Bounded capacity: max 5 decisions, max 10 closed trades (most-recent-first)
- Safe error containment: memory retrieval failures never fail the cycle or simulation
"""

from __future__ import annotations

import collections
import logging
import threading
from datetime import datetime, timezone
from typing import Deque, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.trading.agent.cycle.schemas import DecisionCycleResult
from app.trading.agent.memory.schemas import (
    MAX_RECENT_DECISIONS,
    MAX_RECENT_TRADES,
    AgentMemory,
    MemoryDecisionRecord,
    MemoryTradeRecord,
)
from app.trading.agent.schemas import AgentAction
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime has UTC timezone."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class AgentMemoryService:
    """Manages compact bounded historical context for trading agents."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # In-memory history keyed by (simulation_id, agent_id)
        # Keeps bounded deque of completed decisions
        self._decision_history: Dict[Tuple[Optional[str], str], Deque[MemoryDecisionRecord]] = {}

    def record_decision(
        self,
        agent_id: str,
        simulation_id: Optional[str],
        result: DecisionCycleResult,
    ) -> None:
        """Record an executed cycle outcome into the bounded in-memory tracker."""
        if result.decision is None:
            return

        staged_id: Optional[str] = None
        if result.reconciliation and result.reconciliation.order_staged:
            staged_id = result.reconciliation.order_id
        elif result.orders_staged:
            staged_id = result.orders_staged[0]

        record = MemoryDecisionRecord(
            candle_timestamp=result.candle_timestamp,
            action=result.decision.action,
            confidence=result.decision.confidence,
            quantity=result.decision.quantity,
            reason=result.decision.reason,
            observations=list(result.decision.observations),
            status=result.status.value if result.status else None,
            staged_order_id=staged_id,
        )

        key = (simulation_id, agent_id)
        with self._lock:
            if key not in self._decision_history:
                self._decision_history[key] = collections.deque(maxlen=20)
            self._decision_history[key].append(record)

    def get_memory_from_context(
        self,
        context: ToolExecutionContext,
        agent_id: str = "default-agent",
        simulation_id: Optional[str] = None,
    ) -> AgentMemory:
        """Construct bounded AgentMemory from authoritative context at virtual time t.

        Guarantees:
        - Past decisions strictly < context.virtual_time (no same-candle or future leakage)
        - Closed trades strictly <= context.virtual_time
        - Trades filtered by current symbol
        - Most-recent-first ordering
        - Bounded to max 5 decisions, max 10 trades
        """
        try:
            current_time = _ensure_utc(context.virtual_time)
            current_symbol = context.symbol.strip().upper()

            # 1. Closed Trades: authoritatively sourced from PortfolioTracker
            all_closed = context.portfolio.closed_trades
            eligible_trades = [
                tr
                for tr in all_closed
                if _ensure_utc(tr.exit_time) <= current_time
                and tr.symbol.strip().upper() == current_symbol
            ]
            # Order most-recent-first (descending exit_time)
            eligible_trades.sort(key=lambda x: _ensure_utc(x.exit_time), reverse=True)
            bounded_trades = [
                MemoryTradeRecord(
                    trade_id=tr.trade_id,
                    symbol=tr.symbol,
                    side=tr.side,
                    quantity=tr.quantity,
                    entry_price=tr.entry_price,
                    exit_price=tr.exit_price,
                    gross_pnl=tr.gross_pnl,
                    net_pnl=tr.net_pnl,
                    entry_time=_ensure_utc(tr.entry_time),
                    exit_time=_ensure_utc(tr.exit_time),
                    exit_reason=tr.exit_reason,
                )
                for tr in eligible_trades[:MAX_RECENT_TRADES]
            ]

            # 2. Decisions: authoritatively sourced from in-memory tracker
            key = (simulation_id, agent_id)
            with self._lock:
                history = list(self._decision_history.get(key, []))

            # Filter: strictly before current candle timestamp (no lookahead / no self-reference)
            eligible_decisions = [
                d for d in history if _ensure_utc(d.candle_timestamp) < current_time
            ]
            # Order most-recent-first (descending candle_timestamp)
            eligible_decisions.sort(key=lambda x: _ensure_utc(x.candle_timestamp), reverse=True)
            bounded_decisions = eligible_decisions[:MAX_RECENT_DECISIONS]

            return AgentMemory(
                recent_decisions=bounded_decisions,
                recent_trades=bounded_trades,
                agent_id=agent_id,
                simulation_id=simulation_id,
                as_of_time=current_time,
            )
        except Exception:
            logger.exception(
                "Error retrieving agent memory for sim '%s', agent '%s'; defaulting to empty memory",
                simulation_id,
                agent_id,
            )
            return AgentMemory(
                recent_decisions=[],
                recent_trades=[],
                agent_id=agent_id,
                simulation_id=simulation_id,
                as_of_time=context.virtual_time,
            )

    async def get_memory_from_db(
        self,
        db: AsyncSession,
        agent_id: str,
        simulation_id: Optional[str],
        as_of_time: datetime,
        portfolio: Optional[PortfolioTracker] = None,
        symbol: Optional[str] = None,
    ) -> AgentMemory:
        """Construct bounded AgentMemory by querying persisted database records.

        Queries PostgreSQL agent_decisions table for past decisions strictly < as_of_time.
        """
        try:
            as_of = _ensure_utc(as_of_time)

            # 1. Query past decisions from DB
            stmt = select(models.AgentDecision).where(
                models.AgentDecision.agent_id == agent_id,
                models.AgentDecision.candle_timestamp < as_of,
            )
            if simulation_id is not None:
                stmt = stmt.where(models.AgentDecision.simulation_id == simulation_id)
            else:
                stmt = stmt.where(models.AgentDecision.simulation_id.is_(None))

            stmt = stmt.order_by(models.AgentDecision.candle_timestamp.desc()).limit(
                MAX_RECENT_DECISIONS
            )
            res = await db.execute(stmt)
            db_decisions = res.scalars().all()

            bounded_decisions: list[MemoryDecisionRecord] = []
            for d in db_decisions:
                act = (
                    AgentAction(d.action.value)
                    if hasattr(d.action, "value")
                    else AgentAction(str(d.action))
                )
                bounded_decisions.append(
                    MemoryDecisionRecord(
                        candle_timestamp=_ensure_utc(d.candle_timestamp),
                        action=act,
                        confidence=float(d.confidence),
                        quantity=d.quantity,
                        reason=d.reason,
                        observations=list(d.observations) if d.observations else [],
                        status=None,
                        staged_order_id=None,
                    )
                )

            # 2. Closed trades: if portfolio tracker provided, use its closed trades
            bounded_trades: list[MemoryTradeRecord] = []
            if portfolio is not None:
                all_closed = portfolio.closed_trades
                sym_filter = symbol.strip().upper() if symbol else None
                eligible_trades = [
                    tr
                    for tr in all_closed
                    if _ensure_utc(tr.exit_time) <= as_of
                    and (sym_filter is None or tr.symbol.strip().upper() == sym_filter)
                ]
                eligible_trades.sort(key=lambda x: _ensure_utc(x.exit_time), reverse=True)
                bounded_trades = [
                    MemoryTradeRecord(
                        trade_id=tr.trade_id,
                        symbol=tr.symbol,
                        side=tr.side,
                        quantity=tr.quantity,
                        entry_price=tr.entry_price,
                        exit_price=tr.exit_price,
                        gross_pnl=tr.gross_pnl,
                        net_pnl=tr.net_pnl,
                        entry_time=_ensure_utc(tr.entry_time),
                        exit_time=_ensure_utc(tr.exit_time),
                        exit_reason=tr.exit_reason,
                    )
                    for tr in eligible_trades[:MAX_RECENT_TRADES]
                ]

            return AgentMemory(
                recent_decisions=bounded_decisions,
                recent_trades=bounded_trades,
                agent_id=agent_id,
                simulation_id=simulation_id,
                as_of_time=as_of,
            )
        except Exception:
            logger.exception(
                "Database error retrieving agent memory for sim '%s', agent '%s'; defaulting to empty memory",
                simulation_id,
                agent_id,
            )
            return AgentMemory(
                recent_decisions=[],
                recent_trades=[],
                agent_id=agent_id,
                simulation_id=simulation_id,
                as_of_time=as_of_time,
            )

    def clear_history(
        self,
        agent_id: Optional[str] = None,
        simulation_id: Optional[str] = None,
    ) -> None:
        """Clear tracked in-memory decision history."""
        with self._lock:
            if agent_id is None and simulation_id is None:
                self._decision_history.clear()
            elif agent_id is not None and simulation_id is not None:
                self._decision_history.pop((simulation_id, agent_id), None)
            elif simulation_id is not None:
                keys_to_remove = [k for k in self._decision_history if k[0] == simulation_id]
                for k in keys_to_remove:
                    self._decision_history.pop(k, None)
            elif agent_id is not None:
                keys_to_remove = [k for k in self._decision_history if k[1] == agent_id]
                for k in keys_to_remove:
                    self._decision_history.pop(k, None)
