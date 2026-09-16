"""Cross-component trading flows and adversarial lifecycle tests (Phase 5E).

Verifies end-to-end integration across:
- Phase 5C: RiskEngine (position sizing and pre-trade risk validation)
- Phase 5B: ExecutionEngine (next-candle execution, directional slippage, transaction costs)
- Phase 5A: PortfolioTracker (cash, positions, P&L accounting, conservation invariants)
- Phase 5D: TriggerMonitor (completed-candle SL/TP auto-triggers, deduplication, symbol isolation)
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import (
    ExecutionConfig,
    OrderRequest,
    OrderSide,
    OrderStatus,
    RiskConfig,
)
from app.trading.triggers import (
    EXIT_REASON_STOP_LOSS,
    EXIT_REASON_TAKE_PROFIT,
    TriggerMonitor,
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


def test_full_lifecycle_risk_execution_autotrigger_portfolio_flow():
    """Verify complete lifecycle across all Phase 5 components:

    Propose -> Size -> Validate -> Buy Fill -> Track -> Auto-Trigger TP -> Sell Fill -> Reconcile.
    """
    exec_config = ExecutionConfig(
        slippage_pct=0.0005,  # 0.05%
        brokerage_rate=0.0003,  # 0.03%
        fixed_fee_per_order=10.0,  # ₹10.0
    )
    risk_config = RiskConfig(
        max_risk_per_trade=0.02,  # 2% of equity
        max_position_exposure=0.25,  # 25% of equity
        max_daily_loss=0.05,  # 5%
    )

    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine(config=risk_config, execution_config=exec_config)
    exec_engine = ExecutionEngine(config=exec_config)
    trigger_monitor = TriggerMonitor(execution_engine=exec_engine)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)

    # ------------------------------------------------------------------
    # Step 1: Strategy proposes BUY of RELIANCE with SL and TP
    # ------------------------------------------------------------------
    market_price = 2000.0
    stop_loss = 1900.0
    take_profit = 2200.0

    # Phase 5C Sizing:
    # Capital = 100,000. Risk budget = 2,000. Per share risk = 2000 - 1900 = 100.
    # Qty by risk = 2,000 // 100 = 20 shares.
    # Exposure budget = 25,000. Approx per share = 2001. Qty by exposure = 25,000 // 2001 = 12 shares.
    # Cash budget allows 12 shares. Sized quantity = 12 shares.
    sized_qty = risk_engine.calculate_position_size(
        symbol="RELIANCE",
        price=market_price,
        stop_loss=stop_loss,
        portfolio=portfolio,
    )
    assert sized_qty == 12

    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=sized_qty,
        decision_time=t0,
        decision_price=market_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    # Phase 5C Pre-Trade Risk Check:
    risk_check = risk_engine.validate_order(order, portfolio)
    assert risk_check.approved

    # ------------------------------------------------------------------
    # Step 2: Phase 5B Execution at next candle t1 OPEN
    # ------------------------------------------------------------------
    candle_t1 = _make_candle(
        t1, open_price=2000.0, high_price=2050.0, low_price=1995.0, close_price=2040.0
    )
    buy_result = exec_engine.execute_order(order, candle_t1, portfolio)
    assert buy_result.status == OrderStatus.FILLED

    # Buy fill: 2000.0 * 1.0005 = 2001.00
    assert buy_result.execution_price == 2001.00
    # Nominal: 12 * 2001.00 = 24012.00
    # Fee: 24012.00 * 0.0003 + 10.0 = 7.2036 + 10.0 = 17.2036
    assert buy_result.transaction_cost == 17.2036
    # Buy slippage cost: 12 * 1.0 = 12.00
    assert buy_result.slippage_cost == 12.00

    # Phase 5A Portfolio check:
    pos = portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 12
    assert pos.average_entry_price == 2001.00
    # Cash = 100,000 - 24012.00 - 17.2036 = 75970.7964
    assert round(portfolio.cash, 4) == 75970.7964

    # ------------------------------------------------------------------
    # Step 3: Candle t2 arrives and triggers Take-Profit (High = 2220.0 >= 2200.0)
    # ------------------------------------------------------------------
    candle_t2 = _make_candle(
        t2, open_price=2050.0, high_price=2220.0, low_price=2045.0, close_price=2210.0
    )
    execs_t2, queued_t2 = trigger_monitor.process_simulation_cycle(
        candle_t2, portfolio, symbol="RELIANCE"
    )
    assert len(execs_t2) == 0  # No prior pending exits
    assert len(queued_t2) == 1  # TP exit queued for t3

    exit_order = queued_t2[0]
    assert exit_order.symbol == "RELIANCE"
    assert exit_order.side == OrderSide.SELL
    assert exit_order.quantity == 12
    assert exit_order.reason == EXIT_REASON_TAKE_PROFIT
    assert exit_order.decision_price == 2200.0  # Metadata threshold
    assert trigger_monitor.is_exit_pending("RELIANCE")

    # Position remains open in portfolio pending t3 open execution
    assert portfolio.get_position("RELIANCE") is not None

    # ------------------------------------------------------------------
    # Step 4: Candle t3 arrives, executing the exit at OPEN (2215.0)
    # ------------------------------------------------------------------
    candle_t3 = _make_candle(
        t3, open_price=2215.0, high_price=2230.0, low_price=2200.0, close_price=2225.0
    )
    execs_t3, queued_t3 = trigger_monitor.process_simulation_cycle(
        candle_t3, portfolio, symbol="RELIANCE"
    )
    assert len(execs_t3) == 1
    assert len(queued_t3) == 0  # Position is now closed
    assert not trigger_monitor.is_exit_pending("RELIANCE")

    sell_result = execs_t3[0]
    assert sell_result.status == OrderStatus.FILLED
    # Sell fill: 2215.0 * (1 - 0.0005) = 2213.8925
    assert sell_result.execution_price == 2213.8925
    # Nominal: 12 * 2213.8925 = 26566.71
    # Fee: 26566.71 * 0.0003 + 10.0 = 7.970013 + 10.0 = 17.97
    assert sell_result.transaction_cost == 17.97
    # Sell slippage cost: 12 * (2215.0 - 2213.8925) = 13.29
    assert sell_result.slippage_cost == 13.29

    # ------------------------------------------------------------------
    # Step 5: Full Invariant & Financial Reconciliation
    # ------------------------------------------------------------------
    state = portfolio.get_state()
    assert state.open_positions_count == 0
    assert state.closed_trades_count == 1
    assert state.win_rate_pct == 100.0

    trade = state.closed_trades[0]
    assert trade.exit_reason == EXIT_REASON_TAKE_PROFIT
    assert trade.quantity == 12
    assert trade.entry_price == 2001.00
    assert trade.exit_price == 2213.8925
    # Gross PnL: 12 * (2213.8925 - 2001.00) = 12 * 212.8925 = 2554.71
    assert trade.gross_pnl == 2554.71
    # Net PnL on trade: 2554.71 - 17.97 (exit fee) = 2536.74
    assert trade.net_pnl == 2536.74

    # Portfolio totals:
    # Total fees: 17.2036 + 17.97 = 35.1736
    assert state.total_transaction_costs == 35.1736
    # Total slippage: 12.00 + 13.29 = 25.29 (metric tracked, not double-deducted)
    assert state.total_slippage_cost == 25.29
    # Portfolio Net PnL = Gross (2554.71) - Total fees (35.1736) = 2519.5364
    assert round(state.net_pnl, 4) == 2519.5364
    # Final cash = Initial (100,000) + Net PnL (2519.5364) = 102519.5364
    assert round(state.cash, 4) == 102519.5364
    assert round(state.total_portfolio_value, 4) == round(state.cash, 4)

    # Exact Conservation Invariants:
    assert state.total_portfolio_value == round(state.initial_capital + state.net_pnl, 4)
    assert state.total_portfolio_value == round(state.cash + state.total_market_value, 4)


def test_partial_manual_exit_followed_by_autotrigger_on_remaining_quantity():
    """Verify that a position partially reduced by a manual order has only its REMAINING

    quantity liquidated when a subsequent Stop-Loss auto-trigger occurs.
    """
    exec_engine = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    trigger_monitor = TriggerMonitor(execution_engine=exec_engine)
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)

    # 1. Open long position of 20 shares @ 1000.0 with SL = 950.0
    portfolio.open_or_increase_position(
        symbol="TCS",
        quantity=20,
        price=1000.0,
        timestamp=t0,
        stop_loss=950.0,
        take_profit=1150.0,
    )
    assert portfolio.get_position("TCS").quantity == 20

    # 2. Manual partial exit of 10 shares @ 1050.0
    partial_trade = portfolio.close_or_reduce_position(
        symbol="TCS",
        quantity=10,
        price=1050.0,
        timestamp=t1,
        reason="MANUAL_PARTIAL_EXIT",
    )
    assert partial_trade.quantity == 10
    assert partial_trade.gross_pnl == 10 * (1050.0 - 1000.0)  # +500.0
    assert portfolio.get_position("TCS").quantity == 10  # 10 shares remain

    # 3. Market drops on candle t2: Low is 940.0 (touches SL 950.0)
    candle_t2 = _make_candle(
        t2, open_price=980.0, high_price=985.0, low_price=940.0, close_price=945.0
    )
    execs_t2, queued_t2 = trigger_monitor.process_simulation_cycle(
        candle_t2, portfolio, symbol="TCS"
    )
    assert len(execs_t2) == 0
    assert len(queued_t2) == 1

    auto_exit_order = queued_t2[0]
    # CRITICAL: Auto-trigger must size exit order to the REMAINING quantity (10 shares), not the original 20!
    assert auto_exit_order.quantity == 10
    assert auto_exit_order.reason == EXIT_REASON_STOP_LOSS

    # 4. Candle t3 arrives with open 935.0 -> executes remaining 10 shares
    candle_t3 = _make_candle(
        t3, open_price=935.0, high_price=945.0, low_price=930.0, close_price=940.0
    )
    execs_t3, queued_t3 = trigger_monitor.process_simulation_cycle(
        candle_t3, portfolio, symbol="TCS"
    )
    assert len(execs_t3) == 1
    assert len(queued_t3) == 0

    res = execs_t3[0]
    assert res.status == OrderStatus.FILLED
    assert res.quantity == 10

    # 5. Position is fully closed
    assert portfolio.get_position("TCS") is None
    state = portfolio.get_state()
    assert state.open_positions_count == 0
    assert state.closed_trades_count == 2

    # Trades: Trade 1 = Manual partial (+500), Trade 2 = SL auto exit (negative)
    trades = state.closed_trades
    assert trades[0].exit_reason == "MANUAL_PARTIAL_EXIT"
    assert trades[1].exit_reason == EXIT_REASON_STOP_LOSS

    # Full cash conservation invariant
    assert state.total_portfolio_value == state.cash
    assert round(state.total_portfolio_value, 2) == round(state.initial_capital + state.net_pnl, 2)


def test_rejected_orders_produce_zero_side_effects_on_state():
    """Verify that orders rejected by RiskEngine, ExecutionEngine, or TriggerMonitor

    leave portfolio cash, positions, and pending queues completely unmutated.
    """
    exec_engine = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003)
    )
    risk_engine = RiskEngine(
        config=RiskConfig(max_daily_loss=0.05),
        execution_config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003),
    )
    trigger_monitor = TriggerMonitor(execution_engine=exec_engine)
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # 1. RiskEngine Rejection: BUY order exceeding available cash
    order_huge = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=1000,
        decision_time=t0,
        decision_price=2000.0,
    )
    risk_res = risk_engine.validate_order(order_huge, portfolio)
    assert not risk_res.approved

    # Portfolio state must be 100% identical to initial
    assert portfolio.cash == 100000.0
    assert portfolio.get_state().open_positions_count == 0
    assert portfolio.get_state().net_pnl == 0.0

    # 2. ExecutionEngine Rejection: Next candle timestamp <= decision timestamp (lookahead check)
    candle_stale = _make_candle(
        t0, open_price=2000.0, high_price=2010.0, low_price=1990.0, close_price=2000.0
    )
    valid_order = OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, quantity=10, decision_time=t0, decision_price=2000.0
    )
    exec_res = exec_engine.execute_order(valid_order, candle_stale, portfolio)
    assert exec_res.status == OrderStatus.REJECTED

    # Portfolio state still untouched
    assert portfolio.cash == 100000.0
    assert portfolio.get_state().open_positions_count == 0

    # 3. ExecutionEngine Rejection: SELL without an open position
    sell_order = OrderRequest(
        symbol="RELIANCE", side=OrderSide.SELL, quantity=10, decision_time=t0, decision_price=2000.0
    )
    candle_next = _make_candle(
        t1, open_price=2000.0, high_price=2010.0, low_price=1990.0, close_price=2000.0
    )
    exec_res_sell = exec_engine.execute_order(sell_order, candle_next, portfolio)
    assert exec_res_sell.status == OrderStatus.REJECTED

    assert portfolio.cash == 100000.0
    assert portfolio.get_state().closed_trades_count == 0

    # 4. TriggerMonitor End-of-Series Rejection (next candle is None)
    # Open valid position first
    portfolio.open_or_increase_position(
        symbol="TEST", quantity=5, price=100.0, timestamp=t0, stop_loss=90.0
    )
    cash_after_buy = portfolio.cash

    # Candle triggers SL
    candle_sl = _make_candle(t1, open_price=95.0, high_price=96.0, low_price=85.0, close_price=88.0)
    trigger_monitor.evaluate_completed_candle(candle_sl, portfolio, symbol="TEST")
    assert trigger_monitor.is_exit_pending("TEST")

    # Execute against None (end of series)
    end_of_series_results = trigger_monitor.execute_pending_exits(None, portfolio, symbol="TEST")
    assert len(end_of_series_results) == 1
    assert end_of_series_results[0].status == OrderStatus.REJECTED

    # Position is NOT improperly liquidated; cash is NOT mutated
    assert portfolio.get_position("TEST") is not None
    assert portfolio.get_position("TEST").quantity == 5
    assert portfolio.cash == cash_after_buy


def test_multi_position_portfolio_interleaved_lifecycle_accounting():
    """Verify multi-position simulation with concurrent positions, independent SL and TP

    triggers on separate candles, and exact win rate / cash reconciliation.
    """
    exec_engine = ExecutionEngine(
        config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=0.0)
    )
    trigger_monitor = TriggerMonitor(execution_engine=exec_engine)
    portfolio = PortfolioTracker(initial_capital=200000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 15, 9, 45, tzinfo=timezone.utc)

    # 1. Open Position A (INFY: Entry 1000.0, SL 950.0, TP 1100.0, Qty 20)
    portfolio.open_or_increase_position(
        symbol="INFY",
        quantity=20,
        price=1000.0,
        timestamp=t0,
        stop_loss=950.0,
        take_profit=1100.0,
    )
    # 2. Open Position B (SBIN: Entry 500.0, SL 480.0, TP 550.0, Qty 40)
    portfolio.open_or_increase_position(
        symbol="SBIN",
        quantity=40,
        price=500.0,
        timestamp=t0,
        stop_loss=480.0,
        take_profit=550.0,
    )
    assert portfolio.get_state().open_positions_count == 2

    # 3. Candle t1:
    # INFY touches Take-Profit (High = 1110.0 >= 1100.0)
    c_infy_t1 = _make_candle(
        t1, open_price=1050.0, high_price=1110.0, low_price=1040.0, close_price=1105.0
    )
    trigger_monitor.evaluate_completed_candle(c_infy_t1, portfolio, symbol="INFY")

    # SBIN touches Stop-Loss (Low = 475.0 <= 480.0)
    c_sbin_t1 = _make_candle(
        t1, open_price=490.0, high_price=495.0, low_price=475.0, close_price=478.0
    )
    trigger_monitor.evaluate_completed_candle(c_sbin_t1, portfolio, symbol="SBIN")

    assert trigger_monitor.get_pending_symbols() == {"INFY", "SBIN"}

    # 4. Candle t2:
    # INFY executes TP at Open 1105.0
    c_infy_t2 = _make_candle(
        t2, open_price=1105.0, high_price=1115.0, low_price=1100.0, close_price=1110.0
    )
    execs_infy, _ = trigger_monitor.process_simulation_cycle(c_infy_t2, portfolio, symbol="INFY")
    assert len(execs_infy) == 1
    assert execs_infy[0].status == OrderStatus.FILLED
    assert execs_infy[0].trade_record.exit_reason == EXIT_REASON_TAKE_PROFIT

    # SBIN executes SL at Open 476.0
    c_sbin_t2 = _make_candle(
        t2, open_price=476.0, high_price=480.0, low_price=472.0, close_price=475.0
    )
    execs_sbin, _ = trigger_monitor.process_simulation_cycle(c_sbin_t2, portfolio, symbol="SBIN")
    assert len(execs_sbin) == 1
    assert execs_sbin[0].status == OrderStatus.FILLED
    assert execs_sbin[0].trade_record.exit_reason == EXIT_REASON_STOP_LOSS

    # 5. Reconcile complete portfolio state
    state = portfolio.get_state()
    assert state.open_positions_count == 0
    assert state.closed_trades_count == 2
    # 1 Winning trade (INFY) and 1 Losing trade (SBIN) -> 50% win rate
    assert state.win_rate_pct == 50.0

    # Invariant: Equity == Cash == Initial Capital + Net P&L
    assert state.total_portfolio_value == state.cash
    assert round(state.total_portfolio_value, 2) == round(state.initial_capital + state.net_pnl, 2)
