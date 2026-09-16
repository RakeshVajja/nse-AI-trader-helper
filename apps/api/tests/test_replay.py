"""Unit and integration tests for Chronological Replay Engine (Phase 6A).

Verifies all frozen Phase 6A requirements:
1. Strict timestamp ordering & dataset validation.
2. Strict no-look-ahead: visible_candles strictly <= current candle; zero future data.
3. Next-candle execution at Open: decision at t fills at t+1 Open with slippage and fees; never at t Close.
4. Exact 6-step per-candle event ordering.
5. Same-symbol precedence: automatic SL/TP exit blocks strategy orders for that same symbol at Open.
6. Cross-symbol isolation: exit on symbol A does not block order on symbol B.
7. Idempotency & duplicate timestamp guard.
8. Virtual clock authority (candle timestamps, no datetime.now()).
9. End-of-series handling: final candle queued orders cleanly rejected; open positions marked to market.
10. Deterministic reproducibility: identical runs produce bit-for-bit identical results.
11. Full multi-candle lifecycle with auto-triggers and accounting reconciliation.
12. Database loading from PostgreSQL/SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.schemas import (
    ExecutionConfig,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    DuplicateTimestampError,
    EmptyDatasetError,
    OutOfOrderCandleError,
    ReplayContext,
    load_historical_candles_from_db,
)
from app.trading.triggers import EXIT_REASON_TAKE_PROFIT


def _make_candle(
    timestamp: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float = 1000.0,
    symbol: str = "RELIANCE",
) -> CandleData:
    """Helper to construct a typed CandleData with symbol metadata."""
    candle = CandleData(
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
    # Attach symbol dynamically for multi-symbol simulation tests
    object.__setattr__(candle, "symbol", symbol)
    return candle


def _build_test_candles(
    count: int = 5, start_hour: int = 9, symbol: str = "RELIANCE"
) -> List[CandleData]:
    """Helper to generate a sequence of valid 15-minute candles."""
    candles: List[CandleData] = []
    base_price = 2000.0
    for i in range(count):
        minute = (i * 15) % 60
        hour = start_hour + (i * 15) // 60
        ts = datetime(2026, 1, 15, hour, minute, tzinfo=timezone.utc)
        c = _make_candle(
            timestamp=ts,
            open_price=base_price + (i * 10.0),
            high_price=base_price + (i * 10.0) + 15.0,
            low_price=base_price + (i * 10.0) - 5.0,
            close_price=base_price + (i * 10.0) + 8.0,
            volume=1500.0,
            symbol=symbol,
        )
        candles.append(c)
    return candles


# ==============================================================================
# 1. Dataset Validation & Strict Timestamp Ordering
# ==============================================================================


def test_replay_initialization_and_empty_dataset():
    """Verify clean initialization and empty dataset handling."""
    engine = ChronologicalReplayEngine(candles=[], symbol="RELIANCE", initial_capital=100000.0)
    assert engine.total_candles == 0
    assert engine.current_step == 0
    assert engine.current_time is None
    assert not engine.has_next()

    summary = engine.run()
    assert summary.total_steps == 0
    assert summary.start_time is None
    assert summary.end_time is None
    assert summary.final_portfolio_state.cash == 100000.0
    assert summary.final_portfolio_state.total_portfolio_value == 100000.0


def test_replay_rejects_out_of_order_candles():
    """Verify that candles with non-ascending timestamps are rejected."""
    t1 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t_out_of_order = datetime(2026, 1, 15, 9, 20, tzinfo=timezone.utc)

    candles = [
        _make_candle(t1, 100, 110, 95, 105),
        _make_candle(t2, 105, 115, 100, 110),
        _make_candle(t_out_of_order, 110, 120, 105, 115),  # 09:20 is earlier than 09:30
    ]

    with pytest.raises(OutOfOrderCandleError, match="is earlier than preceding timestamp"):
        ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")


def test_replay_rejects_duplicate_timestamps():
    """Verify that candles with identical timestamps are rejected."""
    t1 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    candles = [
        _make_candle(t1, 100, 110, 95, 105),
        _make_candle(t1, 105, 115, 100, 110),  # Duplicate t1
    ]

    with pytest.raises(DuplicateTimestampError, match="Duplicate candle timestamp"):
        ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")


# ==============================================================================
# 2. Virtual Clock & No Wall-Clock Dependence
# ==============================================================================


def test_replay_virtual_clock_advancement():
    """Verify simulation time advances strictly from candle timestamps."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")

    assert engine.current_time is None

    # Step 0 (09:15)
    res0 = engine.step()
    assert res0 is not None
    assert engine.current_time == candles[0].timestamp
    assert engine.portfolio.last_updated == candles[0].timestamp
    assert engine.current_step == 1

    # Step 1 (09:30)
    res1 = engine.step()
    assert res1 is not None
    assert engine.current_time == candles[1].timestamp
    assert engine.portfolio.last_updated == candles[1].timestamp
    assert engine.current_step == 2

    # Step 2 (09:45)
    res2 = engine.step()
    assert res2 is not None
    assert engine.current_time == candles[2].timestamp
    assert engine.portfolio.last_updated == candles[2].timestamp
    assert engine.current_step == 3


# ==============================================================================
# 3. Strict No-Look-Ahead Enforcement
# ==============================================================================


def test_replay_strict_no_look_ahead_visible_candles():
    """Verify strategy callback never sees future candles."""
    candles = _build_test_candles(count=4)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")

    inspected_lengths: List[int] = []
    inspected_future_timestamps: List[datetime] = []

    def mock_strategy(context: ReplayContext) -> List[OrderRequest]:
        # Context visible_candles must contain strictly <= step completed candles
        inspected_lengths.append(len(context.visible_candles))
        # Ensure no future timestamps exist in visible_candles
        for c in context.visible_candles:
            if c.timestamp > context.virtual_time:
                inspected_future_timestamps.append(c.timestamp)
        return []

    engine.run(strategy=mock_strategy)

    # Step 0 saw 1 candle, Step 1 saw 2 candles, Step 2 saw 3 candles, Step 3 saw 4 candles
    assert inspected_lengths == [1, 2, 3, 4]
    # Zero future candles were ever visible
    assert inspected_future_timestamps == []


# ==============================================================================
# 4. Next-Candle Execution & Order Timing
# ==============================================================================


def test_replay_next_candle_execution_timing_and_slippage():
    """Verify order decided at candle t executes strictly at candle t+1 OPEN."""
    candles = _build_test_candles(count=3)
    # Candle 0: Open 2000, Close 2008
    # Candle 1: Open 2010, Close 2018
    # Candle 2: Open 2020, Close 2028

    exec_config = ExecutionConfig(
        slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0
    )
    engine = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        execution_engine=ExecutionEngine(config=exec_config),
        initial_capital=100000.0,
    )

    orders_emitted_step: List[int] = []

    def strategy(context: ReplayContext) -> List[OrderRequest]:
        if context.step_index == 0:
            orders_emitted_step.append(0)
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=10,
                    decision_time=context.virtual_time,
                    decision_price=context.current_candle.close,
                )
            ]
        return []

    # Step 0 (09:15): Strategy decides BUY. Position MUST NOT open yet!
    res0 = engine.step(strategy=strategy)
    assert res0 is not None
    assert len(res0.strategy_orders_queued) == 1
    assert len(res0.strategy_orders_executed) == 0
    assert engine.portfolio.get_position("RELIANCE") is None
    assert engine.portfolio.cash == 100000.0

    # Step 1 (09:30): Order executes at Candle 1 OPEN (2010.0)
    res1 = engine.step(strategy=strategy)
    assert res1 is not None
    assert len(res1.strategy_orders_executed) == 1
    fill = res1.strategy_orders_executed[0]
    assert fill.status == OrderStatus.FILLED
    # Fill price: 2010.0 * (1 + 0.0005) = 2011.005 -> 2011.005
    assert fill.market_price == 2010.0
    assert fill.execution_price == 2011.005
    assert fill.executed_at == candles[1].timestamp

    # Position now active in portfolio
    pos = engine.portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10
    assert pos.average_entry_price == 2011.005


# ==============================================================================
# 5. Exact 6-Step Per-Candle Event Ordering
# ==============================================================================


def test_replay_exact_six_step_event_sequence():
    """Verify the 6 per-candle steps execute in exact sequence:

    1) Execute auto-exits at Open
    2) Execute strategy orders at Open
    3) Update portfolio
    4) Mark to market at Close
    5) Evaluate completed-candle SL/TP triggers
    6) Evaluate strategy signals & queue for next Open
    """
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # C0: Open 2000, High 2010, Low 1990, Close 2005
    # C1: Open 2005, High 2150 (triggers TP 2100!), Low 2000, Close 2140
    # C2: Open 2140, High 2160, Low 2130, Close 2150
    c0 = _make_candle(t0, 2000.0, 2010.0, 1990.0, 2005.0)
    c1 = _make_candle(t1, 2005.0, 2150.0, 2000.0, 2140.0)
    c2 = _make_candle(t2, 2140.0, 2160.0, 2130.0, 2150.0)

    engine = ChronologicalReplayEngine(candles=[c0, c1, c2], symbol="RELIANCE")

    # Step 0: Emit BUY with Take-Profit at 2100.0
    def strat(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 0:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=5,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                    stop_loss=1900.0,
                    take_profit=2100.0,
                )
            ]
        return []

    # Candle 0: BUY queued for t1 Open
    r0 = engine.step(strategy=strat)
    assert r0 is not None
    assert len(r0.strategy_orders_queued) == 1

    # Candle 1:
    # 1) No auto-exits at Open
    # 2) Strategy BUY fills at t1 Open (2005.0)
    # 3) Portfolio updated with position
    # 4) Candle 1 completes, marked to market at 2140.0
    # 5) Candle 1 High (2150.0 >= 2100.0) triggers TP! Auto-exit queued for t2 Open.
    # 6) Strategy runs (emits nothing)
    r1 = engine.step(strategy=strat)
    assert r1 is not None
    assert len(r1.strategy_orders_executed) == 1
    assert r1.strategy_orders_executed[0].status == OrderStatus.FILLED
    assert len(r1.auto_exits_queued) == 1
    assert r1.auto_exits_queued[0].reason == EXIT_REASON_TAKE_PROFIT
    assert engine.trigger_monitor.is_exit_pending("RELIANCE")

    # Candle 2:
    # 1) Auto-exit executes at t2 Open (2140.0)
    # 2) No strategy orders
    # 3) Portfolio updated: position is now closed!
    # 4) Candle 2 completes
    # 5) No triggers (position already closed)
    r2 = engine.step(strategy=strat)
    assert r2 is not None
    assert len(r2.auto_exits_executed) == 1
    assert r2.auto_exits_executed[0].status == OrderStatus.FILLED
    assert len(r2.auto_exits_queued) == 0
    assert engine.portfolio.get_position("RELIANCE") is None
    assert len(engine.portfolio.closed_trades) == 1
    assert engine.portfolio.closed_trades[0].exit_reason == EXIT_REASON_TAKE_PROFIT


# ==============================================================================
# 6. Same-Symbol Precedence Rule
# ==============================================================================


def test_replay_same_symbol_auto_exit_precedence_blocks_strategy_order():
    """Verify automatic SL/TP exit takes strict precedence over strategy order on same symbol at Open."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # C0: BUY filled manually or pre-opened
    # C1: Low crosses SL 1900 -> Auto-exit queued for t2 Open
    # C2: At t2 Open, both Auto-Exit AND a strategy BUY for RELIANCE are scheduled
    c0 = _make_candle(t0, 2000.0, 2020.0, 1990.0, 2010.0)
    c1 = _make_candle(t1, 2010.0, 2015.0, 1890.0, 1905.0)  # Low 1890 <= SL 1900
    c2 = _make_candle(t2, 1910.0, 1930.0, 1900.0, 1920.0)

    engine = ChronologicalReplayEngine(candles=[c0, c1, c2], symbol="RELIANCE")

    # Step 0: Open position with SL=1900
    def strat_open(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 0:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=10,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                    stop_loss=1900.0,
                )
            ]
        return []

    engine.step(strategy=strat_open)  # Queues BUY for t1
    engine.step()  # Fills BUY at t1, triggers SL at t1 Close -> auto-exit queued for t2 Open

    assert engine.trigger_monitor.is_exit_pending("RELIANCE")

    # Now simulate a rogue strategy order queued for t2 Open
    # Inject a pending strategy BUY order for RELIANCE scheduled for t2 Open
    rogue_order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t1,
        decision_price=1905.0,
    )
    engine.pending_strategy_orders.append(rogue_order)

    # Advance to Candle 2 (t2 Open):
    # Step 1: Auto-exit liquidates the 10 shares
    # Step 2: Rogue strategy BUY order is encountered for same symbol
    # -> Must be REJECTED by same-symbol precedence!
    r2 = engine.step()
    assert r2 is not None
    assert len(r2.auto_exits_executed) == 1
    assert r2.auto_exits_executed[0].status == OrderStatus.FILLED

    assert len(r2.strategy_orders_executed) == 1
    strat_res = r2.strategy_orders_executed[0]
    assert strat_res.status == OrderStatus.REJECTED
    assert "same-symbol precedence" in strat_res.rejection_reason

    # Verify position is completely closed and was NOT reopened
    assert engine.portfolio.get_position("RELIANCE") is None
    assert engine.portfolio.closed_trades[0].quantity == 10


def test_replay_same_symbol_precedence_cross_symbol_isolation():
    """Verify auto-exit on symbol A does NOT block strategy order on symbol B."""
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    c1 = _make_candle(t1, 2010.0, 2015.0, 1890.0, 1905.0, symbol="RELIANCE")  # SL triggered
    c2 = _make_candle(t2, 1910.0, 1930.0, 1900.0, 1920.0, symbol="RELIANCE")

    engine = ChronologicalReplayEngine(candles=[c1, c2], symbol="RELIANCE")

    # Manually open a position for RELIANCE with SL=1900
    engine.portfolio.open_or_increase_position(
        "RELIANCE", quantity=10, price=2000.0, stop_loss=1900.0
    )

    # Process candle 1: SL is triggered for RELIANCE, queued for t2
    engine.step()
    assert engine.trigger_monitor.is_exit_pending("RELIANCE")

    # Queue a strategy BUY order for a DIFFERENT symbol: TCS
    tcs_order = OrderRequest(
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t1,
        decision_price=3000.0,
    )
    engine.pending_strategy_orders.append(tcs_order)

    # Process candle 2: RELIANCE auto-exit executes, TCS BUY also executes!
    r2 = engine.step()
    assert r2 is not None
    assert len(r2.auto_exits_executed) == 1
    assert r2.auto_exits_executed[0].symbol == "RELIANCE"
    assert r2.auto_exits_executed[0].status == OrderStatus.FILLED

    assert len(r2.strategy_orders_executed) == 1
    assert r2.strategy_orders_executed[0].symbol == "TCS"
    assert r2.strategy_orders_executed[0].status == OrderStatus.FILLED

    # RELIANCE is closed, TCS is open
    assert engine.portfolio.get_position("RELIANCE") is None
    assert engine.portfolio.get_position("TCS") is not None
    assert engine.portfolio.get_position("TCS").quantity == 5


def test_replay_same_symbol_precedence_at_step_six_queueing():
    """Verify strategy order emitted at Step 6 is rejected immediately if auto-exit was queued at Step 5."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # Candle 0: Open position with SL=1950
    # Candle 1: Low 1940 <= SL 1950 -> triggers SL at Step 5.
    # Strategy tries to emit BUY for RELIANCE at Step 6.
    c0 = _make_candle(t0, 2000.0, 2010.0, 1990.0, 2000.0)
    c1 = _make_candle(t1, 2000.0, 2005.0, 1940.0, 1945.0)

    engine = ChronologicalReplayEngine(candles=[c0, c1], symbol="RELIANCE")
    engine.portfolio.open_or_increase_position(
        "RELIANCE", quantity=10, price=2000.0, stop_loss=1950.0
    )

    def conflict_strat(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 1:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=5,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                )
            ]
        return []

    assert engine.step() is not None  # Step 0
    r1 = engine.step(strategy=conflict_strat)  # Step 1
    assert r1 is not None

    # Step 5 queued auto-exit
    assert len(r1.auto_exits_queued) == 1
    assert r1.auto_exits_queued[0].symbol == "RELIANCE"

    # Step 6 strategy order was rejected immediately due to pending auto-exit
    assert len(r1.strategy_orders_queued) == 0
    assert len(engine.rejected_orders) >= 1
    last_rej = engine.rejected_orders[-1]
    assert last_rej.symbol == "RELIANCE"
    assert "same-symbol precedence" in last_rej.rejection_reason


# ==============================================================================
# 7. Idempotency & Repeated Timestamp Guard
# ==============================================================================


def test_replay_idempotency_rejects_duplicate_processing():
    """Verify processing an identical candle timestamp twice raises DuplicateTimestampError."""
    candles = _build_test_candles(count=2)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")

    engine.step()  # Processes candle 0
    cash_after_step0 = engine.portfolio.cash

    # Attempt to re-process candle 0
    with pytest.raises(DuplicateTimestampError, match="has already been processed"):
        engine.process_candle(candles[0])

    # State remains unmutated
    assert engine.portfolio.cash == cash_after_step0
    assert engine.current_step == 1


# ==============================================================================
# 8. End of Series & Final Candle Behavior
# ==============================================================================


def test_replay_end_of_series_final_candle_behavior():
    """Verify final candle orders are rejected cleanly and open positions are marked to market without liquidation."""
    candles = _build_test_candles(count=2)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")

    # Strategy emits BUY on candle 1 (the final candle!)
    def final_candle_strat(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 1:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=2,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                    stop_loss=1900.0,
                )
            ]
        return []

    # Also open a position on candle 0 so an open position exists at the end
    engine.portfolio.open_or_increase_position(
        "RELIANCE", quantity=5, price=2000.0, stop_loss=1800.0, timestamp=candles[0].timestamp
    )

    summary = engine.run(strategy=final_candle_strat)

    # 1. Final candle queued order was rejected because no candle t+2 exists
    assert len(summary.rejected_orders) == 1
    rej = summary.rejected_orders[0]
    assert rej.status == OrderStatus.REJECTED
    assert "Next candle unavailable" in rej.rejection_reason

    # 2. Position remains open (not liquidated!)
    pos = engine.portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 5
    assert pos.is_open

    # 3. Position was marked to market at final candle close (Candle 1 close)
    assert pos.current_price == candles[1].close
    assert summary.final_portfolio_state.open_positions_count == 1
    assert summary.final_portfolio_state.closed_trades_count == 0


# ==============================================================================
# 9. Deterministic Reproducibility
# ==============================================================================


def test_replay_deterministic_reproducibility():
    """Verify identical dataset and strategy produce bit-for-bit identical results across separate runs."""
    candles = _build_test_candles(count=5)

    def simple_strategy(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 0:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=8,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                    stop_loss=1950.0,
                    take_profit=2050.0,
                )
            ]
        return []

    engine1 = ChronologicalReplayEngine(
        candles=candles, symbol="RELIANCE", initial_capital=100000.0
    )
    summary1 = engine1.run(strategy=simple_strategy)

    engine2 = ChronologicalReplayEngine(
        candles=candles, symbol="RELIANCE", initial_capital=100000.0
    )
    summary2 = engine2.run(strategy=simple_strategy)

    assert summary1.total_steps == summary2.total_steps
    assert summary1.final_portfolio_state.cash == summary2.final_portfolio_state.cash
    assert (
        summary1.final_portfolio_state.total_portfolio_value
        == summary2.final_portfolio_state.total_portfolio_value
    )
    assert summary1.final_portfolio_state.net_pnl == summary2.final_portfolio_state.net_pnl
    assert len(summary1.executions) == len(summary2.executions)

    for e1, e2 in zip(summary1.executions, summary2.executions):
        assert e1.status == e2.status
        assert e1.execution_price == e2.execution_price
        assert e1.transaction_cost == e2.transaction_cost
        assert e1.executed_at == e2.executed_at


# ==============================================================================
# 10. Manual Strategy Order Queueing
# ==============================================================================


def test_replay_manual_strategy_order_queueing():
    """Verify caller can manually queue a strategy order between candle steps."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")

    # Cannot queue before first candle
    early_order = OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, quantity=5, decision_time=candles[0].timestamp
    )
    with pytest.raises(Exception, match="Cannot queue strategy order before the first candle"):
        engine.queue_strategy_order(early_order)

    # Step 0 completes
    engine.step()

    # Queue valid order at completed candle 0 timestamp
    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=candles[0].timestamp,
        decision_price=candles[0].close,
        stop_loss=1900.0,
    )
    res = engine.queue_strategy_order(order)
    assert res.status == OrderStatus.PENDING

    # Step 1 executes the queued order
    r1 = engine.step()
    assert r1 is not None
    assert len(r1.strategy_orders_executed) == 1
    assert r1.strategy_orders_executed[0].status == OrderStatus.FILLED
    assert engine.portfolio.get_position("RELIANCE").quantity == 5


# ==============================================================================
# 11. Database Historical Candle Loader Integration
# ==============================================================================


@pytest.mark.asyncio
async def test_replay_load_historical_candles_from_db(db_session: AsyncSession):
    """Verify loading historical candles chronologically from PostgreSQL/SQLite."""
    # Seed Instrument
    inst = models.Instrument(symbol="RELIANCE", name="Reliance Industries Ltd")
    db_session.add(inst)
    await db_session.flush()

    # Seed 3 Candles out of order in insertion to verify SQL ORDER BY timestamp ASC
    t1 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    db_session.add_all(
        [
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=t2,
                open=2010.0,
                high=2020.0,
                low=2000.0,
                close=2015.0,
            ),
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=t1,
                open=2000.0,
                high=2010.0,
                low=1990.0,
                close=2005.0,
            ),
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=t3,
                open=2020.0,
                high=2030.0,
                low=2010.0,
                close=2025.0,
            ),
        ]
    )
    await db_session.commit()

    candles = await load_historical_candles_from_db(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=t1,
        end_date=t3,
    )

    assert len(candles) == 3
    # Strictly ascending by timestamp
    assert candles[0].timestamp == t1
    assert candles[1].timestamp == t2
    assert candles[2].timestamp == t3
    assert candles[0].open == 2000.0
    assert candles[1].open == 2010.0
    assert candles[2].open == 2020.0


@pytest.mark.asyncio
async def test_replay_load_db_empty_dataset_raises(db_session: AsyncSession):
    """Verify empty dataset in database raises EmptyDatasetError."""
    t1 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)

    with pytest.raises(EmptyDatasetError, match="No historical candles found in PostgreSQL"):
        await load_historical_candles_from_db(
            db=db_session,
            symbol="NONEXISTENT",
            timeframe="15m",
            start_date=t1,
            end_date=t2,
        )


@pytest.mark.asyncio
async def test_replay_from_db_factory_integration(db_session: AsyncSession):
    """Verify ChronologicalReplayEngine.from_db constructor integration."""
    inst = models.Instrument(symbol="TCS", name="Tata Consultancy Services Ltd")
    db_session.add(inst)
    await db_session.flush()

    t1 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    db_session.add_all(
        [
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=t1,
                open=3000.0,
                high=3020.0,
                low=2990.0,
                close=3010.0,
            ),
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=t2,
                open=3010.0,
                high=3030.0,
                low=3000.0,
                close=3020.0,
            ),
        ]
    )
    await db_session.commit()

    engine = await ChronologicalReplayEngine.from_db(
        db=db_session,
        symbol="TCS",
        timeframe="15m",
        start_date=t1,
        end_date=t2,
        initial_capital=50000.0,
    )

    assert engine.total_candles == 2
    assert engine.symbol == "TCS"
    assert engine.portfolio.initial_capital == 50000.0

    summary = engine.run()
    assert summary.total_steps == 2
    assert summary.final_portfolio_state.total_portfolio_value == 50000.0
