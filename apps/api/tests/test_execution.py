"""Targeted unit tests for Phase 5B: Deterministic Execution Model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.schemas import (
    ExecutionConfig,
    OrderRequest,
    OrderSide,
    OrderStatus,
)


def _make_candle(
    timestamp: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float = 1000.0,
) -> CandleData:
    return CandleData(
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )


def test_slippage_price_calculation_buy_and_sell():
    """Verify default 0.05% slippage and directional sign convention."""
    engine = ExecutionEngine()  # default 0.05% (0.0005)

    # 1. BUY: market_price * (1 + 0.0005)
    buy_price = engine.calculate_execution_price(market_price=1000.0, side=OrderSide.BUY)
    assert buy_price == 1000.50

    # 2. SELL: market_price * (1 - 0.0005)
    sell_price = engine.calculate_execution_price(market_price=1000.0, side=OrderSide.SELL)
    assert sell_price == 999.50

    # 3. Custom slippage (e.g. 0.1% = 0.001)
    custom_engine = ExecutionEngine(config=ExecutionConfig(slippage_pct=0.001))
    assert custom_engine.calculate_execution_price(2500.0, OrderSide.BUY) == 2502.50
    assert custom_engine.calculate_execution_price(2500.0, OrderSide.SELL) == 2497.50

    # 4. Zero / negative price validation
    with pytest.raises(ValueError, match="market_price must be > 0.0"):
        engine.calculate_execution_price(0.0, OrderSide.BUY)

    with pytest.raises(ValueError, match="market_price must be > 0.0"):
        engine.calculate_execution_price(-100.0, OrderSide.SELL)


def test_transaction_cost_and_slippage_cost_calculation():
    """Verify transaction fees and slippage impact calculations."""
    engine = ExecutionEngine(
        config=ExecutionConfig(brokerage_rate=0.0003, fixed_fee_per_order=10.0, slippage_pct=0.0005)
    )

    # Traded value ₹50,000
    # Transaction cost = 50,000 * 0.0003 + 10 = 15.0 + 10 = ₹25.0
    tx_cost = engine.calculate_transaction_cost(50000.0)
    assert tx_cost == 25.0

    # Slippage cost for 50 units: market=1000.0, exec=1000.50 -> slippage cost = 0.50 * 50 = ₹25.0
    slip_cost = engine.calculate_slippage_cost(
        market_price=1000.0, execution_price=1000.50, quantity=50
    )
    assert slip_cost == 25.0

    # Invalid nominal / quantity checks
    with pytest.raises(ValueError, match="nominal_value cannot be negative"):
        engine.calculate_transaction_cost(-500.0)

    with pytest.raises(ValueError, match="quantity must be > 0"):
        engine.calculate_slippage_cost(1000.0, 1000.50, 0)


def test_next_candle_open_execution():
    """Verify market orders execute strictly at next candle OPEN price and not decision candle CLOSE."""
    engine = ExecutionEngine()
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # Decision candle t (Close = 2520.0)
    # Next candle t+1 (Open = 2530.0)
    next_candle = _make_candle(
        timestamp=t1,
        open_price=2530.0,
        high_price=2545.0,
        low_price=2525.0,
        close_price=2540.0,
    )

    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        decision_time=t0,
        decision_price=2520.0,  # Decision candle close (must NOT be used for fill)
    )

    result = engine.execute_order(order=order, next_candle=next_candle, portfolio=portfolio)

    assert result.status == OrderStatus.FILLED
    assert result.symbol == "RELIANCE"
    assert result.side == OrderSide.BUY
    assert result.quantity == 10
    # Market price must be Next Candle Open (2530.0)
    assert result.market_price == 2530.0
    # Execution price must be 2530.0 * (1 + 0.0005) = 2531.265
    assert result.execution_price == 2531.265
    assert result.executed_at == t1
    assert result.decision_time == t0
    assert result.trade_record is None

    # Verify portfolio state
    pos = portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10
    assert pos.average_entry_price == 2531.265


def test_decision_candle_exclusion_and_timestamp_validation():
    """Verify orders cannot execute against the decision candle itself (look-ahead prevention)."""
    engine = ExecutionEngine()
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    decision_candle = _make_candle(
        timestamp=t0,
        open_price=2500.0,
        high_price=2525.0,
        low_price=2495.0,
        close_price=2520.0,
    )

    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        decision_time=t0,
    )

    # Attempting to execute with next_candle having timestamp <= decision_time
    result = engine.execute_order(order=order, next_candle=decision_candle, portfolio=portfolio)

    assert result.status == OrderStatus.REJECTED
    assert "must be strictly after decision timestamp" in (result.rejection_reason or "")
    assert portfolio.get_position("RELIANCE") is None


def test_unavailable_next_candle_rejection():
    """Verify execution engine handles end of historical data / missing next candle gracefully."""
    engine = ExecutionEngine()
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 15, 15, tzinfo=timezone.utc)
    order = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
    )

    result = engine.execute_order(order=order, next_candle=None, portfolio=portfolio)

    assert result.status == OrderStatus.REJECTED
    assert "Next candle unavailable" in (result.rejection_reason or "")
    assert portfolio.get_position("INFY") is None


def test_execution_engine_round_trip_buy_and_sell():
    """Verify complete BUY followed by SELL execution lifecycle with fee and slippage reconciliation."""
    engine = ExecutionEngine()
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # 1. Buy 10 shares of TCS at t1 Open (3000.0)
    c1 = _make_candle(
        t1, open_price=3000.0, high_price=3050.0, low_price=2990.0, close_price=3040.0
    )
    buy_order = OrderRequest(symbol="TCS", side=OrderSide.BUY, quantity=10, decision_time=t0)
    buy_res = engine.execute_order(order=buy_order, next_candle=c1, portfolio=portfolio)

    assert buy_res.status == OrderStatus.FILLED
    # Buy fill: 3000.0 * 1.0005 = 3001.50
    assert buy_res.execution_price == 3001.50

    # 2. Sell 10 shares of TCS at t2 Open (3200.0)
    c2 = _make_candle(
        t2, open_price=3200.0, high_price=3220.0, low_price=3180.0, close_price=3210.0
    )
    sell_order = OrderRequest(symbol="TCS", side=OrderSide.SELL, quantity=10, decision_time=t1)
    sell_res = engine.execute_order(order=sell_order, next_candle=c2, portfolio=portfolio)

    assert sell_res.status == OrderStatus.FILLED
    # Sell fill: 3200.0 * (1 - 0.0005) = 3198.40
    assert sell_res.execution_price == 3198.40
    assert sell_res.trade_record is not None

    trade = sell_res.trade_record
    assert trade.symbol == "TCS"
    assert trade.entry_price == 3001.50
    assert trade.exit_price == 3198.40
    # Gross PnL = 10 * (3198.40 - 3001.50) = 1969.00
    assert trade.gross_pnl == 1969.00

    # Position must be closed in portfolio
    assert portfolio.get_position("TCS") is None
    port_state = portfolio.get_state()
    assert port_state.closed_trades_count == 1
    assert port_state.open_positions_count == 0

    # Reconcile cash, costs, and equity without double-counted slippage
    # Buy: 10 * 3001.50 = 30015.0, tx_cost = 9.0045, slip = 15.0
    # Sell: 10 * 3198.40 = 31984.0, tx_cost = 9.5952, slip = 16.0
    # Expected final cash: 100000.0 - 30015.0 - 9.0045 + 31984.0 - 9.5952 = 101950.4003
    expected_cash = round(100000.0 - 30015.0 - 9.0045 + 31984.0 - 9.5952, 4)
    expected_tx_costs = round(9.0045 + 9.5952, 4)
    expected_net_pnl = round(1969.00 - expected_tx_costs, 4)

    assert port_state.cash == expected_cash
    assert port_state.total_portfolio_value == expected_cash
    assert port_state.total_transaction_costs == expected_tx_costs
    assert port_state.total_slippage_cost == 31.00  # 15.0 + 16.0 tracked as metric
    assert port_state.realized_gross_pnl == 1969.00
    assert port_state.net_pnl == expected_net_pnl
    assert port_state.total_portfolio_value == round(
        port_state.initial_capital + port_state.net_pnl, 4
    )


def test_execution_engine_sell_rejection_no_position_and_oversized():
    """Verify execution engine rejects sell orders when position does not exist or requested qty exceeds open."""
    engine = ExecutionEngine()
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    candle = _make_candle(
        t1, open_price=500.0, high_price=510.0, low_price=490.0, close_price=505.0
    )

    # 1. No position open
    sell_no_pos = OrderRequest(symbol="SBIN", side=OrderSide.SELL, quantity=10, decision_time=t0)
    res1 = engine.execute_order(order=sell_no_pos, next_candle=candle, portfolio=portfolio)
    assert res1.status == OrderStatus.REJECTED
    assert "No open position exists" in (res1.rejection_reason or "")

    # 2. Buy 5 shares, then attempt to sell 10 shares
    buy_order = OrderRequest(symbol="SBIN", side=OrderSide.BUY, quantity=5, decision_time=t0)
    engine.execute_order(order=buy_order, next_candle=candle, portfolio=portfolio)

    t2 = t1 + timedelta(minutes=15)
    candle2 = _make_candle(
        t2, open_price=510.0, high_price=520.0, low_price=500.0, close_price=515.0
    )
    sell_excessive = OrderRequest(symbol="SBIN", side=OrderSide.SELL, quantity=10, decision_time=t1)
    res2 = engine.execute_order(order=sell_excessive, next_candle=candle2, portfolio=portfolio)
    assert res2.status == OrderStatus.REJECTED
    assert "exceeds open position quantity" in (res2.rejection_reason or "")

    # Position remains 5 shares
    assert portfolio.get_position("SBIN").quantity == 5


def test_deterministic_reproducibility_execution():
    """Verify execution engine calculations are strictly deterministic and reproducible."""
    engine1 = ExecutionEngine()
    engine2 = ExecutionEngine()

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    candle = _make_candle(
        t1, open_price=1234.56, high_price=1240.0, low_price=1230.0, close_price=1235.0
    )

    p1 = PortfolioTracker(initial_capital=100000.0)
    p2 = PortfolioTracker(initial_capital=100000.0)

    order = OrderRequest(symbol="HDFCBANK", side=OrderSide.BUY, quantity=25, decision_time=t0)

    res1 = engine1.execute_order(order=order, next_candle=candle, portfolio=p1)
    res2 = engine2.execute_order(order=order, next_candle=candle, portfolio=p2)

    assert res1.execution_price == res2.execution_price
    assert res1.transaction_cost == res2.transaction_cost
    assert res1.slippage_cost == res2.slippage_cost
    assert p1.get_state().cash == p2.get_state().cash


# =====================================================================
# Regression Tests: Slippage Double-Counting Defect Prevention
# =====================================================================


def test_regression_buy_non_zero_slippage_no_double_counting():
    """Verify that BUY execution does NOT double-deduct slippage from portfolio cash or net P&L.

    Under the defect:
        Cash was deducted by: (quantity * execution_price) + tx_cost + slippage_cost
        where execution_price already included slippage. This deducted slippage TWICE.
    Under the corrected model:
        Cash is deducted by: (quantity * execution_price) + tx_cost
        slippage_cost is tracked strictly as a cumulative metric.
    """
    engine = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    portfolio = PortfolioTracker(initial_capital=200000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # Market open = 1000.0. Qty = 100.
    # execution_price = 1000.0 * 1.0005 = 1000.50
    # nominal = 100 * 1000.50 = 100050.0
    # tx_cost = 100050.0 * 0.0003 = 30.015
    # slippage_cost metric = |1000.50 - 1000.0| * 100 = 50.0
    candle = _make_candle(
        t1, open_price=1000.0, high_price=1010.0, low_price=990.0, close_price=1005.0
    )
    order = OrderRequest(symbol="INFY", side=OrderSide.BUY, quantity=100, decision_time=t0)

    res = engine.execute_order(order=order, next_candle=candle, portfolio=portfolio)

    assert res.status == OrderStatus.FILLED
    assert res.execution_price == 1000.50
    assert res.transaction_cost == 30.015
    assert res.slippage_cost == 50.0

    state = portfolio.get_state()
    # Correct cash: 200,000 - (100 * 1000.50 + 30.015) = 200,000 - 100,080.015 = 99,919.985
    expected_cash = 200000.0 - 100080.015
    assert state.cash == expected_cash

    # DEFECT REGRESSION GUARD: Under the bug, cash would be 99,919.985 - 50.0 = 99,869.985
    bugged_cash = expected_cash - 50.0
    assert state.cash != bugged_cash
    assert (
        round(state.cash - bugged_cash, 4) == 50.0
    )  # Exactly the double-deducted slippage eliminated

    # Market value at fill price: 100 * 1000.50 = 100,050.0
    assert state.total_market_value == 100050.0
    # Equity = 99,919.985 + 100,050.0 = 199,969.985
    assert state.total_portfolio_value == 199969.985
    assert state.total_transaction_costs == 30.015
    assert state.total_slippage_cost == 50.0  # Metric is tracked accurately
    assert state.gross_pnl == 0.0
    # Net PnL is strictly -30.015 (only transaction fee lost so far, since market value == entry cost basis)
    assert state.net_pnl == -30.015
    assert state.net_pnl != -80.015  # Would be -80.015 under bug!

    # Authoritative equity conservation invariant
    assert state.total_portfolio_value == round(state.initial_capital + state.net_pnl, 4)
    assert state.total_portfolio_value == round(state.cash + state.total_market_value, 4)


def test_regression_sell_non_zero_slippage_no_double_counting():
    """Verify that SELL execution does NOT double-deduct slippage from cash inflow or realized P&L.

    Under the defect:
        Cash inflow was: (quantity * execution_price) - tx_cost - slippage_cost
        where execution_price already had slippage subtracted. This penalized seller TWICE.
    Under the corrected model:
        Cash inflow is: (quantity * execution_price) - tx_cost
        slippage_cost is tracked strictly as a cumulative metric.
    """
    engine = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    portfolio = PortfolioTracker(initial_capital=200000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # 1. Open position directly at 1000.0 fill price (100 shares, 0 fee)
    portfolio.open_or_increase_position(
        symbol="INFY",
        quantity=100,
        price=1000.0,
        timestamp=t0,
        transaction_cost=0.0,
        slippage_cost=0.0,
    )
    assert portfolio.cash == 100000.0

    # 2. Sell at next open 1200.0 with 0.05% slippage
    # execution_price = 1200.0 * (1 - 0.0005) = 1199.40
    # nominal = 100 * 1199.40 = 119,940.0
    # tx_cost = 119940.0 * 0.0003 = 35.982
    # slippage_cost metric = |1199.40 - 1200.0| * 100 = 60.0
    candle_sell = _make_candle(
        t2, open_price=1200.0, high_price=1210.0, low_price=1195.0, close_price=1205.0
    )
    sell_order = OrderRequest(symbol="INFY", side=OrderSide.SELL, quantity=100, decision_time=t1)

    sell_res = engine.execute_order(order=sell_order, next_candle=candle_sell, portfolio=portfolio)

    assert sell_res.status == OrderStatus.FILLED
    assert sell_res.execution_price == 1199.40
    assert sell_res.transaction_cost == 35.982
    assert sell_res.slippage_cost == 60.0

    # Correct cash inflow: 119,940.0 - 35.982 = 119,904.018
    # Total cash: 100,000.0 + 119,904.018 = 219,904.018
    expected_cash = 100000.0 + 119940.0 - 35.982
    state = portfolio.get_state()
    assert state.cash == expected_cash

    # DEFECT REGRESSION GUARD: Under the bug, cash would be 219,904.018 - 60.0 = 219,844.018
    bugged_cash = expected_cash - 60.0
    assert state.cash != bugged_cash
    assert round(state.cash - bugged_cash, 4) == 60.0

    trade = sell_res.trade_record
    assert trade is not None
    assert trade.gross_pnl == round(100 * (1199.40 - 1000.0), 4)  # 19,940.0
    # Net PnL = gross_pnl - transaction_cost = 19,940.0 - 35.982 = 19,904.018
    assert trade.net_pnl == 19904.018
    assert trade.net_pnl != 19844.018  # Would be 19,844.018 under bug!
    assert trade.slippage_cost == 60.0
    assert trade.transaction_costs == 35.982


def test_regression_full_buy_sell_round_trip_numerical_reconciliation():
    """Verify complete BUY -> SELL round trip reconciles all metrics to the penny without double slippage."""
    engine = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # 1. BUY 100 shares @ open 1000.0
    c1 = _make_candle(t1, open_price=1000.0, high_price=1010.0, low_price=990.0, close_price=1005.0)
    buy_order = OrderRequest(symbol="RELIANCE", side=OrderSide.BUY, quantity=100, decision_time=t0)
    engine.execute_order(buy_order, c1, portfolio)

    # 2. SELL 100 shares @ open 1100.0
    c2 = _make_candle(
        t2, open_price=1100.0, high_price=1110.0, low_price=1090.0, close_price=1105.0
    )
    sell_order = OrderRequest(
        symbol="RELIANCE", side=OrderSide.SELL, quantity=100, decision_time=t1
    )
    engine.execute_order(sell_order, c2, portfolio)

    # Expected exact reconciliation:
    # BUY: exec=1000.50, nominal=100050.0, tx=30.015, slip=50.0
    # SELL: exec=1099.45, nominal=109945.0, tx=32.9835, slip=55.0
    # Realized Gross PnL = 100 * (1099.45 - 1000.50) = 9895.0
    # Total Transaction Costs = 30.015 + 32.9835 = 62.9985
    # Total Slippage Metric = 50.0 + 55.0 = 105.0
    # Net PnL = 9895.0 - 62.9985 = 9832.0015
    # Final Cash = 100000.0 + 9832.0015 = 109832.0015
    state = portfolio.get_state()

    assert state.realized_gross_pnl == 9895.0
    assert state.total_transaction_costs == 62.9985
    assert state.total_slippage_cost == 105.0
    assert state.gross_pnl == 9895.0
    assert state.net_pnl == 9832.0015
    assert state.cash == 109832.0015
    assert state.total_portfolio_value == 109832.0015

    # DEFECT REGRESSION GUARD:
    # Under the bug, reported equity was 109,727.0015 (erroneously losing an extra 105.0)
    assert state.cash != 109727.0015
    assert round(state.cash - 109727.0015, 4) == 105.0

    # Invariants
    assert state.total_portfolio_value == round(state.initial_capital + state.net_pnl, 4)
    assert state.total_portfolio_value == round(state.cash + state.total_market_value, 4)
    assert round(state.total_return_pct, 4) == round((9832.0015 / 100000.0) * 100.0, 4)


def test_regression_zero_slippage_exact_comparison():
    """Verify that zero-slippage execution matches theoretical benchmarks and quantifies exact slippage impact."""
    # Zero slippage engine
    engine_zero = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    port_zero = PortfolioTracker(initial_capital=100000.0)

    # Standard slippage engine (0.05%)
    engine_slip = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    port_slip = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    c1 = _make_candle(t1, open_price=1000.0, high_price=1010.0, low_price=990.0, close_price=1005.0)
    c2 = _make_candle(
        t2, open_price=1100.0, high_price=1110.0, low_price=1090.0, close_price=1105.0
    )

    # Execute on zero-slippage portfolio
    engine_zero.execute_order(
        OrderRequest(symbol="TCS", side=OrderSide.BUY, quantity=100, decision_time=t0),
        c1,
        port_zero,
    )
    engine_zero.execute_order(
        OrderRequest(symbol="TCS", side=OrderSide.SELL, quantity=100, decision_time=t1),
        c2,
        port_zero,
    )

    # Execute on standard-slippage portfolio
    engine_slip.execute_order(
        OrderRequest(symbol="TCS", side=OrderSide.BUY, quantity=100, decision_time=t0),
        c1,
        port_slip,
    )
    engine_slip.execute_order(
        OrderRequest(symbol="TCS", side=OrderSide.SELL, quantity=100, decision_time=t1),
        c2,
        port_slip,
    )

    state_zero = port_zero.get_state()
    state_slip = port_slip.get_state()

    # Zero-slippage baseline
    assert state_zero.total_slippage_cost == 0.0
    assert state_zero.realized_gross_pnl == 100 * (1100.0 - 1000.0)  # 10,000.0
    assert (
        state_zero.total_transaction_costs == 100000.0 * 0.0003 + 110000.0 * 0.0003
    )  # 30.0 + 33.0 = 63.0
    assert state_zero.cash == 100000.0 + 10000.0 - 63.0  # 109,937.0

    # The difference in gross PnL between 0% slippage and 0.05% slippage MUST be EXACTLY the total slippage (₹105.0)
    gross_diff = state_zero.gross_pnl - state_slip.gross_pnl
    assert gross_diff == 105.0  # Exactly 50.0 buy slippage + 55.0 sell slippage!

    # The difference in final cash is gross_diff minus slight brokerage difference on the slippage-adjusted nominals
    cash_diff = state_zero.cash - state_slip.cash
    assert round(cash_diff, 4) == 104.9985

    # DEFECT REGRESSION GUARD: Under the bug, cash_diff was 209.9985 (double slippage!)
    assert cash_diff < 150.0
