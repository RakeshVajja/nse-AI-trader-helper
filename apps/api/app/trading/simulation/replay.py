"""Chronological Historical Replay Engine (Phase 6A).

Enforces the frozen 6-step per-candle simulation event sequence:
1) Execute pending automatic SL/TP exits at current candle OPEN.
2) Execute pending strategy orders at current candle OPEN.
   - Enforcing Same-Symbol Precedence: an automatic SL/TP exit blocks
     any strategy order for that same symbol at that OPEN.
3) Update PortfolioTracker.
4) Complete current candle and mark active positions to market at CLOSE.
5) Evaluate completed-candle SL/TP triggers and queue exits for t+1 OPEN.
6) Evaluate strategy signals using data through t and queue orders for t+1 OPEN.

Strict Invariants:
- Zero look-ahead: at candle t, only data through completed candle t is visible.
- Virtual clock: simulation time derives strictly from candle timestamps, never datetime.now().
- Idempotency: a candle timestamp may be processed exactly once.
- End-of-series: orders queued at the final candle are cleanly rejected without next candle;
  open positions remain open and marked to market at final candle close.
- Component isolation: each engine instance owns its own state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import (
    ExecutionResult,
    OrderRequest,
    OrderStatus,
    PortfolioState,
    TradeRecord,
)
from app.trading.triggers import TriggerMonitor

logger = logging.getLogger(__name__)


class ReplayError(Exception):
    """Base exception for replay engine errors."""


class DuplicateTimestampError(ReplayError, ValueError):
    """Raised when a candle with an already-processed timestamp is received."""


class OutOfOrderCandleError(ReplayError, ValueError):
    """Raised when candles are not strictly ascending in chronological order."""


class EmptyDatasetError(ReplayError, ValueError):
    """Raised when the historical dataset is empty."""


@dataclass(frozen=True)
class ReplayContext:
    """Context provided to trading strategies at completed candle t.

    Enforces strict no-look-ahead: visible_candles contains only completed
    candles up to and including the current candle.
    """

    current_candle: CandleData
    visible_candles: Tuple[CandleData, ...]
    portfolio_state: PortfolioState
    virtual_time: datetime
    step_index: int
    total_candles: int


@dataclass
class ReplayStepResult:
    """Structured result of processing a single simulation candle step."""

    step_index: int
    timestamp: datetime
    candle: CandleData
    auto_exits_executed: List[ExecutionResult] = field(default_factory=list)
    strategy_orders_executed: List[ExecutionResult] = field(default_factory=list)
    auto_exits_queued: List[OrderRequest] = field(default_factory=list)
    strategy_orders_queued: List[OrderRequest] = field(default_factory=list)
    portfolio_state: Optional[PortfolioState] = None


@dataclass
class ReplaySummary:
    """End-of-simulation summary and performance records."""

    total_steps: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    final_portfolio_state: PortfolioState
    trades: List[TradeRecord]
    executions: List[ExecutionResult]
    rejected_orders: List[ExecutionResult]
    step_results: List[ReplayStepResult]


StrategyCallable = Callable[[ReplayContext], Sequence[OrderRequest]]


async def load_historical_candles_from_db(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
) -> List[CandleData]:
    """Query locked historical candles chronologically from PostgreSQL.

    Rules:
    1. Read-only query ordered strictly by timestamp ASC.
    2. Does not fetch live or external data.
    3. Does not mutate database records.
    4. Enforces UTC timezone on timestamps.

    Args:
        db: Active AsyncSession.
        symbol: Trading symbol (e.g. RELIANCE).
        timeframe: Candle interval (e.g. 15m).
        start_date: Start of historical window.
        end_date: End of historical window.

    Returns:
        List of CandleData strictly ordered by timestamp ascending.
    """
    clean_symbol = symbol.strip().upper()
    req_start = start_date.replace(tzinfo=timezone.utc) if start_date.tzinfo is None else start_date
    req_end = end_date.replace(tzinfo=timezone.utc) if end_date.tzinfo is None else end_date

    if req_start > req_end:
        raise ValueError(
            f"start_date ({req_start.isoformat()}) cannot be after end_date ({req_end.isoformat()})"
        )

    stmt = (
        select(models.Candle)
        .join(models.Instrument, models.Candle.instrument_id == models.Instrument.id)
        .where(
            models.Instrument.symbol == clean_symbol,
            models.Candle.timeframe == timeframe,
            models.Candle.timestamp >= req_start,
            models.Candle.timestamp <= req_end,
        )
        .order_by(models.Candle.timestamp.asc())
    )
    result = await db.execute(stmt)
    db_candles = result.scalars().all()

    if not db_candles:
        raise EmptyDatasetError(
            f"No historical candles found in PostgreSQL for {clean_symbol} ({timeframe}) "
            f"between {req_start.isoformat()} and {req_end.isoformat()}. "
            "Historical replay requires a pre-loaded dataset."
        )

    candles: List[CandleData] = []
    for c in db_candles:
        ts = c.timestamp.replace(tzinfo=timezone.utc) if c.timestamp.tzinfo is None else c.timestamp
        candles.append(
            CandleData(
                timestamp=ts,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=float(c.volume),
            )
        )
    return candles


class ChronologicalReplayEngine:
    """Chronological historical simulation replay engine (Phase 6A).

    Coordinates market data playback, order executions, portfolio accounting,
    stop-loss / take-profit auto-triggers, and strategy decision lifecycles.
    """

    def __init__(
        self,
        candles: Optional[Sequence[CandleData]] = None,
        symbol: Optional[str] = None,
        portfolio: Optional[PortfolioTracker] = None,
        execution_engine: Optional[ExecutionEngine] = None,
        risk_engine: Optional[RiskEngine] = None,
        trigger_monitor: Optional[TriggerMonitor] = None,
        initial_capital: float = 100000.0,
    ) -> None:
        self.symbol: Optional[str] = symbol.strip().upper() if symbol else None
        self.execution_engine = (
            execution_engine if execution_engine is not None else ExecutionEngine()
        )
        self.portfolio = (
            portfolio
            if portfolio is not None
            else PortfolioTracker(initial_capital=initial_capital)
        )
        self.risk_engine = (
            risk_engine
            if risk_engine is not None
            else RiskEngine(execution_config=self.execution_engine.config)
        )
        self.trigger_monitor = (
            trigger_monitor
            if trigger_monitor is not None
            else TriggerMonitor(execution_engine=self.execution_engine)
        )

        self._all_candles: List[CandleData] = []
        self._completed_candles: List[CandleData] = []
        self._processed_timestamps: Set[datetime] = set()
        self._current_index: int = 0
        self._current_time: Optional[datetime] = None
        self._is_finalized: bool = False

        self.pending_strategy_orders: List[OrderRequest] = []
        self.execution_history: List[ExecutionResult] = []
        self.rejected_orders: List[ExecutionResult] = []
        self.step_results: List[ReplayStepResult] = []

        if candles is not None:
            self.set_candles(candles)

    @classmethod
    async def from_db(
        cls,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        portfolio: Optional[PortfolioTracker] = None,
        execution_engine: Optional[ExecutionEngine] = None,
        risk_engine: Optional[RiskEngine] = None,
        trigger_monitor: Optional[TriggerMonitor] = None,
        initial_capital: float = 100000.0,
    ) -> ChronologicalReplayEngine:
        """Create and initialize a ChronologicalReplayEngine from PostgreSQL historical data."""
        candles = await load_historical_candles_from_db(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )
        return cls(
            candles=candles,
            symbol=symbol,
            portfolio=portfolio,
            execution_engine=execution_engine,
            risk_engine=risk_engine,
            trigger_monitor=trigger_monitor,
            initial_capital=initial_capital,
        )

    def set_candles(self, candles: Sequence[CandleData]) -> None:
        """Set and validate the historical candle dataset for replay.

        Enforces strict timestamp ASC ordering and uniqueness.
        """
        if not candles:
            self._all_candles = []
            self.reset()
            return

        validated: List[CandleData] = []
        prev_ts: Optional[datetime] = None
        for i, c in enumerate(candles):
            ts = (
                c.timestamp.replace(tzinfo=timezone.utc)
                if c.timestamp.tzinfo is None
                else c.timestamp
            )
            if prev_ts is not None:
                if ts < prev_ts:
                    raise OutOfOrderCandleError(
                        f"Candles out of order at index {i}: timestamp {ts.isoformat()} "
                        f"is earlier than preceding timestamp {prev_ts.isoformat()}."
                    )
                if ts == prev_ts:
                    raise DuplicateTimestampError(
                        f"Duplicate candle timestamp at index {i}: {ts.isoformat()}."
                    )

            norm_candle = CandleData(
                timestamp=ts,
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=float(c.volume),
            )
            validated.append(norm_candle)
            prev_ts = ts

        self._all_candles = validated
        self.reset()

    @property
    def current_time(self) -> Optional[datetime]:
        """Current virtual simulation timestamp (derived strictly from candle stream)."""
        return self._current_time

    @property
    def current_step(self) -> int:
        """Number of completed simulation candle steps."""
        return self._current_index

    @property
    def total_candles(self) -> int:
        """Total number of candles loaded in the historical replay series."""
        return len(self._all_candles)

    @property
    def is_completed(self) -> bool:
        """True if all candles in the series have been processed and finalized."""
        return self._is_finalized

    def has_next(self) -> bool:
        """Return True if there are remaining candles to process."""
        return self._current_index < len(self._all_candles)

    def get_visible_candles(self) -> Tuple[CandleData, ...]:
        """Return completed candles strictly up to the current candle (no look-ahead)."""
        return tuple(self._completed_candles)

    def queue_strategy_order(self, order: OrderRequest) -> ExecutionResult:
        """Queue a strategy order for execution at the next candle OPEN.

        Performs:
        1. Virtual time check: decision_time must match current completed candle timestamp.
        2. Same-symbol auto-exit precedence check.
        3. RiskEngine pre-trade validation.
        """
        if self._current_time is None:
            raise ReplayError("Cannot queue strategy order before the first candle has completed.")

        order_sym = order.symbol.strip().upper()

        # Decision time must match current candle timestamp
        if order.decision_time != self._current_time:
            rejected = ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=order_sym,
                side=order.side,
                quantity=order.quantity,
                decision_time=order.decision_time,
                rejection_reason=(
                    f"Decision time ({order.decision_time.isoformat()}) must match current "
                    f"completed candle timestamp ({self._current_time.isoformat()})."
                ),
            )
            self.rejected_orders.append(rejected)
            self.execution_history.append(rejected)
            return rejected

        # Same-symbol precedence rule: if an auto-exit is already pending for this symbol, reject
        if self.trigger_monitor.is_exit_pending(order_sym):
            rejected = ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=order_sym,
                side=order.side,
                quantity=order.quantity,
                decision_time=order.decision_time,
                rejection_reason=(
                    f"Rejected due to same-symbol precedence: an automatic SL/TP exit is already "
                    f"pending for {order_sym} at next candle open."
                ),
            )
            self.rejected_orders.append(rejected)
            self.execution_history.append(rejected)
            return rejected

        # Validate with RiskEngine
        risk_check = self.risk_engine.validate_order(
            order=order,
            portfolio=self.portfolio,
            current_price=order.decision_price or self._completed_candles[-1].close,
        )
        if not risk_check.approved:
            rejected = ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=order_sym,
                side=order.side,
                quantity=order.quantity,
                decision_time=order.decision_time,
                rejection_reason=f"Risk check failed: {risk_check.rejection_reason}",
            )
            self.rejected_orders.append(rejected)
            self.execution_history.append(rejected)
            return rejected

        # Approved: queue for next candle OPEN
        self.pending_strategy_orders.append(order)
        return ExecutionResult(
            order_id=order.order_id,
            status=OrderStatus.PENDING,
            symbol=order_sym,
            side=order.side,
            quantity=order.quantity,
            decision_time=order.decision_time,
        )

    def _resolve_symbol(self, candle: CandleData) -> Optional[str]:
        """Resolve the effective symbol for the current candle."""
        if self.symbol:
            return self.symbol
        candle_sym = getattr(candle, "symbol", None)
        if candle_sym:
            return str(candle_sym).strip().upper()
        if len(self.portfolio.positions) == 1:
            return next(iter(self.portfolio.positions.keys()))
        return None

    def _process_single_candle(
        self,
        candle: CandleData,
        step_index: int,
        strategy: Optional[StrategyCallable] = None,
    ) -> ReplayStepResult:
        """Execute the authoritative 6-step event sequence for a single candle."""
        ts = (
            candle.timestamp.replace(tzinfo=timezone.utc)
            if candle.timestamp.tzinfo is None
            else candle.timestamp
        )

        # Idempotency check: timestamp must never be processed twice
        if ts in self._processed_timestamps:
            raise DuplicateTimestampError(
                f"Candle timestamp {ts.isoformat()} has already been processed."
            )

        # Chronological check: timestamp must be strictly after current virtual time
        if self._current_time is not None and ts <= self._current_time:
            raise OutOfOrderCandleError(
                f"Candle timestamp {ts.isoformat()} is not strictly after previous "
                f"timestamp {self._current_time.isoformat()}."
            )

        target_sym = self._resolve_symbol(candle)

        # ------------------------------------------------------------------
        # Step 1: Execute pending automatic SL/TP exits at current candle OPEN
        # ------------------------------------------------------------------
        # Identify symbols that have an automatic exit pending for this current OPEN
        exiting_symbols: Set[str] = set(self.trigger_monitor.get_pending_symbols())

        auto_exit_results: List[ExecutionResult] = self.trigger_monitor.execute_pending_exits(
            current_candle=candle,
            portfolio=self.portfolio,
            symbol=target_sym,
        )
        self.execution_history.extend(auto_exit_results)

        # ------------------------------------------------------------------
        # Step 2: Execute pending strategy orders at current candle OPEN
        # ------------------------------------------------------------------
        strategy_exec_results: List[ExecutionResult] = []
        orders_to_execute = list(self.pending_strategy_orders)
        self.pending_strategy_orders.clear()

        for order in orders_to_execute:
            order_sym = order.symbol.strip().upper()

            # Same-Symbol Precedence Rule:
            # If an automatic exit was pending/executed for this symbol at this OPEN,
            # reject the strategy order without side effects.
            if order_sym in exiting_symbols or self.trigger_monitor.is_exit_pending(order_sym):
                rejected_res = ExecutionResult(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    symbol=order_sym,
                    side=order.side,
                    quantity=order.quantity,
                    decision_time=order.decision_time,
                    rejection_reason=(
                        f"Rejected due to same-symbol precedence: an automatic SL/TP exit was "
                        f"executed or pending for {order_sym} at current candle open ({ts.isoformat()})."
                    ),
                )
                strategy_exec_results.append(rejected_res)
                self.rejected_orders.append(rejected_res)
            else:
                res = self.execution_engine.execute_order(
                    order=order,
                    next_candle=candle,
                    portfolio=self.portfolio,
                )
                strategy_exec_results.append(res)
                if res.status == OrderStatus.REJECTED:
                    self.rejected_orders.append(res)

        self.execution_history.extend(strategy_exec_results)

        # ------------------------------------------------------------------
        # Step 3: Update PortfolioTracker
        # ------------------------------------------------------------------
        # All fills at Step 1 and Step 2 already updated PortfolioTracker cash and positions.
        self.portfolio.last_updated = ts

        # ------------------------------------------------------------------
        # Step 4: Complete current candle and mark active positions to market at CLOSE
        # ------------------------------------------------------------------
        self._completed_candles.append(candle)
        self._processed_timestamps.add(ts)
        self._current_time = ts

        # Mark active positions to market using completed candle Close
        if target_sym and target_sym in self.portfolio.positions:
            self.portfolio.update_market_price(
                symbol=target_sym,
                current_price=float(candle.close),
                timestamp=ts,
            )
        elif len(self.portfolio.positions) > 0:
            for sym in list(self.portfolio.positions.keys()):
                if target_sym is None or sym == target_sym:
                    self.portfolio.update_market_price(
                        symbol=sym,
                        current_price=float(candle.close),
                        timestamp=ts,
                    )

        # ------------------------------------------------------------------
        # Step 5: Evaluate completed-candle SL/TP triggers
        # ------------------------------------------------------------------
        auto_exits_queued = self.trigger_monitor.evaluate_completed_candle(
            completed_candle=candle,
            portfolio=self.portfolio,
            symbol=target_sym,
        )

        # ------------------------------------------------------------------
        # Step 6: Evaluate strategy signals and queue orders for next candle OPEN
        # ------------------------------------------------------------------
        strategy_orders_queued: List[OrderRequest] = []
        if strategy is not None:
            context = ReplayContext(
                current_candle=candle,
                visible_candles=self.get_visible_candles(),
                portfolio_state=self.portfolio.get_state(),
                virtual_time=ts,
                step_index=step_index,
                total_candles=len(self._all_candles),
            )
            emitted_orders = strategy(context)
            for emitted in emitted_orders:
                emit_sym = emitted.symbol.strip().upper()

                # Same-Symbol Precedence: if an auto-exit was just queued at Step 5, reject immediately
                if self.trigger_monitor.is_exit_pending(emit_sym):
                    rejected_res = ExecutionResult(
                        order_id=emitted.order_id,
                        status=OrderStatus.REJECTED,
                        symbol=emit_sym,
                        side=emitted.side,
                        quantity=emitted.quantity,
                        decision_time=ts,
                        rejection_reason=(
                            f"Rejected due to same-symbol precedence: automatic SL/TP exit already "
                            f"queued for {emit_sym} for next candle open."
                        ),
                    )
                    self.rejected_orders.append(rejected_res)
                    self.execution_history.append(rejected_res)
                else:
                    risk_check = self.risk_engine.validate_order(
                        order=emitted,
                        portfolio=self.portfolio,
                        current_price=emitted.decision_price or float(candle.close),
                    )
                    if risk_check.approved:
                        self.pending_strategy_orders.append(emitted)
                        strategy_orders_queued.append(emitted)
                    else:
                        rejected_res = ExecutionResult(
                            order_id=emitted.order_id,
                            status=OrderStatus.REJECTED,
                            symbol=emit_sym,
                            side=emitted.side,
                            quantity=emitted.quantity,
                            decision_time=ts,
                            rejection_reason=f"Risk check failed: {risk_check.rejection_reason}",
                        )
                        self.rejected_orders.append(rejected_res)
                        self.execution_history.append(rejected_res)

        step_res = ReplayStepResult(
            step_index=step_index,
            timestamp=ts,
            candle=candle,
            auto_exits_executed=auto_exit_results,
            strategy_orders_executed=strategy_exec_results,
            auto_exits_queued=auto_exits_queued,
            strategy_orders_queued=strategy_orders_queued,
            portfolio_state=self.portfolio.get_state(),
        )
        self.step_results.append(step_res)
        return step_res

    def step(self, strategy: Optional[StrategyCallable] = None) -> Optional[ReplayStepResult]:
        """Advance the replay clock by exactly one candle and process the 6-step cycle."""
        if not self.has_next():
            if not self._is_finalized:
                self.finalize()
            return None

        candle = self._all_candles[self._current_index]
        current_step_idx = self._current_index
        self._current_index += 1

        return self._process_single_candle(
            candle=candle,
            step_index=current_step_idx,
            strategy=strategy,
        )

    def process_candle(
        self,
        candle: CandleData,
        strategy: Optional[StrategyCallable] = None,
    ) -> ReplayStepResult:
        """Process an individually supplied candle through the 6-step replay cycle."""
        step_idx = len(self._completed_candles)
        return self._process_single_candle(
            candle=candle,
            step_index=step_idx,
            strategy=strategy,
        )

    def finalize(self) -> ReplaySummary:
        """Finalize the replay at the end of the historical series.

        Enforces End-of-Series Invariants:
        1. Reject any pending strategy orders and auto-exits cleanly (no next candle exists).
        2. Open positions remain open and are marked to market at final candle close.
        3. No positions are artificially liquidated.
        """
        if self._is_finalized:
            return self.get_summary()

        # Reject remaining pending strategy orders (next candle is None)
        orders_to_reject = list(self.pending_strategy_orders)
        self.pending_strategy_orders.clear()
        for order in orders_to_reject:
            res = self.execution_engine.execute_order(
                order=order,
                next_candle=None,
                portfolio=self.portfolio,
            )
            self.rejected_orders.append(res)
            self.execution_history.append(res)

        # Reject remaining pending auto-exits (next candle is None)
        auto_exits_rejected = self.trigger_monitor.execute_pending_exits(
            current_candle=None,
            portfolio=self.portfolio,
            symbol=self.symbol,
        )
        self.rejected_orders.extend(auto_exits_rejected)
        self.execution_history.extend(auto_exits_rejected)

        self._is_finalized = True
        return self.get_summary()

    def get_summary(self) -> ReplaySummary:
        """Return the current or final simulation replay summary."""
        start_ts = self._completed_candles[0].timestamp if self._completed_candles else None
        end_ts = self._completed_candles[-1].timestamp if self._completed_candles else None
        return ReplaySummary(
            total_steps=len(self._completed_candles),
            start_time=start_ts,
            end_time=end_ts,
            final_portfolio_state=self.portfolio.get_state(),
            trades=list(self.portfolio.closed_trades),
            executions=list(self.execution_history),
            rejected_orders=list(self.rejected_orders),
            step_results=list(self.step_results),
        )

    def run(self, strategy: Optional[StrategyCallable] = None) -> ReplaySummary:
        """Run the replay continuously from current index to the end of the series."""
        while self.has_next():
            self.step(strategy=strategy)
        return self.finalize()

    def reset(self) -> None:
        """Reset the replay engine and components back to initial state."""
        self.portfolio.reset()
        self.trigger_monitor.reset()
        self._completed_candles.clear()
        self._processed_timestamps.clear()
        self._current_index = 0
        self._current_time = None
        self._is_finalized = False
        self.pending_strategy_orders.clear()
        self.execution_history.clear()
        self.rejected_orders.clear()
        self.step_results.clear()
