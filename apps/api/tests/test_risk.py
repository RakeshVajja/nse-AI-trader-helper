"""Targeted unit tests for Phase 5C: Deterministic Risk Engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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


@pytest.fixture
def clean_portfolio() -> PortfolioTracker:
    """Fresh portfolio with standard initial capital ₹1,00,000."""
    return PortfolioTracker(initial_capital=100000.0)


@pytest.fixture
def risk_engine() -> RiskEngine:
    """Standard RiskEngine with default 2% risk/trade, 25% pos exposure, 5% daily loss."""
    return RiskEngine(
        config=RiskConfig(
            max_risk_per_trade=0.02,
            max_position_exposure=0.25,
            max_portfolio_exposure=1.00,
            max_daily_loss=0.05,
        ),
        execution_config=ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003),
    )


# =====================================================================
# 1. Order Validity Tests
# =====================================================================


def test_order_validity_invalid_symbol_or_price(
    risk_engine: RiskEngine, clean_portfolio: PortfolioTracker
):
    """Verify orders with empty symbols or invalid prices are rejected."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. Empty symbol
    order_empty_sym = OrderRequest(
        symbol="", side=OrderSide.BUY, quantity=10, decision_time=t0, decision_price=1000.0
    )
    res = risk_engine.validate_order(order_empty_sym, clean_portfolio)
    assert not res.approved
    assert "symbol cannot be empty" in (res.rejection_reason or "")

    # 2. Zero price
    order_zero_px = OrderRequest(
        symbol="TCS", side=OrderSide.BUY, quantity=10, decision_time=t0, decision_price=0.0
    )
    res2 = risk_engine.validate_order(order_zero_px, clean_portfolio)
    assert not res2.approved
    assert "Valid positive reference price required" in (res2.rejection_reason or "")

    # 3. Negative price
    order_neg_px = OrderRequest(
        symbol="TCS", side=OrderSide.BUY, quantity=10, decision_time=t0, decision_price=-500.0
    )
    res3 = risk_engine.validate_order(order_neg_px, clean_portfolio)
    assert not res3.approved
    assert "Valid positive reference price required" in (res3.rejection_reason or "")


def test_order_validity_quantity_bounds(
    clean_portfolio: PortfolioTracker,
):
    """Verify order quantity constraints including min/max ceilings."""
    engine = RiskEngine(
        config=RiskConfig(min_order_quantity=5, max_order_quantity=100),
        execution_config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0),
    )
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. Below min quantity (4 < 5)
    order_low = OrderRequest(
        symbol="SBIN", side=OrderSide.BUY, quantity=4, decision_time=t0, decision_price=500.0
    )
    res_low = engine.validate_order(order_low, clean_portfolio)
    assert not res_low.approved
    assert "below minimum allowed quantity" in (res_low.rejection_reason or "")

    # 2. Exactly min quantity (5 == 5) -> passes
    order_min = OrderRequest(
        symbol="SBIN", side=OrderSide.BUY, quantity=5, decision_time=t0, decision_price=500.0
    )
    res_min = engine.validate_order(order_min, clean_portfolio)
    assert res_min.approved

    # 3. Above max ceiling (101 > 100)
    order_high = OrderRequest(
        symbol="SBIN", side=OrderSide.BUY, quantity=101, decision_time=t0, decision_price=100.0
    )
    res_high = engine.validate_order(order_high, clean_portfolio)
    assert not res_high.approved
    assert "exceeds maximum allowed single order quantity ceiling" in (
        res_high.rejection_reason or ""
    )


def test_sell_order_validity_and_position_sufficiency(
    risk_engine: RiskEngine, clean_portfolio: PortfolioTracker
):
    """Verify SELL orders require an active open position and cannot exceed open quantity."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. SELL when no position exists -> REJECTED
    sell_no_pos = OrderRequest(
        symbol="RELIANCE", side=OrderSide.SELL, quantity=10, decision_time=t0, decision_price=2500.0
    )
    res_no_pos = risk_engine.validate_order(sell_no_pos, clean_portfolio)
    assert not res_no_pos.approved
    assert "No open position exists" in (res_no_pos.rejection_reason or "")

    # Open position of 10 shares
    clean_portfolio.open_or_increase_position(
        symbol="RELIANCE", quantity=10, price=2500.0, timestamp=t0
    )

    # 2. SELL quantity > open position quantity (15 > 10) -> REJECTED
    sell_excess = OrderRequest(
        symbol="RELIANCE", side=OrderSide.SELL, quantity=15, decision_time=t0, decision_price=2500.0
    )
    res_excess = risk_engine.validate_order(sell_excess, clean_portfolio)
    assert not res_excess.approved
    assert "exceeds open position quantity" in (res_excess.rejection_reason or "")

    # 3. Partial SELL (5 <= 10) -> APPROVED
    sell_partial = OrderRequest(
        symbol="RELIANCE", side=OrderSide.SELL, quantity=5, decision_time=t0, decision_price=2600.0
    )
    res_partial = risk_engine.validate_order(sell_partial, clean_portfolio)
    assert res_partial.approved
    assert res_partial.risk_metrics["remaining_quantity_after_sell"] == 5.0

    # 4. Full SELL (10 == 10) -> APPROVED
    sell_full = OrderRequest(
        symbol="RELIANCE", side=OrderSide.SELL, quantity=10, decision_time=t0, decision_price=2600.0
    )
    res_full = risk_engine.validate_order(sell_full, clean_portfolio)
    assert res_full.approved
    assert res_full.risk_metrics["remaining_quantity_after_sell"] == 0.0


# =====================================================================
# 2. Available Cash Sufficiency Tests
# =====================================================================


def test_available_cash_rejection_and_boundary():
    """Verify available cash check accounts for slippage and transaction costs precisely."""
    # Zero slippage and zero fees for clear boundary testing
    engine = RiskEngine(
        config=RiskConfig(max_position_exposure=1.0),
        execution_config=ExecutionConfig(
            slippage_pct=0.0, brokerage_rate=0.0, fixed_fee_per_order=0.0
        ),
    )
    portfolio = PortfolioTracker(initial_capital=50000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. Cash required exceeds available cash (50 shares @ 1001.0 = 50,050 > 50,000) -> REJECTED
    order_fail = OrderRequest(
        symbol="TCS", side=OrderSide.BUY, quantity=50, decision_time=t0, decision_price=1001.0
    )
    res_fail = engine.validate_order(order_fail, portfolio)
    assert not res_fail.approved
    assert "Insufficient available cash" in (res_fail.rejection_reason or "")
    assert res_fail.risk_metrics["cash_required"] == 50050.0

    # 2. Cash required exactly equal to available cash (50 shares @ 1000.0 = 50,000 == 50,000) -> APPROVED
    order_exact = OrderRequest(
        symbol="TCS", side=OrderSide.BUY, quantity=50, decision_time=t0, decision_price=1000.0
    )
    res_exact = engine.validate_order(order_exact, portfolio)
    assert res_exact.approved
    assert res_exact.risk_metrics["cash_required"] == 50000.0


def test_available_cash_incorporates_slippage_and_brokerage():
    """Verify cash required accounts for estimated fill price with slippage and transaction fee."""
    engine = RiskEngine(
        config=RiskConfig(max_position_exposure=1.0),
        execution_config=ExecutionConfig(
            slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=10.0
        ),
    )
    # Available cash = ₹1,00,000
    portfolio = PortfolioTracker(initial_capital=100000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 100 units at raw market price 999.0:
    # est_fill_price = 999.0 * 1.0005 = 999.4995 -> 999.50
    # nominal = 100 * 999.50 = 99,950.0
    # fee = 99,950.0 * 0.0003 + 10.0 = 29.985 + 10.0 = 39.985 -> 39.99
    # total cash required = 99,950.0 + 39.99 = 99,989.99 <= 100,000 -> APPROVED
    order_ok = OrderRequest(
        symbol="INFY", side=OrderSide.BUY, quantity=100, decision_time=t0, decision_price=999.0
    )
    res_ok = engine.validate_order(order_ok, portfolio)
    assert res_ok.approved
    assert res_ok.risk_metrics["cash_required"] < 100000.0

    # 100 units at raw market price 1000.0:
    # est_fill_price = 1000.50, nominal = 100,050.0 > 100,000 -> REJECTED
    order_exceed = OrderRequest(
        symbol="INFY", side=OrderSide.BUY, quantity=100, decision_time=t0, decision_price=1000.0
    )
    res_exceed = engine.validate_order(order_exceed, portfolio)
    assert not res_exceed.approved
    assert "Insufficient available cash" in (res_exceed.rejection_reason or "")


# =====================================================================
# 3. Stop-Loss & Take-Profit Validity Tests
# =====================================================================


def test_stop_loss_validity_for_buy_orders(
    risk_engine: RiskEngine, clean_portfolio: PortfolioTracker
):
    """Verify stop-loss price logic: must be > 0 and strictly below entry price."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. Negative SL -> REJECTED
    order_neg_sl = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        stop_loss=-100.0,
    )
    res1 = risk_engine.validate_order(order_neg_sl, clean_portfolio)
    assert not res1.approved
    assert "Stop loss must be strictly positive" in (res1.rejection_reason or "")

    # 2. Zero SL -> REJECTED
    order_zero_sl = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        stop_loss=0.0,
    )
    res2 = risk_engine.validate_order(order_zero_sl, clean_portfolio)
    assert not res2.approved
    assert "Stop loss must be strictly positive" in (res2.rejection_reason or "")

    # 3. SL equal to entry price (2500 == 2500) -> REJECTED
    order_eq_sl = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        stop_loss=2500.0,
    )
    res3 = risk_engine.validate_order(order_eq_sl, clean_portfolio)
    assert not res3.approved
    assert "must be strictly below entry price" in (res3.rejection_reason or "")

    # 4. SL above entry price (2550 > 2500) -> REJECTED
    order_high_sl = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        stop_loss=2550.0,
    )
    res4 = risk_engine.validate_order(order_high_sl, clean_portfolio)
    assert not res4.approved
    assert "must be strictly below entry price" in (res4.rejection_reason or "")

    # 5. Valid SL (2450 < 2500) -> APPROVED
    order_valid_sl = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        stop_loss=2450.0,
    )
    res5 = risk_engine.validate_order(order_valid_sl, clean_portfolio)
    assert res5.approved


def test_take_profit_validity_for_buy_orders(
    risk_engine: RiskEngine, clean_portfolio: PortfolioTracker
):
    """Verify take-profit price logic: must be > 0, > entry, and > SL."""
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. TP below entry price (2400 < 2500) -> REJECTED
    order_low_tp = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        take_profit=2400.0,
    )
    res1 = risk_engine.validate_order(order_low_tp, clean_portfolio)
    assert not res1.approved
    assert "must be strictly above entry price" in (res1.rejection_reason or "")

    # 2. TP equal to entry price (2500 == 2500) -> REJECTED
    order_eq_tp = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        take_profit=2500.0,
    )
    res2 = risk_engine.validate_order(order_eq_tp, clean_portfolio)
    assert not res2.approved
    assert "must be strictly above entry price" in (res2.rejection_reason or "")

    # 3. Valid TP (2600 > 2500) -> APPROVED
    order_ok = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=2500.0,
        take_profit=2600.0,
    )
    assert risk_engine.validate_order(order_ok, clean_portfolio).approved


def test_mandatory_stop_loss_configuration(clean_portfolio: PortfolioTracker):
    """Verify require_stop_loss config flag rejects BUY orders missing SL."""
    engine = RiskEngine(config=RiskConfig(require_stop_loss=True))
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Missing SL -> REJECTED
    order_no_sl = OrderRequest(
        symbol="TCS", side=OrderSide.BUY, quantity=5, decision_time=t0, decision_price=3000.0
    )
    res = engine.validate_order(order_no_sl, clean_portfolio)
    assert not res.approved
    assert "Stop loss is mandatory" in (res.rejection_reason or "")

    # With SL -> APPROVED
    order_with_sl = OrderRequest(
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=5,
        decision_time=t0,
        decision_price=3000.0,
        stop_loss=2950.0,
    )
    assert engine.validate_order(order_with_sl, clean_portfolio).approved


# =====================================================================
# 4. Maximum Risk Per Trade (2%) Tests
# =====================================================================


def test_max_risk_per_trade_boundary_reconciliation():
    """Verify max risk per trade limit (2% of equity = ₹2,000 on ₹1,00,000)."""
    # 0 slippage for exact boundary math
    engine = RiskEngine(
        config=RiskConfig(max_risk_per_trade=0.02, max_position_exposure=0.50),
        execution_config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0),
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Entry = 1000.0, SL = 900.0 (Risk per share = ₹100.0)
    # 1. Exactly 20 shares: Trade Risk = 20 * 100 = ₹2,000 == 2% of ₹1,00,000 -> APPROVED
    order_boundary = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=20,
        decision_time=t0,
        decision_price=1000.0,
        stop_loss=900.0,
    )
    res_boundary = engine.validate_order(order_boundary, portfolio)
    assert res_boundary.approved
    assert res_boundary.risk_metrics["trade_risk"] == 2000.0
    assert res_boundary.risk_metrics["max_allowed_risk"] == 2000.0

    # 2. 21 shares: Trade Risk = 21 * 100 = ₹2,100 > ₹2,000 (2.1% > 2.0%) -> REJECTED
    order_exceed = OrderRequest(
        symbol="INFY",
        side=OrderSide.BUY,
        quantity=21,
        decision_time=t0,
        decision_price=1000.0,
        stop_loss=900.0,
    )
    res_exceed = engine.validate_order(order_exceed, portfolio)
    assert not res_exceed.approved
    assert "exceeds maximum allowed risk per trade" in (res_exceed.rejection_reason or "")
    assert res_exceed.risk_metrics["trade_risk"] == 2100.0


# =====================================================================
# 5. Maximum Position Exposure (25%) & Scaling Tests
# =====================================================================


def test_max_position_exposure_boundary_and_scaling_prevention():
    """Verify max position exposure (25% = ₹25,000 on ₹1,00,000) prevents scaling bypass."""
    engine = RiskEngine(
        config=RiskConfig(max_position_exposure=0.25),
        execution_config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0),
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Entry price = 1000.0
    # 1. Exactly 25 shares (value = 25 * 1000 = ₹25,000 == 25% of ₹1,00,000) -> APPROVED
    order_25 = OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, quantity=25, decision_time=t0, decision_price=1000.0
    )
    assert engine.validate_order(order_25, portfolio).approved

    # 2. 26 shares (value = 26 * 1000 = ₹26,000 > ₹25,000) -> REJECTED
    order_26 = OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, quantity=26, decision_time=t0, decision_price=1000.0
    )
    res_26 = engine.validate_order(order_26, portfolio)
    assert not res_26.approved
    assert "exceeding maximum allowed position exposure" in (res_26.rejection_reason or "")

    # 3. Scaling: open 15 shares first
    portfolio.open_or_increase_position(symbol="RELIANCE", quantity=15, price=1000.0, timestamp=t0)
    assert portfolio.get_position("RELIANCE").quantity == 15

    # 4. Try adding 11 shares (15 + 11 = 26 shares = ₹26,000 > 25%) -> REJECTED
    order_add_11 = OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, quantity=11, decision_time=t0, decision_price=1000.0
    )
    res_add_11 = engine.validate_order(order_add_11, portfolio)
    assert not res_add_11.approved
    assert "exceeding maximum allowed position exposure" in (res_add_11.rejection_reason or "")

    # 5. Add 10 shares (15 + 10 = 25 shares = ₹25,000 == 25%) -> APPROVED
    order_add_10 = OrderRequest(
        symbol="RELIANCE", side=OrderSide.BUY, quantity=10, decision_time=t0, decision_price=1000.0
    )
    assert engine.validate_order(order_add_10, portfolio).approved


# =====================================================================
# 6. Maximum Portfolio Exposure Tests
# =====================================================================


def test_max_portfolio_exposure_across_multiple_symbols():
    """Verify aggregate portfolio exposure across all open positions cannot exceed limit."""
    engine = RiskEngine(
        config=RiskConfig(max_position_exposure=0.50, max_portfolio_exposure=0.60),
        execution_config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0),
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. Open 30 shares of A @ 1000 (₹30,000 = 30% exposure)
    portfolio.open_or_increase_position(symbol="A", quantity=30, price=1000.0, timestamp=t0)

    # 2. Open 20 shares of B @ 1000 (₹20,000 = 20% exposure, total 50% <= 60%)
    portfolio.open_or_increase_position(symbol="B", quantity=20, price=1000.0, timestamp=t0)
    assert portfolio.get_state().exposure_pct == 50.0

    # 3. Attempt to buy 15 shares of C @ 1000 (₹15,000 -> new total 65,000 = 65% > 60%) -> REJECTED
    order_c_fail = OrderRequest(
        symbol="C", side=OrderSide.BUY, quantity=15, decision_time=t0, decision_price=1000.0
    )
    res_c_fail = engine.validate_order(order_c_fail, portfolio)
    assert not res_c_fail.approved
    assert "exceeding maximum allowed portfolio exposure" in (res_c_fail.rejection_reason or "")

    # 4. Buy 10 shares of C @ 1000 (₹10,000 -> new total 60,000 == 60% <= 60%) -> APPROVED
    order_c_ok = OrderRequest(
        symbol="C", side=OrderSide.BUY, quantity=10, decision_time=t0, decision_price=1000.0
    )
    assert engine.validate_order(order_c_ok, portfolio).approved


# =====================================================================
# 7. Maximum Daily Loss Limit (5%) Tests
# =====================================================================


def test_max_daily_loss_limit_halts_buy_orders_but_permits_sells():
    """Verify that breaching the 5% daily loss limit halts BUY orders while permitting SELLs."""
    engine = RiskEngine(
        config=RiskConfig(max_daily_loss=0.05),
        execution_config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0),
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Daily starting equity = ₹1,00,000. Max allowed daily loss = 5% = ₹5,000.
    # Buy 20 shares of TCS @ 3000 (₹60,000)
    portfolio.open_or_increase_position(symbol="TCS", quantity=20, price=3000.0, timestamp=t0)

    # Mark-to-market drop: TCS 3000 -> 2750 (Loss of 20 * 250 = ₹5,000 == exactly 5%)
    portfolio.update_market_price("TCS", 2750.0, timestamp=t0)
    assert portfolio.get_state().total_portfolio_value == 95000.0

    # At exactly 5% loss (₹5,000 <= ₹5,000), boundary holds -> BUY is allowed
    order_buy_limit = OrderRequest(
        symbol="INFY", side=OrderSide.BUY, quantity=5, decision_time=t0, decision_price=1000.0
    )
    assert engine.validate_order(order_buy_limit, portfolio).approved

    # Mark-to-market drops further: TCS 2750 -> 2740 (Loss of 20 * 260 = ₹5,200 > ₹5,000 = 5.2% > 5%)
    portfolio.update_market_price("TCS", 2740.0, timestamp=t0)
    assert portfolio.get_state().total_portfolio_value == 94800.0

    # 1. New BUY order is strictly REJECTED (daily loss limit breached)
    res_buy_halted = engine.validate_order(order_buy_limit, portfolio)
    assert not res_buy_halted.approved
    assert "Maximum daily loss limit breached" in (res_buy_halted.rejection_reason or "")
    assert "New BUY orders are halted" in (res_buy_halted.rejection_reason or "")

    # 2. SELL order to liquidate or reduce the losing TCS position is APPROVED (cuts risk)
    order_sell_tcs = OrderRequest(
        symbol="TCS", side=OrderSide.SELL, quantity=20, decision_time=t0, decision_price=2740.0
    )
    res_sell = engine.validate_order(order_sell_tcs, portfolio)
    assert res_sell.approved
    assert res_sell.side == OrderSide.SELL

    # 3. Strengthened assertion: Liquidate position to cash -> loss becomes REALIZED
    portfolio.close_or_reduce_position(symbol="TCS", quantity=20, price=2740.0, timestamp=t0)
    assert portfolio.get_state().open_positions_count == 0
    assert portfolio.get_state().cash == 94800.0
    assert portfolio.get_state().total_portfolio_value == 94800.0

    # Converting unrealized breach into realized cash loss must STILL halt new BUY orders!
    res_buy_still_halted = engine.validate_order(order_buy_limit, portfolio)
    assert not res_buy_still_halted.approved
    assert "Maximum daily loss limit breached" in (res_buy_still_halted.rejection_reason or "")


# =====================================================================
# 8. Deterministic Position Size Calculator Tests
# =====================================================================


def test_calculate_position_size_respects_risk_and_exposure():
    """Verify calculate_position_size deterministically bounds quantities."""
    engine = RiskEngine(
        config=RiskConfig(max_risk_per_trade=0.02, max_position_exposure=0.25),
        execution_config=ExecutionConfig(slippage_pct=0.0, brokerage_rate=0.0),
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)

    # 1. Tight stop loss: Entry = 1000.0, SL = 980.0 (Per share risk = ₹20.0)
    # Capital = 100,000. Max risk = 2,000. Qty by risk = 2,000 // 20 = 100 shares.
    # Max exposure = 25,000 // 1000 = 25 shares.
    # Safe quantity = min(100, 25) = 25 shares (constrained by position exposure!).
    qty1 = engine.calculate_position_size(
        symbol="RELIANCE", price=1000.0, stop_loss=980.0, portfolio=portfolio
    )
    assert qty1 == 25

    # 2. Wide stop loss: Entry = 1000.0, SL = 800.0 (Per share risk = ₹200.0)
    # Qty by risk = 2,000 // 200 = 10 shares.
    # Max exposure = 25 shares.
    # Safe quantity = min(10, 25) = 10 shares (constrained by risk per trade!).
    qty2 = engine.calculate_position_size(
        symbol="RELIANCE", price=1000.0, stop_loss=800.0, portfolio=portfolio
    )
    assert qty2 == 10

    # 3. No stop loss provided: bounded solely by position exposure (25 shares)
    qty3 = engine.calculate_position_size(
        symbol="RELIANCE", price=1000.0, stop_loss=None, portfolio=portfolio
    )
    assert qty3 == 25


def test_calculate_position_size_fixed_fee_regression():
    """Regression test: verify calculate_position_size includes fixed_fee_per_order.

    Proves:
    1. Returned quantity is affordable (cash_required <= available_cash).
    2. Returned quantity passes validate_order().
    3. One additional unit fails validate_order() due to insufficient cash.
    4. When available cash <= fixed_fee_per_order, returns 0.
    """
    fixed_fee = 50.0
    price = 100.0
    capital = 1000.0
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # 1. Zero slippage / zero brokerage to isolate fixed_fee impact
    # Capital = 1000.0, Price = 100.0, Fixed Fee = 50.0.
    # Without fix, cash_per_unit = 100.0 -> returned 10.
    # But 10 * 100 + 50 = 1050 > 1000 -> rejected by validate_order!
    # With fix, effective_cash = 1000 - 50 = 950.0 -> returns 9.
    engine = RiskEngine(
        config=RiskConfig(max_position_exposure=1.0, max_risk_per_trade=1.0),
        execution_config=ExecutionConfig(
            slippage_pct=0.0, brokerage_rate=0.0, fixed_fee_per_order=fixed_fee
        ),
    )
    portfolio = PortfolioTracker(initial_capital=capital)

    qty = engine.calculate_position_size(
        symbol="ABC", price=price, stop_loss=None, portfolio=portfolio
    )
    assert qty == 9

    # Prove 1 & 2: returned quantity is affordable and passes validate_order()
    order_ok = OrderRequest(
        symbol="ABC",
        side=OrderSide.BUY,
        quantity=qty,
        decision_time=t0,
        decision_price=price,
    )
    res_ok = engine.validate_order(order_ok, portfolio)
    assert res_ok.approved
    assert res_ok.risk_metrics["cash_required"] == 950.0
    assert res_ok.risk_metrics["cash_required"] <= portfolio.cash

    # Prove 3: one additional unit fails validate_order() for insufficient cash
    order_excess = OrderRequest(
        symbol="ABC",
        side=OrderSide.BUY,
        quantity=qty + 1,
        decision_time=t0,
        decision_price=price,
    )
    res_excess = engine.validate_order(order_excess, portfolio)
    assert not res_excess.approved
    assert "Insufficient available cash" in (res_excess.rejection_reason or "")
    assert res_excess.risk_metrics["cash_required"] == 1050.0
    assert res_excess.risk_metrics["cash_required"] > portfolio.cash

    # 2. Non-zero slippage + non-zero brokerage + fixed fee
    # Capital = 10,000, Price = 1000.0, Slippage = 0.05%, Brokerage = 0.03%, Fixed fee = 25.0
    engine_realistic = RiskEngine(
        config=RiskConfig(max_position_exposure=1.0, max_risk_per_trade=1.0),
        execution_config=ExecutionConfig(
            slippage_pct=0.0005, brokerage_rate=0.0003, fixed_fee_per_order=25.0
        ),
    )
    portfolio_real = PortfolioTracker(initial_capital=10000.0)
    qty_real = engine_realistic.calculate_position_size(
        symbol="XYZ", price=1000.0, stop_loss=None, portfolio=portfolio_real
    )
    assert qty_real > 0

    order_real_ok = OrderRequest(
        symbol="XYZ",
        side=OrderSide.BUY,
        quantity=qty_real,
        decision_time=t0,
        decision_price=1000.0,
    )
    res_real_ok = engine_realistic.validate_order(order_real_ok, portfolio_real)
    assert res_real_ok.approved
    assert res_real_ok.risk_metrics["cash_required"] <= portfolio_real.cash

    order_real_next = OrderRequest(
        symbol="XYZ",
        side=OrderSide.BUY,
        quantity=qty_real + 1,
        decision_time=t0,
        decision_price=1000.0,
    )
    res_real_next = engine_realistic.validate_order(order_real_next, portfolio_real)
    assert not res_real_next.approved
    assert "Insufficient available cash" in (res_real_next.rejection_reason or "")

    # Prove 4: when available cash <= fixed_fee_per_order, returns 0
    portfolio_broke = PortfolioTracker(initial_capital=25.0)
    qty_zero = engine_realistic.calculate_position_size(
        symbol="XYZ", price=1000.0, stop_loss=None, portfolio=portfolio_broke
    )
    assert qty_zero == 0


# =====================================================================
# 9. Full End-to-End Pipeline Integration Test
# =====================================================================


def test_end_to_end_order_risk_validation_and_execution_pipeline():
    """Verify complete flow: Propose Order -> RiskEngine Validates -> ExecutionEngine Executes -> Portfolio Updates."""
    exec_config = ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003)
    risk_config = RiskConfig(max_risk_per_trade=0.02, max_position_exposure=0.25)

    risk_engine = RiskEngine(config=risk_config, execution_config=exec_config)
    execution_engine = ExecutionEngine(config=exec_config)
    portfolio = PortfolioTracker(initial_capital=100000.0)

    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)

    # 1. Propose valid BUY order: 10 shares of RELIANCE @ 2000.0 (value ₹20,000 <= ₹25,000)
    # SL = 1900.0 (Risk = 10 * 101 = ₹1010 <= ₹2,000)
    order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        decision_time=t0,
        decision_price=2000.0,
        stop_loss=1900.0,
        take_profit=2200.0,
    )

    # 2. Risk check
    risk_res = risk_engine.validate_order(order, portfolio)
    assert risk_res.approved

    # 3. Next candle arrives at t1 with open 2000.0
    from app.market_data.schema import CandleData

    candle = CandleData(
        timestamp=t1, open=2000.0, high=2010.0, low=1990.0, close=2005.0, volume=1000.0
    )

    # 4. Execution
    exec_res = execution_engine.execute_order(order, candle, portfolio)
    assert exec_res.status == OrderStatus.FILLED
    # Execution price = 2000.0 * 1.0005 = 2001.00
    assert exec_res.execution_price == 2001.00

    # 5. Portfolio state verification
    pos = portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10
    assert pos.average_entry_price == 2001.00

    state = portfolio.get_state()
    assert state.open_positions_count == 1
    # Cash = 100,000 - (10 * 2001.0 + 10 * 2001.0 * 0.0003) = 100,000 - 20016.003 = 79,983.997
    assert state.cash == 79983.997
    # Conservation invariant
    assert state.total_portfolio_value == round(state.initial_capital + state.net_pnl, 4)
