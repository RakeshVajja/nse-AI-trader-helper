"""Targeted unit and integration tests for Phase 5D: Deterministic Stop-Loss & Take-Profit Auto-Triggers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.schemas import (
    ExecutionConfig,
    OrderSide,
    OrderStatus,
    PositionState,
)
from app.trading.triggers import (
    EXIT_REASON_STOP_LOSS,
    EXIT_REASON_TAKE_PROFIT,
    TriggerMonitor,
    check_position_trigger,
    create_exit_order,
)


@pytest.fixture
def clean_portfolio() -> PortfolioTracker:
    """Fresh portfolio with standard initial capital ₹1,00,000."""
    return PortfolioTracker(initial_capital=100000.0)


@pytest.fixture
def execution_engine() -> ExecutionEngine:
    """Standard ExecutionEngine with 0.05% slippage and 0.03% brokerage."""
    return ExecutionEngine(
        config=ExecutionConfig(
            slippage_pct=0.0005,
            brokerage_rate=0.0003,
            fixed_fee_per_order=0.0,
        )
    )


@pytest.fixture
def trigger_monitor(execution_engine: ExecutionEngine) -> TriggerMonitor:
    """TriggerMonitor using the standard execution engine."""
    return TriggerMonitor(execution_engine=execution_engine)


# =====================================================================
# 1. Exact SL / TP Boundary Touches & Low/High Discrimination
# =====================================================================


def test_exact_sl_tp_boundary_touches():
    """Verify exact boundary touches: low <= SL triggers SL, high >= TP triggers TP."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # Position: entry=1000.0, SL=950.0, TP=1050.0
    pos = PositionState(
        symbol="RELIANCE",
        quantity=10,
        average_entry_price=1000.0,
        current_price=1000.0,
        market_value=10000.0,
        unrealized_gross_pnl=0.0,
        unrealized_pnl_pct=0.0,
        stop_loss=950.0,
        take_profit=1050.0,
        is_open=True,
        entry_time=t0,
        last_updated=t0,
    )

    # 1. Exact touch on SL (low == 950.00) -> STOP_LOSS
    c_exact_sl = CandleData(
        timestamp=t1, open=980.0, high=990.0, low=950.0, close=960.0, volume=500.0
    )
    assert check_position_trigger(c_exact_sl, pos) == EXIT_REASON_STOP_LOSS

    # 2. Just above SL (low == 950.01) -> None (no trigger)
    c_above_sl = CandleData(
        timestamp=t1, open=980.0, high=990.0, low=950.01, close=960.0, volume=500.0
    )
    assert check_position_trigger(c_above_sl, pos) is None

    # 3. Exact touch on TP (high == 1050.00) -> TAKE_PROFIT
    c_exact_tp = CandleData(
        timestamp=t1, open=1020.0, high=1050.0, low=1010.0, close=1040.0, volume=500.0
    )
    assert check_position_trigger(c_exact_tp, pos) == EXIT_REASON_TAKE_PROFIT

    # 4. Just below TP (high == 1049.99) -> None (no trigger)
    c_below_tp = CandleData(
        timestamp=t1, open=1020.0, high=1049.99, low=1010.0, close=1040.0, volume=500.0
    )
    assert check_position_trigger(c_below_tp, pos) is None


def test_sl_vs_tp_independent_discrimination():
    """Verify clean discrimination between SL only, TP only, and neither."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    pos = PositionState(
        symbol="TCS",
        quantity=5,
        average_entry_price=3000.0,
        current_price=3000.0,
        market_value=15000.0,
        unrealized_gross_pnl=0.0,
        unrealized_pnl_pct=0.0,
        stop_loss=2900.0,
        take_profit=3200.0,
        is_open=True,
        entry_time=t0,
        last_updated=t0,
    )

    # 1. Bearish candle piercing SL only
    c_sl_only = CandleData(
        timestamp=t1, open=2950.0, high=2980.0, low=2880.0, close=2890.0, volume=100.0
    )
    assert check_position_trigger(c_sl_only, pos) == EXIT_REASON_STOP_LOSS

    # 2. Bullish candle piercing TP only
    c_tp_only = CandleData(
        timestamp=t1, open=3100.0, high=3250.0, low=3080.0, close=3220.0, volume=100.0
    )
    assert check_position_trigger(c_tp_only, pos) == EXIT_REASON_TAKE_PROFIT

    # 3. Inside candle touching neither
    c_neutral = CandleData(
        timestamp=t1, open=3000.0, high=3100.0, low=2950.0, close=3050.0, volume=100.0
    )
    assert check_position_trigger(c_neutral, pos) is None


# =====================================================================
# 2. Dual-Touch Precedence (Conservative Deterministic Rule)
# =====================================================================


def test_dual_touch_same_candle_stop_loss_precedence():
    """Verify STOP_LOSS takes strict precedence when a candle touches BOTH SL and TP.

    Project Specification Section 34:
    "An OHLC candle can potentially span both the stop-loss and take-profit levels.
    Because standard OHLC summary bars do not reveal intrabar price sequencing:
    STOP_LOSS takes strict precedence."
    """
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # Entry = 1000.0, SL = 950.0, TP = 1050.0
    pos = PositionState(
        symbol="INFY",
        quantity=20,
        average_entry_price=1000.0,
        current_price=1000.0,
        market_value=20000.0,
        unrealized_gross_pnl=0.0,
        unrealized_pnl_pct=0.0,
        stop_loss=950.0,
        take_profit=1050.0,
        is_open=True,
        entry_time=t0,
        last_updated=t0,
    )

    # Extreme volatility bar: Low is 920.0 (<= 950 SL) AND High is 1080.0 (>= 1050 TP)
    c_dual_touch = CandleData(
        timestamp=t1, open=1000.0, high=1080.0, low=920.0, close=1020.0, volume=5000.0
    )

    # Must choose STOP_LOSS strictly
    reason = check_position_trigger(c_dual_touch, pos)
    assert reason == EXIT_REASON_STOP_LOSS

    # Verify exit order created from this dual-touch has reason="STOP_LOSS"
    order = create_exit_order(pos, c_dual_touch, reason)
    assert order.reason == EXIT_REASON_STOP_LOSS
    assert order.decision_price == 950.0  # SL threshold recorded as metadata
    assert order.side == OrderSide.SELL
    assert order.quantity == 20


# =====================================================================
# 3. Trigger Candle vs Execution Candle Separation & Next-Candle Open Fill
# =====================================================================


def test_trigger_candle_vs_execution_candle_separation(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Verify trigger candle (t) and execution/fill candle (t+1) are strictly distinct.

    Trigger occurs on candle t; market exit fills at candle t+1 OPEN with slippage.
    Fill price is strictly next candle OPEN, never candle t close or SL level.
    """
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # 1. Open long position of 10 shares @ 1000 on candle t0
    clean_portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=1000.0,
        timestamp=t0,
        stop_loss=950.0,
        take_profit=1100.0,
    )
    pos = clean_portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10

    # 2. Candle t1 arrives: Low is 940.0 (hits SL 950.0)
    c_t1 = CandleData(timestamp=t1, open=980.0, high=990.0, low=940.0, close=945.0, volume=1000.0)

    # Simulation cycle on t1:
    # No prior pending exits -> executions is empty.
    # Evaluates completed candle t1 -> triggers SL and queues exit order for t2 OPEN.
    execs_t1, queued_t1 = trigger_monitor.process_simulation_cycle(c_t1, clean_portfolio)
    assert len(execs_t1) == 0
    assert len(queued_t1) == 1

    exit_order = queued_t1[0]
    assert exit_order.symbol == "RELIANCE"
    assert exit_order.reason == EXIT_REASON_STOP_LOSS
    assert exit_order.decision_time == t1  # Triggered at t1
    assert exit_order.decision_price == 950.0  # Metadata only!
    assert exit_order.quantity == 10

    # Position is STILL open on candle t1 (order is queued, not yet filled!)
    assert clean_portfolio.get_position("RELIANCE") is not None
    assert clean_portfolio.get_position("RELIANCE").quantity == 10
    assert trigger_monitor.is_exit_pending("RELIANCE")

    # 3. Candle t2 arrives: Open is 930.0 (gapped down overnight / next period)
    c_t2 = CandleData(timestamp=t2, open=930.0, high=940.0, low=925.0, close=935.0, volume=1000.0)

    # Simulation cycle on t2:
    # Step 1 & 2: Executes the pending exit at candle t2 OPEN!
    # Fill price = 930.0 * (1 - 0.0005) = 929.535 -> 929.5350
    execs_t2, queued_t2 = trigger_monitor.process_simulation_cycle(c_t2, clean_portfolio)
    assert len(execs_t2) == 1
    assert len(queued_t2) == 0  # Position is now closed, no new trigger generated

    res = execs_t2[0]
    assert res.status == OrderStatus.FILLED
    assert res.executed_at == t2  # Strictly executed at t2!
    assert res.decision_time == t1  # Decision was at t1!
    assert res.market_price == 930.0  # Filled against t2 OPEN, not t1 close or SL level
    assert res.execution_price == 929.535

    # Position is now closed in portfolio
    assert clean_portfolio.get_position("RELIANCE") is None
    assert not trigger_monitor.is_exit_pending("RELIANCE")


# =====================================================================
# 4. Slippage, Transaction Costs & Cash Reconciliation
# =====================================================================


def test_slippage_transaction_costs_and_accounting_reconciliation():
    """Verify exit execution adheres strictly to Phase 5A/5B cost and cash accounting rules."""
    exec_engine = ExecutionEngine(
        config=ExecutionConfig(
            slippage_pct=0.0005,
            brokerage_rate=0.0003,
            fixed_fee_per_order=10.0,  # ₹10 fixed fee
        )
    )
    monitor = TriggerMonitor(execution_engine=exec_engine)
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # Buy 20 shares @ 1000.0:
    # cash outflow = 20 * 1000.0 + (20 * 1000.0 * 0.0003 + 10.0) = 20000.0 + 16.0 = 20016.0
    portfolio.open_or_increase_position(
        symbol="SBIN",
        quantity=20,
        price=1000.0,
        timestamp=t0,
        transaction_cost=16.0,
        stop_loss=950.0,
        take_profit=1100.0,
    )
    assert portfolio.cash == 79984.0

    # Candle t1 touches Take-Profit (high = 1120.0 >= 1100.0)
    c_t1 = CandleData(
        timestamp=t1, open=1050.0, high=1120.0, low=1040.0, close=1110.0, volume=2000.0
    )
    _, queued = monitor.process_simulation_cycle(c_t1, portfolio)
    assert len(queued) == 1
    assert queued[0].reason == EXIT_REASON_TAKE_PROFIT

    # Candle t2 arrives: open = 1115.0
    # Expected fill price = 1115.0 * (1 - 0.0005) = 1114.4425
    # Nominal = 20 * 1114.4425 = 22288.85
    # Transaction cost = 22288.85 * 0.0003 + 10.0 = 6.6867 + 10.0 = 16.6867 -> 16.69
    # Cash inflow = 22288.85 - 16.69 = 22272.16
    # New cash = 79984.0 + 22272.16 = 102256.16
    c_t2 = CandleData(
        timestamp=t2, open=1115.0, high=1130.0, low=1110.0, close=1125.0, volume=2000.0
    )
    execs, _ = monitor.process_simulation_cycle(c_t2, portfolio)
    assert len(execs) == 1

    res = execs[0]
    assert res.status == OrderStatus.FILLED
    assert res.trade_record is not None
    assert res.trade_record.exit_reason == EXIT_REASON_TAKE_PROFIT

    # Strict conservation invariant: Equity = Cash + Market Value = Initial Capital + Net P&L
    state = portfolio.get_state()
    assert state.open_positions_count == 0
    assert state.closed_trades_count == 1
    assert state.total_portfolio_value == state.cash
    assert round(state.total_portfolio_value, 2) == round(state.initial_capital + state.net_pnl, 2)


# =====================================================================
# 5. Pending Exit Deduplication & Post-Exit Terminal State
# =====================================================================


def test_pending_exit_deduplication_prevents_duplicate_orders(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Verify that a position with an in-flight exit order NEVER generates duplicate exit orders."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    clean_portfolio.open_or_increase_position(
        symbol="TATASTEEL",
        quantity=50,
        price=150.0,
        timestamp=t0,
        stop_loss=140.0,
    )

    c_t1 = CandleData(timestamp=t1, open=145.0, high=146.0, low=138.0, close=139.0, volume=500.0)

    # First evaluation emits order
    orders1 = trigger_monitor.evaluate_completed_candle(c_t1, clean_portfolio)
    assert len(orders1) == 1
    assert trigger_monitor.is_exit_pending("TATASTEEL")

    # Second evaluation on the same or subsequent candle before execution
    orders2 = trigger_monitor.evaluate_completed_candle(c_t1, clean_portfolio)
    assert len(orders2) == 0  # Deduplication: zero new orders emitted!

    # A third evaluation also yields zero orders
    orders3 = trigger_monitor.evaluate_completed_candle(c_t1, clean_portfolio)
    assert len(orders3) == 0


def test_closed_position_terminal_behavior_generates_no_further_triggers(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Verify that once closed, a position reaches terminal state and emits no further triggers."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)

    clean_portfolio.open_or_increase_position(
        symbol="HDFCBANK",
        quantity=15,
        price=1600.0,
        timestamp=t0,
        stop_loss=1550.0,
    )

    # t1 triggers SL
    c_t1 = CandleData(
        timestamp=t1, open=1580.0, high=1590.0, low=1540.0, close=1545.0, volume=100.0
    )
    trigger_monitor.process_simulation_cycle(c_t1, clean_portfolio)

    # t2 executes exit and closes position
    c_t2 = CandleData(
        timestamp=t2, open=1540.0, high=1550.0, low=1520.0, close=1530.0, volume=100.0
    )
    execs_t2, queued_t2 = trigger_monitor.process_simulation_cycle(c_t2, clean_portfolio)
    assert len(execs_t2) == 1
    assert len(queued_t2) == 0
    assert clean_portfolio.get_position("HDFCBANK") is None

    # t3 crashes even further (low = 1400.0 << SL 1550.0)
    c_t3 = CandleData(
        timestamp=t3, open=1520.0, high=1530.0, low=1400.0, close=1420.0, volume=100.0
    )
    execs_t3, queued_t3 = trigger_monitor.process_simulation_cycle(c_t3, clean_portfolio)
    assert len(execs_t3) == 0
    assert len(queued_t3) == 0  # Closed position generates ZERO triggers!


# =====================================================================
# 6. Final-Candle End-of-Series Handling
# =====================================================================


def test_final_candle_end_of_series_graceful_rejection(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Verify that if an exit is queued on the final candle, execution against None is rejected."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t_final = datetime(2026, 1, 15, 15, 15, tzinfo=timezone.utc)

    clean_portfolio.open_or_increase_position(
        symbol="WIPRO",
        quantity=30,
        price=400.0,
        timestamp=t0,
        stop_loss=380.0,
    )

    # Final candle hits SL
    c_final = CandleData(
        timestamp=t_final, open=390.0, high=395.0, low=375.0, close=378.0, volume=100.0
    )
    _, queued = trigger_monitor.process_simulation_cycle(c_final, clean_portfolio)
    assert len(queued) == 1
    assert trigger_monitor.is_exit_pending("WIPRO")

    # End of series: execute_pending_exits called with next_candle=None
    results = trigger_monitor.execute_pending_exits(None, clean_portfolio)
    assert len(results) == 1
    assert results[0].status == OrderStatus.REJECTED
    assert "Next candle unavailable" in (results[0].rejection_reason or "")

    # Position was NOT improperly liquidated without a fill
    assert clean_portfolio.get_position("WIPRO") is not None


# =====================================================================
# 7. Multiple Positions Simultaneous Triggers
# =====================================================================


def test_multiple_positions_simultaneous_sl_tp_triggers(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Verify that multiple open positions evaluate triggers independently and accurately."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # POS_A has SL=90.0, TP=110.0
    # POS_B has SL=70.0, TP=120.0
    clean_portfolio.open_or_increase_position(
        symbol="POS_A",
        quantity=10,
        price=100.0,
        timestamp=t0,
        stop_loss=90.0,
        take_profit=110.0,
    )
    clean_portfolio.open_or_increase_position(
        symbol="POS_B",
        quantity=20,
        price=100.0,
        timestamp=t0,
        stop_loss=70.0,
        take_profit=120.0,
    )

    # Candle t1: low=85.0 (<= 90.0 hits POS_A SL; > 70.0 does NOT hit POS_B SL),
    #            high=125.0 (>= 120.0 hits POS_B TP; >= 110.0 would hit POS_A TP, but for POS_A SL took priority via dual-touch!)
    # To strictly test POS_B hitting TP only:
    # low=85.0 > POS_B SL (70.0), high=125.0 >= POS_B TP (120.0) -> POS_B hits TP!
    # For POS_A: low=85.0 <= 90.0 (hits SL), high=105.0 < 110.0 (no TP touch)
    # Using symbol-specific evaluation:
    c_t1_a = CandleData(timestamp=t1, open=95.0, high=105.0, low=85.0, close=90.0, volume=1000.0)
    c_t1_b = CandleData(timestamp=t1, open=105.0, high=125.0, low=100.0, close=122.0, volume=1000.0)

    queued_a = trigger_monitor.evaluate_completed_candle(c_t1_a, clean_portfolio, symbol="POS_A")
    queued_b = trigger_monitor.evaluate_completed_candle(c_t1_b, clean_portfolio, symbol="POS_B")
    assert len(queued_a) == 1
    assert len(queued_b) == 1
    assert queued_a[0].reason == EXIT_REASON_STOP_LOSS
    assert queued_b[0].reason == EXIT_REASON_TAKE_PROFIT

    # Execute both on t2
    c_t2 = CandleData(timestamp=t2, open=100.0, high=105.0, low=95.0, close=100.0, volume=1000.0)
    execs = trigger_monitor.execute_pending_exits(c_t2, clean_portfolio)
    assert len(execs) == 2
    assert all(e.status == OrderStatus.FILLED for e in execs)

    # Both positions closed
    assert clean_portfolio.get_position("POS_A") is None
    assert clean_portfolio.get_position("POS_B") is None
    assert clean_portfolio.get_state().closed_trades_count == 2


# =====================================================================
# 8. Deterministic Reproducibility
# =====================================================================


def test_deterministic_reproducibility():
    """Verify running the same sequence twice yields bit-for-bit identical results."""
    candles = [
        CandleData(
            timestamp=datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc),
            open=1000.0,
            high=1010.0,
            low=990.0,
            close=1005.0,
        ),
        CandleData(
            timestamp=datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc),
            open=1005.0,
            high=1015.0,
            low=940.0,  # Hits SL 950
            close=945.0,
        ),
        CandleData(
            timestamp=datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc),
            open=942.0,  # Execution open
            high=950.0,
            low=930.0,
            close=948.0,
        ),
    ]

    def run_sim():
        engine = ExecutionEngine(config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003))
        monitor = TriggerMonitor(execution_engine=engine)
        p = PortfolioTracker(initial_capital=100000.0)

        # Open position
        p.open_or_increase_position(
            symbol="TEST",
            quantity=10,
            price=1000.0,
            timestamp=candles[0].timestamp,
            stop_loss=950.0,
            take_profit=1100.0,
        )

        all_execs = []
        for c in candles:
            execs, _ = monitor.process_simulation_cycle(c, p)
            all_execs.extend(execs)

        return p.get_state(), all_execs

    state1, execs1 = run_sim()
    state2, execs2 = run_sim()

    assert state1.cash == state2.cash
    assert state1.net_pnl == state2.net_pnl
    assert state1.total_transaction_costs == state2.total_transaction_costs
    assert state1.total_slippage_cost == state2.total_slippage_cost
    assert len(execs1) == len(execs2)
    assert execs1[0].execution_price == execs2[0].execution_price
    assert execs1[0].transaction_cost == execs2[0].transaction_cost


# =====================================================================
# 9. Invalid Input & Defensive Checks
# =====================================================================


def test_invalid_candle_data_raises_value_error():
    """Verify invalid candle values (high < low, non-positive) raise ValueError."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    pos = PositionState(
        symbol="ERR",
        quantity=5,
        average_entry_price=100.0,
        current_price=100.0,
        market_value=500.0,
        unrealized_gross_pnl=0.0,
        unrealized_pnl_pct=0.0,
        stop_loss=90.0,
        is_open=True,
        entry_time=t0,
        last_updated=t0,
    )

    # 1. Inverted prices (high < low)
    c_inv = CandleData(timestamp=t0, open=100.0, high=90.0, low=110.0, close=95.0, volume=10.0)
    with pytest.raises(ValueError, match="cannot be less than low"):
        check_position_trigger(c_inv, pos)

    # 2. Zero price
    c_zero = CandleData(timestamp=t0, open=100.0, high=100.0, low=0.0, close=95.0, volume=10.0)
    with pytest.raises(ValueError, match="must be strictly positive"):
        check_position_trigger(c_zero, pos)


# =====================================================================
# 10. Multi-Symbol Cross-Contamination Regression Tests (Phase 5D Audit Fix)
# =====================================================================


def test_cross_symbol_execution_isolation_and_correct_fill_price(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Prove that a pending TCS exit remains pending when a RELIANCE candle is processed,

    and executes only when a TCS candle arrives at its correct fill price.
    """
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # 1. Setup multi-position portfolio
    clean_portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2500.0,
        timestamp=t0,
        stop_loss=2400.0,
    )
    clean_portfolio.open_or_increase_position(
        symbol="TCS",
        quantity=5,
        price=3500.0,
        timestamp=t0,
        stop_loss=3400.0,
    )

    # 2. Candle t1 for TCS touches Stop-Loss (low = 3350.0 <= 3400.0)
    c_tcs_t1 = CandleData(
        timestamp=t1, open=3450.0, high=3460.0, low=3350.0, close=3380.0, volume=500.0
    )
    queued_tcs = trigger_monitor.evaluate_completed_candle(c_tcs_t1, clean_portfolio, symbol="TCS")
    assert len(queued_tcs) == 1
    assert trigger_monitor.is_exit_pending("TCS")
    assert not trigger_monitor.is_exit_pending("RELIANCE")

    # 3. Candle t2 for RELIANCE arrives with open = 2500.0
    c_rel_t2 = CandleData(
        timestamp=t2, open=2500.0, high=2520.0, low=2490.0, close=2510.0, volume=1000.0
    )

    # Process simulation cycle for RELIANCE:
    execs_rel, queued_rel = trigger_monitor.process_simulation_cycle(
        c_rel_t2, clean_portfolio, symbol="RELIANCE"
    )

    # REQUIREMENT 1: The pending TCS exit REMAINS pending when a RELIANCE candle is processed!
    assert len(execs_rel) == 0
    assert len(queued_rel) == 0
    assert trigger_monitor.is_exit_pending("TCS")
    assert clean_portfolio.get_position("TCS") is not None
    assert clean_portfolio.get_position("TCS").quantity == 5

    # 4. Candle t2 for TCS arrives with open = 3370.0
    c_tcs_t2 = CandleData(
        timestamp=t2, open=3370.0, high=3390.0, low=3360.0, close=3380.0, volume=500.0
    )

    # Process simulation cycle for TCS:
    execs_tcs, queued_tcs2 = trigger_monitor.process_simulation_cycle(
        c_tcs_t2, clean_portfolio, symbol="TCS"
    )

    # REQUIREMENT 2: TCS exit executes only when the TCS candle for t2 arrives!
    assert len(execs_tcs) == 1
    assert len(queued_tcs2) == 0
    res_tcs = execs_tcs[0]
    assert res_tcs.status == OrderStatus.FILLED
    assert res_tcs.symbol == "TCS"

    # REQUIREMENT 3: The fill price is based on the correct symbol's OPEN (3370.0), NOT RELIANCE (2500.0)!
    # 3370.0 * (1 - 0.0005) = 3368.315
    assert res_tcs.market_price == 3370.0
    assert res_tcs.execution_price == 3368.315

    # TCS position is now closed, RELIANCE remains open
    assert not trigger_monitor.is_exit_pending("TCS")
    assert clean_portfolio.get_position("TCS") is None
    assert clean_portfolio.get_position("RELIANCE") is not None
    assert clean_portfolio.get_position("RELIANCE").quantity == 10


def test_multiple_pending_exits_execute_independently_on_their_respective_candles(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Prove that multiple pending exits for different symbols execute independently on their respective candles."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    clean_portfolio.open_or_increase_position(
        symbol="INFY",
        quantity=20,
        price=1500.0,
        timestamp=t0,
        stop_loss=1450.0,
    )
    clean_portfolio.open_or_increase_position(
        symbol="SBIN",
        quantity=50,
        price=600.0,
        timestamp=t0,
        take_profit=650.0,
    )

    # t1: INFY touches SL, SBIN touches TP
    c_infy_t1 = CandleData(
        timestamp=t1, open=1460.0, high=1470.0, low=1440.0, close=1445.0, volume=100.0
    )
    c_sbin_t1 = CandleData(
        timestamp=t1, open=630.0, high=660.0, low=620.0, close=655.0, volume=100.0
    )

    trigger_monitor.evaluate_completed_candle(c_infy_t1, clean_portfolio, symbol="INFY")
    trigger_monitor.evaluate_completed_candle(c_sbin_t1, clean_portfolio, symbol="SBIN")

    assert trigger_monitor.get_pending_symbols() == {"INFY", "SBIN"}

    # t2: INFY candle processed first
    c_infy_t2 = CandleData(
        timestamp=t2, open=1440.0, high=1450.0, low=1430.0, close=1435.0, volume=100.0
    )
    execs_infy, _ = trigger_monitor.process_simulation_cycle(
        c_infy_t2, clean_portfolio, symbol="INFY"
    )

    assert len(execs_infy) == 1
    assert execs_infy[0].symbol == "INFY"
    assert execs_infy[0].market_price == 1440.0
    # SBIN MUST remain pending!
    assert trigger_monitor.is_exit_pending("SBIN")
    assert clean_portfolio.get_position("SBIN") is not None

    # t2: SBIN candle processed next
    c_sbin_t2 = CandleData(
        timestamp=t2, open=655.0, high=660.0, low=650.0, close=652.0, volume=100.0
    )
    execs_sbin, _ = trigger_monitor.process_simulation_cycle(
        c_sbin_t2, clean_portfolio, symbol="SBIN"
    )

    assert len(execs_sbin) == 1
    assert execs_sbin[0].symbol == "SBIN"
    assert execs_sbin[0].market_price == 655.0

    # Both are closed, pending_exits is empty
    assert len(trigger_monitor.get_pending_symbols()) == 0
    assert clean_portfolio.get_position("INFY") is None
    assert clean_portfolio.get_position("SBIN") is None


def test_omitting_symbol_on_multi_position_portfolio_raises_error_guarding_cross_trigger(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Prove that omitting symbol on a multi-position portfolio raises an error preventing cross-instrument trigger."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # Multi-position portfolio: TCS (high price) and ZOMATO (low price)
    clean_portfolio.open_or_increase_position(
        symbol="TCS",
        quantity=5,
        price=3500.0,
        timestamp=t0,
        stop_loss=3400.0,
    )
    clean_portfolio.open_or_increase_position(
        symbol="ZOMATO",
        quantity=100,
        price=160.0,
        timestamp=t0,
        stop_loss=140.0,
    )

    # ZOMATO candle with low = 145.0 (which is <= 3400.0, so it would trigger TCS if cross-evaluated!)
    c_zomato = CandleData(
        timestamp=t1, open=150.0, high=155.0, low=145.0, close=150.0, volume=1000.0
    )

    # Omitting symbol must raise ValueError
    with pytest.raises(
        ValueError, match="Symbol must be specified when portfolio holds multiple positions"
    ):
        trigger_monitor.evaluate_completed_candle(c_zomato, clean_portfolio, symbol=None)

    # Also raises on process_simulation_cycle when symbol is omitted
    with pytest.raises(
        ValueError, match="Symbol must be specified when portfolio holds multiple positions"
    ):
        trigger_monitor.process_simulation_cycle(c_zomato, clean_portfolio, symbol=None)

    # Proves TCS was NEVER triggered by ZOMATO's candle!
    assert not trigger_monitor.is_exit_pending("TCS")
    assert not trigger_monitor.is_exit_pending("ZOMATO")


def test_single_position_symbol_inference_preserves_existing_behavior(
    clean_portfolio: PortfolioTracker,
    trigger_monitor: TriggerMonitor,
):
    """Prove that existing single-position workflows where symbol is omitted work seamlessly with safe inference."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # Single position in portfolio
    clean_portfolio.open_or_increase_position(
        symbol="SINGLE_STOCK",
        quantity=10,
        price=100.0,
        timestamp=t0,
        stop_loss=90.0,
    )

    # Candle t1 triggers SL without specifying symbol
    c_t1 = CandleData(timestamp=t1, open=95.0, high=96.0, low=88.0, close=89.0, volume=100.0)
    execs_t1, queued_t1 = trigger_monitor.process_simulation_cycle(
        c_t1, clean_portfolio, symbol=None
    )

    assert len(execs_t1) == 0
    assert len(queued_t1) == 1
    assert queued_t1[0].symbol == "SINGLE_STOCK"
    assert trigger_monitor.is_exit_pending("SINGLE_STOCK")

    # Candle t2 executes without specifying symbol
    c_t2 = CandleData(timestamp=t2, open=87.0, high=90.0, low=86.0, close=88.0, volume=100.0)
    execs_t2, queued_t2 = trigger_monitor.process_simulation_cycle(
        c_t2, clean_portfolio, symbol=None
    )

    assert len(execs_t2) == 1
    assert len(queued_t2) == 0
    assert execs_t2[0].status == OrderStatus.FILLED
    assert execs_t2[0].symbol == "SINGLE_STOCK"
    assert clean_portfolio.get_position("SINGLE_STOCK") is None
