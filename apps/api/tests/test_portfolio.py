"""Targeted unit tests for Phase 5A: Deterministic Portfolio Accounting & Position Tracking."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.trading.portfolio import PortfolioTracker


def test_portfolio_tracker_initialization():
    """Verify clean initial portfolio state and capital constraints."""
    tracker = PortfolioTracker(initial_capital=100000.0)
    state = tracker.get_state()

    assert state.initial_capital == 100000.0
    assert state.cash == 100000.0
    assert state.total_market_value == 0.0
    assert state.total_portfolio_value == 100000.0
    assert state.realized_gross_pnl == 0.0
    assert state.realized_net_pnl == 0.0
    assert state.unrealized_gross_pnl == 0.0
    assert state.gross_pnl == 0.0
    assert state.net_pnl == 0.0
    assert state.total_return_pct == 0.0
    assert state.exposure_pct == 0.0
    assert state.open_positions_count == 0
    assert state.closed_trades_count == 0
    assert state.win_rate_pct == 0.0
    assert state.daily_starting_equity == 100000.0
    assert state.daily_realized_pnl == 0.0
    assert len(state.positions) == 0
    assert len(state.closed_trades) == 0

    # Negative / zero capital should raise ValueError
    with pytest.raises(ValueError, match="initial_capital must be positive"):
        PortfolioTracker(initial_capital=0.0)

    with pytest.raises(ValueError, match="initial_capital must be positive"):
        PortfolioTracker(initial_capital=-50000.0)


def test_open_single_position_and_cash_conservation():
    """Verify cash deduction and position creation when opening a long position."""
    tracker = PortfolioTracker(initial_capital=100000.0)
    now = datetime.now(timezone.utc)

    # Buy 10 shares of RELIANCE at ₹2,500 with ₹15 fee and ₹12.50 slippage
    pos = tracker.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2500.0,
        timestamp=now,
        transaction_cost=15.0,
        slippage_cost=12.50,
        stop_loss=2450.0,
        take_profit=2600.0,
    )

    assert pos.symbol == "RELIANCE"
    assert pos.quantity == 10
    assert pos.average_entry_price == 2500.0
    assert pos.current_price == 2500.0
    assert pos.market_value == 25000.0
    assert pos.unrealized_gross_pnl == 0.0
    assert pos.stop_loss == 2450.0
    assert pos.take_profit == 2600.0
    assert pos.is_open is True

    state = tracker.get_state()
    # Cash = 100,000 - (10 * 2500 + 15) = 74,985.00 (slippage metric tracked, not double-deducted)
    assert state.cash == 74985.00
    assert state.total_market_value == 25000.0
    assert state.total_portfolio_value == 99985.00
    assert state.total_transaction_costs == 15.0
    assert state.total_slippage_cost == 12.50
    assert state.gross_pnl == 0.0
    assert state.net_pnl == -15.00
    assert state.open_positions_count == 1
    assert round(state.exposure_pct, 2) == round((25000.0 / 99985.00) * 100, 2)


def test_increase_existing_position_weighted_average_entry():
    """Verify weighted average cost basis when adding to an active position."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    # 1. Buy 10 shares of TCS at ₹3,000
    tracker.open_or_increase_position(
        symbol="TCS",
        quantity=10,
        price=3000.0,
    )

    # 2. Add 10 shares of TCS at ₹3,400
    pos = tracker.open_or_increase_position(
        symbol="TCS",
        quantity=10,
        price=3400.0,
    )

    assert pos.quantity == 20
    # Weighted average = (10 * 3000 + 10 * 3400) / 20 = 3200.0
    assert pos.average_entry_price == 3200.0
    assert pos.current_price == 3400.0
    assert pos.market_value == 68000.0
    # Unrealized gross PnL = 20 * (3400 - 3200) = +4000.0
    assert pos.unrealized_gross_pnl == 4000.0
    assert pos.unrealized_pnl_pct == round(((3400 - 3200) / 3200) * 100, 4)

    state = tracker.get_state()
    assert state.unrealized_gross_pnl == 4000.0
    assert state.gross_pnl == 4000.0


def test_partial_position_exit_realized_pnl():
    """Verify partial position reduction and proportional realized P&L accounting."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    # Buy 20 shares at ₹1,000 (total ₹20,000)
    tracker.open_or_increase_position(
        symbol="INFY",
        quantity=20,
        price=1000.0,
        transaction_cost=10.0,
    )

    # Sell 10 shares at ₹1,200 with ₹10 exit fee and ₹5 exit slippage
    trade = tracker.close_or_reduce_position(
        symbol="INFY",
        quantity=10,
        price=1200.0,
        transaction_cost=10.0,
        slippage_cost=5.0,
        reason="TAKE_PROFIT_PARTIAL",
    )

    # TradeRecord checks
    assert trade.symbol == "INFY"
    assert trade.quantity == 10
    assert trade.entry_price == 1000.0
    assert trade.exit_price == 1200.0
    # Gross PnL = 10 * (1200 - 1000) = +2,000.0
    assert trade.gross_pnl == 2000.0
    # Net PnL = 2000 - 10 = 1990.0 (slippage metric tracked, not double-deducted)
    assert trade.net_pnl == 1990.0
    assert trade.exit_reason == "TAKE_PROFIT_PARTIAL"

    # Remaining position check
    rem_pos = tracker.get_position("INFY")
    assert rem_pos is not None
    assert rem_pos.quantity == 10
    assert rem_pos.average_entry_price == 1000.0
    assert rem_pos.current_price == 1200.0
    assert rem_pos.market_value == 12000.0
    assert rem_pos.unrealized_gross_pnl == 2000.0

    state = tracker.get_state()
    assert state.realized_gross_pnl == 2000.0
    assert state.realized_net_pnl == 1990.0
    assert state.closed_trades_count == 1
    assert state.open_positions_count == 1
    assert state.win_rate_pct == 100.0
    # Strengthened equity & cash conservation invariants
    assert state.total_portfolio_value == state.cash + state.total_market_value
    assert round(state.total_portfolio_value, 2) == round(state.initial_capital + state.net_pnl, 2)


def test_full_position_exit_closes_position():
    """Verify complete liquidation removes position and records trade."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    # Buy 15 shares of SBIN at ₹600 (₹9,000)
    tracker.open_or_increase_position(
        symbol="SBIN",
        quantity=15,
        price=600.0,
    )

    # Close all 15 shares at ₹580 (loss of ₹20/share = -₹300)
    trade = tracker.close_or_reduce_position(
        symbol="SBIN",
        quantity=15,
        price=580.0,
        reason="STOP_LOSS",
    )

    assert trade.gross_pnl == -300.0
    assert trade.net_pnl == -300.0
    assert trade.exit_reason == "STOP_LOSS"

    # Position should no longer exist
    assert tracker.get_position("SBIN") is None
    state = tracker.get_state()
    assert state.open_positions_count == 0
    assert state.closed_trades_count == 1
    assert state.win_rate_pct == 0.0
    assert state.realized_gross_pnl == -300.0
    assert state.total_market_value == 0.0
    assert state.cash == 100000.0 - 300.0


def test_mark_to_market_updates():
    """Verify price updates recalculate unrealized P&L and exposure metrics."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    tracker.open_or_increase_position(symbol="RELIANCE", quantity=10, price=2500.0)
    tracker.open_or_increase_position(symbol="TCS", quantity=5, price=3000.0)

    # Mark-to-market price move: RELIANCE 2500 -> 2600, TCS 3000 -> 2900
    tracker.update_all_market_prices(
        {
            "RELIANCE": 2600.0,
            "TCS": 2900.0,
        }
    )

    rel_pos = tracker.get_position("RELIANCE")
    assert rel_pos.current_price == 2600.0
    assert rel_pos.unrealized_gross_pnl == 1000.0

    tcs_pos = tracker.get_position("TCS")
    assert tcs_pos.current_price == 2900.0
    assert tcs_pos.unrealized_gross_pnl == -500.0

    state = tracker.get_state()
    assert state.total_market_value == (10 * 2600.0) + (5 * 2900.0)  # 26000 + 14500 = 40500
    assert state.unrealized_gross_pnl == 500.0  # +1000 - 500
    assert state.total_portfolio_value == state.cash + 40500.0
    # Strengthened equity & net P&L conservation during active unrealized mark-to-market
    assert state.net_pnl == state.unrealized_gross_pnl - state.total_transaction_costs
    assert round(state.total_portfolio_value, 2) == round(state.initial_capital + state.net_pnl, 2)


def test_win_rate_calculation_multiple_trades():
    """Verify accurate win rate calculation over a sequence of winning and losing trades."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    # Trade 1: Win (+₹500)
    tracker.open_or_increase_position(symbol="A", quantity=10, price=100.0)
    tracker.close_or_reduce_position(symbol="A", quantity=10, price=150.0)

    # Trade 2: Loss (-₹200)
    tracker.open_or_increase_position(symbol="B", quantity=10, price=100.0)
    tracker.close_or_reduce_position(symbol="B", quantity=10, price=80.0)

    # Trade 3: Win (+₹300)
    tracker.open_or_increase_position(symbol="C", quantity=10, price=100.0)
    tracker.close_or_reduce_position(symbol="C", quantity=10, price=130.0)

    state = tracker.get_state()
    assert state.closed_trades_count == 3
    # 2 wins out of 3 = 66.6667%
    assert round(state.win_rate_pct, 2) == 66.67


def test_daily_stats_reset():
    """Verify reset_daily_stats sets new baseline for the next trading session."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    tracker.open_or_increase_position(symbol="A", quantity=10, price=100.0)
    tracker.close_or_reduce_position(symbol="A", quantity=10, price=120.0)  # +200

    state = tracker.get_state()
    assert state.daily_realized_pnl == 200.0
    assert state.daily_starting_equity == 100000.0

    # Next trading day arrives
    tracker.reset_daily_stats()
    new_state = tracker.get_state()
    assert new_state.daily_starting_equity == 100200.0
    assert new_state.daily_realized_pnl == 0.0


def test_portfolio_tracker_boundary_conditions_and_exceptions():
    """Verify strict validation and exception handling for all invalid inputs."""
    tracker = PortfolioTracker(initial_capital=100000.0)

    # 1. Close non-existent position
    with pytest.raises(ValueError, match="No open position exists"):
        tracker.close_or_reduce_position(symbol="UNKNOWN", quantity=5, price=100.0)

    # 2. Buy with invalid quantity
    with pytest.raises(ValueError, match="quantity must be > 0"):
        tracker.open_or_increase_position(symbol="RELIANCE", quantity=0, price=2500.0)

    with pytest.raises(ValueError, match="quantity must be > 0"):
        tracker.open_or_increase_position(symbol="RELIANCE", quantity=-5, price=2500.0)

    # 3. Buy with invalid price
    with pytest.raises(ValueError, match="price must be > 0.0"):
        tracker.open_or_increase_position(symbol="RELIANCE", quantity=10, price=0.0)

    with pytest.raises(ValueError, match="price must be > 0.0"):
        tracker.open_or_increase_position(symbol="RELIANCE", quantity=10, price=-100.0)

    # 4. Open position then try to close more than open quantity
    tracker.open_or_increase_position(symbol="RELIANCE", quantity=10, price=2500.0)
    with pytest.raises(ValueError, match="only 10 units open"):
        tracker.close_or_reduce_position(symbol="RELIANCE", quantity=15, price=2600.0)

    # 5. Invalid negative fees or slippage
    with pytest.raises(ValueError, match="transaction_cost cannot be negative"):
        tracker.open_or_increase_position(
            symbol="TCS", quantity=5, price=3000.0, transaction_cost=-10.0
        )

    with pytest.raises(ValueError, match="slippage_cost cannot be negative"):
        tracker.open_or_increase_position(
            symbol="TCS", quantity=5, price=3000.0, slippage_cost=-5.0
        )

    # 6. Update price with <= 0 price
    with pytest.raises(ValueError, match="current_price must be > 0.0"):
        tracker.update_market_price("RELIANCE", 0.0)
