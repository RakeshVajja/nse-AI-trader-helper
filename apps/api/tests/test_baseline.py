"""Unit and integration tests for Deterministic Benchmark Baseline Strategy (Phase 6C).

Verifies all frozen Phase 6C requirements:
1. Bullish crossover exact boundary: prev_ema9 <= prev_ema20 AND curr_ema9 > curr_ema20.
2. Bearish crossover exact boundary: prev_ema9 >= prev_ema20 AND curr_ema9 < curr_ema20.
3. Equality at current candle (curr_ema9 == curr_ema20) emits HOLD.
4. Missing EMA values emit HOLD.
5. Earliest valid crossover / warmup (bars 0..19 emit HOLD; earliest valid crossover at bar 20).
6. Flat + bullish crossover => BUY.
7. Flat + bearish crossover => HOLD.
8. Long + bullish crossover => HOLD.
9. Long + bearish crossover => SELL.
10. Baseline never creates a short position.
11. Baseline never scales into an existing position.
12. Exact stop-loss calculation: round(candle_t.close * 0.98, 2).
13. Stop-loss is based strictly on candle t Close, never on t+1 Open or execution fill price.
14. Baseline orders pass through RiskEngine sizing and validation.
15. Baseline execution occurs strictly at candle t+1 Open via ChronologicalReplayEngine.
16. Zero dependency on market-regime classifier (descriptive context only).
17. Strategy works seamlessly through the Phase 6A strategy interface (ReplayContext).
18. Repeated identical inputs produce identical decisions (deterministic reproducibility).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskConfig, RiskEngine
from app.trading.schemas import (
    ExecutionConfig,
    OrderSide,
    OrderStatus,
    PortfolioState,
)
from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    ReplayContext,
)
from app.trading.strategy.baseline import (
    SIGNAL_BUY,
    SIGNAL_SELL,
    BenchmarkBaselineStrategy,
)


def _make_candle(
    timestamp: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float = 1000.0,
    symbol: str = "RELIANCE",
) -> CandleData:
    """Helper to construct a CandleData instance."""
    candle = CandleData(
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
    object.__setattr__(candle, "symbol", symbol)
    return candle


def _build_candles_with_closes(closes: List[float], symbol: str = "RELIANCE") -> List[CandleData]:
    """Helper to construct a sequence of candles from a list of Close prices."""
    candles: List[CandleData] = []
    base_ts = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)
    for i, c in enumerate(closes):
        ts = base_ts + timedelta(minutes=15 * i)
        candle = _make_candle(
            timestamp=ts,
            open_price=c,
            high_price=c + 5.0,
            low_price=c - 5.0,
            close_price=c,
            volume=1000.0,
            symbol=symbol,
        )
        candles.append(candle)
    return candles


def _make_context(
    candles: List[CandleData],
    portfolio_state: PortfolioState,
    step_index: int = 0,
) -> ReplayContext:
    """Helper to construct a ReplayContext."""
    return ReplayContext(
        current_candle=candles[-1],
        visible_candles=tuple(candles),
        portfolio_state=portfolio_state,
        virtual_time=candles[-1].timestamp,
        step_index=step_index,
        total_candles=len(candles),
    )


# ==============================================================================
# 1. Exact Crossover Boundaries (Mathematical Unit Tests)
# ==============================================================================


def test_bullish_crossover_exact_boundaries():
    """Verify exact mathematical boundary conditions for bullish crossover:

    prev_ema9 <= prev_ema20 AND curr_ema9 > curr_ema20.
    """
    eval_fn = BenchmarkBaselineStrategy.evaluate_crossover_values

    # Strict crossover from below: prev_ema9 < prev_ema20 and curr_ema9 > curr_ema20 -> BUY
    assert (
        eval_fn(prev_ema9=99.5, curr_ema9=100.5, prev_ema20=100.0, curr_ema20=100.0) == SIGNAL_BUY
    )

    # Boundary equality at t-1: prev_ema9 == prev_ema20 and curr_ema9 > curr_ema20 -> BUY
    assert (
        eval_fn(prev_ema9=100.0, curr_ema9=100.2, prev_ema20=100.0, curr_ema20=100.0) == SIGNAL_BUY
    )

    # Already above at t-1: prev_ema9 > prev_ema20 and curr_ema9 > curr_ema20 -> HOLD (no cross)
    assert eval_fn(prev_ema9=100.5, curr_ema9=101.0, prev_ema20=100.0, curr_ema20=100.0) is None


def test_bearish_crossover_exact_boundaries():
    """Verify exact mathematical boundary conditions for bearish crossover:

    prev_ema9 >= prev_ema20 AND curr_ema9 < curr_ema20.
    """
    eval_fn = BenchmarkBaselineStrategy.evaluate_crossover_values

    # Strict crossover from above: prev_ema9 > prev_ema20 and curr_ema9 < curr_ema20 -> SELL
    assert (
        eval_fn(prev_ema9=100.5, curr_ema9=99.5, prev_ema20=100.0, curr_ema20=100.0) == SIGNAL_SELL
    )

    # Boundary equality at t-1: prev_ema9 == prev_ema20 and curr_ema9 < curr_ema20 -> SELL
    assert (
        eval_fn(prev_ema9=100.0, curr_ema9=99.8, prev_ema20=100.0, curr_ema20=100.0) == SIGNAL_SELL
    )

    # Already below at t-1: prev_ema9 < prev_ema20 and curr_ema9 < curr_ema20 -> HOLD (no cross)
    assert eval_fn(prev_ema9=99.5, curr_ema9=99.0, prev_ema20=100.0, curr_ema20=100.0) is None


def test_equality_at_current_candle_emits_hold():
    """Verify curr_ema9 == curr_ema20 is strictly NOT a crossover (emits HOLD)."""
    eval_fn = BenchmarkBaselineStrategy.evaluate_crossover_values

    # Touch from below: prev_ema9 < prev_ema20 and curr_ema9 == curr_ema20 -> HOLD
    assert eval_fn(prev_ema9=99.0, curr_ema9=100.0, prev_ema20=100.0, curr_ema20=100.0) is None

    # Touch from above: prev_ema9 > prev_ema20 and curr_ema9 == curr_ema20 -> HOLD
    assert eval_fn(prev_ema9=101.0, curr_ema9=100.0, prev_ema20=100.0, curr_ema20=100.0) is None

    # Parallel equality: prev_ema9 == prev_ema20 and curr_ema9 == curr_ema20 -> HOLD
    assert eval_fn(prev_ema9=100.0, curr_ema9=100.0, prev_ema20=100.0, curr_ema20=100.0) is None


def test_missing_ema_values_emit_hold():
    """Verify that if any of prev_ema9, curr_ema9, prev_ema20, curr_ema20 is missing, signal is HOLD."""
    eval_fn = BenchmarkBaselineStrategy.evaluate_crossover_values

    assert eval_fn(prev_ema9=None, curr_ema9=101.0, prev_ema20=100.0, curr_ema20=100.0) is None
    assert eval_fn(prev_ema9=99.0, curr_ema9=None, prev_ema20=100.0, curr_ema20=100.0) is None
    assert eval_fn(prev_ema9=99.0, curr_ema9=101.0, prev_ema20=None, curr_ema20=100.0) is None
    assert eval_fn(prev_ema9=99.0, curr_ema9=101.0, prev_ema20=100.0, curr_ema20=None) is None


# ==============================================================================
# 2. Warmup & Earliest Crossover Bar (Index 20 / 21st Candle)
# ==============================================================================


def test_warmup_period_emits_hold_prior_to_bar_index_20():
    """Verify that all candles prior to index 20 (bars 0..19) strictly emit HOLD."""
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)

    # 25 candles with flat prices followed by sharp upward jump
    # Flat 100 for 19 bars, then 100, then jump to 200 to induce crossover
    closes = [100.0] * 19 + [100.0, 150.0, 160.0, 170.0, 180.0, 190.0]
    all_candles = _build_candles_with_closes(closes)

    # For each bar from 0 to 19 (first 20 candles), verify strategy returns [] (HOLD)
    for idx in range(20):
        sub_candles = all_candles[: idx + 1]
        ctx = _make_context(sub_candles, portfolio.get_state(), step_index=idx)
        orders = strategy(ctx)
        assert orders == [], f"Expected HOLD at warmup bar index {idx}, got {orders}"

    # At bar index 20 (the 21st candle), both t-1 and t have valid EMA9 and EMA20
    # Because price jumped from 100 to 150 at index 20, EMA9 crosses above EMA20 -> BUY
    ctx20 = _make_context(all_candles[:21], portfolio.get_state(), step_index=20)
    orders20 = strategy(ctx20)
    assert len(orders20) == 1
    assert orders20[0].side == OrderSide.BUY
    assert orders20[0].symbol == "RELIANCE"


# ==============================================================================
# 3. Position State Rules: Flat vs Long
# ==============================================================================


def test_flat_position_signals():
    """Verify:

    Flat + bullish crossover => BUY.
    Flat + bearish crossover => HOLD.
    """
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)
    flat_state = portfolio.get_state()
    assert flat_state.open_positions_count == 0

    # 1. Flat + Bullish Crossover -> BUY
    # 20 flat candles at 100, then candle 21 at 150 (bullish cross)
    closes_bull = [100.0] * 20 + [150.0]
    candles_bull = _build_candles_with_closes(closes_bull)
    ctx_bull = _make_context(candles_bull, flat_state, step_index=20)
    orders_bull = strategy(ctx_bull)

    assert len(orders_bull) == 1
    assert orders_bull[0].side == OrderSide.BUY
    assert orders_bull[0].quantity > 0

    # 2. Flat + Bearish Crossover -> HOLD (never short sell!)
    # 20 flat candles at 100, then candle 21 at 50 (bearish cross)
    closes_bear = [100.0] * 20 + [50.0]
    candles_bear = _build_candles_with_closes(closes_bear)
    ctx_bear = _make_context(candles_bear, flat_state, step_index=20)
    orders_bear = strategy(ctx_bear)

    assert orders_bear == []  # Strictly HOLD


def test_long_position_signals():
    """Verify:

    Long + bullish crossover => HOLD (no scaling into existing position).
    Long + bearish crossover => SELL to close entire existing position.
    """
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)
    t0 = datetime(2026, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Open a position of 15 shares of RELIANCE
    portfolio.open_or_increase_position(
        "RELIANCE", quantity=15, price=2000.0, stop_loss=1960.0, timestamp=t0
    )
    long_state = portfolio.get_state()
    assert long_state.open_positions_count == 1
    assert long_state.positions["RELIANCE"].quantity == 15

    # 1. Long + Bullish Crossover -> HOLD (no scaling)
    closes_bull = [100.0] * 20 + [150.0]
    candles_bull = _build_candles_with_closes(closes_bull)
    ctx_bull = _make_context(candles_bull, long_state, step_index=20)
    orders_bull = strategy(ctx_bull)

    assert orders_bull == []  # Strictly HOLD

    # 2. Long + Bearish Crossover -> SELL to close entire position (15 shares)
    closes_bear = [100.0] * 20 + [50.0]
    candles_bear = _build_candles_with_closes(closes_bear)
    ctx_bear = _make_context(candles_bear, long_state, step_index=20)
    orders_bear = strategy(ctx_bear)

    assert len(orders_bear) == 1
    sell_order = orders_bear[0]
    assert sell_order.side == OrderSide.SELL
    assert sell_order.quantity == 15
    assert sell_order.stop_loss is None


def test_baseline_never_short_sells_under_multiple_bearish_crossovers():
    """Verify repeated bearish crossovers while flat continue to emit HOLD."""
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)

    # Sequence of falling prices
    closes = [200.0 - (i * 2.0) for i in range(25)]
    candles = _build_candles_with_closes(closes)

    for i in range(20, 25):
        ctx = _make_context(candles[: i + 1], portfolio.get_state(), step_index=i)
        orders = strategy(ctx)
        assert orders == [], f"Expected HOLD at bar {i} while flat, got {orders}"


def test_baseline_never_scales_existing_position_under_multiple_bullish_bars():
    """Verify repeated bullish signals while long never scale the position."""
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)
    portfolio.open_or_increase_position("RELIANCE", quantity=10, price=100.0)

    # Sequence of rising prices
    closes = [100.0 + (i * 5.0) for i in range(25)]
    candles = _build_candles_with_closes(closes)

    for i in range(20, 25):
        ctx = _make_context(candles[: i + 1], portfolio.get_state(), step_index=i)
        orders = strategy(ctx)
        assert orders == [], f"Expected HOLD at bar {i} while long, got {orders}"


# ==============================================================================
# 4. Exact Stop-Loss Calculation & Reference Price
# ==============================================================================


def test_exact_stop_loss_calculation_formula():
    """Verify stop_loss = round(candle_t.close * 0.98, 2) against exact numerical values."""
    fn = BenchmarkBaselineStrategy.calculate_stop_loss

    # 2000.0 * 0.98 = 1960.0
    assert fn(2000.0) == 1960.0

    # 2005.35 * 0.98 = 1965.243 -> 1965.24
    assert fn(2005.35) == 1965.24

    # 153.77 * 0.98 = 150.6946 -> 150.69
    assert fn(153.77) == 150.69

    # 2450.50 * 0.98 = 2401.49
    assert fn(2450.50) == 2401.49

    # 100.0 * 0.98 = 98.0
    assert fn(100.0) == 98.0


def test_stop_loss_is_attached_to_buy_order_and_based_on_close():
    """Verify generated OrderRequest.stop_loss equals round(candle_t.close * 0.98, 2)."""
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)

    # Candle 20 has close = 2005.35
    closes = [2000.0] * 20 + [2005.35]
    candles = _build_candles_with_closes(closes)

    ctx = _make_context(candles, portfolio.get_state(), step_index=20)
    orders = strategy(ctx)

    assert len(orders) == 1
    order = orders[0]
    assert order.side == OrderSide.BUY
    assert order.decision_price == 2005.35
    # Must match round(2005.35 * 0.98, 2) = 1965.24
    assert order.stop_loss == 1965.24


# ==============================================================================
# 5. RiskEngine Sizing & Pre-Trade Checks
# ==============================================================================


def test_baseline_order_sized_and_validated_by_risk_engine():
    """Verify BUY orders are sized according to RiskEngine limits (2% risk, 25% exposure, cash)."""
    risk_cfg = RiskConfig(
        max_risk_per_trade=0.02,  # 2% of ₹1,00,000 = ₹2,000 risk
        max_position_exposure=0.25,  # 25% of ₹1,00,000 = ₹25,000 max position
        max_daily_loss=0.05,
    )
    risk_engine = RiskEngine(config=risk_cfg)
    portfolio = PortfolioTracker(initial_capital=100000.0)
    strategy = BenchmarkBaselineStrategy(
        symbol="RELIANCE", risk_engine=risk_engine, portfolio=portfolio
    )

    # Candle close = 2000.0, stop_loss = 1960.0 -> risk per share ~ ₹41
    # Max risk limit: ₹2000 // ₹41 ~ 48 shares
    # Max exposure limit: ₹25000 // 2001 ~ 12 shares
    # Sizing should be bounded by exposure: 12 shares
    closes = [1900.0] * 20 + [2000.0]
    candles = _build_candles_with_closes(closes)

    ctx = _make_context(candles, portfolio.get_state(), step_index=20)
    orders = strategy(ctx)

    assert len(orders) == 1
    order = orders[0]
    assert order.side == OrderSide.BUY
    assert order.quantity == 12
    # Verify order passes validate_order()
    res = risk_engine.validate_order(order=order, portfolio=portfolio, current_price=2000.0)
    assert res.approved


def test_baseline_emits_hold_when_cash_is_insufficient_for_risk_engine():
    """Verify strategy emits HOLD if available cash is insufficient to buy even 1 share."""
    risk_engine = RiskEngine()
    portfolio = PortfolioTracker(initial_capital=100.0)  # Only ₹100 cash
    strategy = BenchmarkBaselineStrategy(
        symbol="RELIANCE", risk_engine=risk_engine, portfolio=portfolio
    )

    # Candle close = 2000.0 (cannot afford 1 share with ₹100)
    closes = [1900.0] * 20 + [2000.0]
    candles = _build_candles_with_closes(closes)

    ctx = _make_context(candles, portfolio.get_state(), step_index=20)
    orders = strategy(ctx)

    assert orders == []  # Insufficient cash -> HOLD


# ==============================================================================
# 6. Replay Engine Integration & Execution Timing
# ==============================================================================


def test_baseline_integration_execution_at_next_candle_open():
    """Verify baseline signal at candle t executes strictly at candle t+1 OPEN in ChronologicalReplayEngine."""
    # Build 23 candles:
    # 0..19: Flat at 2000
    # 20: Sharp jump to 2100 (triggers BUY at candle 20 Close!)
    # 21: Candle 21 Open 2100 (BUY executes here!), Close 2150
    # 22: Candle 22 Open 2150, Close 2160
    closes = [2000.0] * 20 + [2100.0, 2150.0, 2160.0]
    candles = _build_candles_with_closes(closes)

    exec_config = ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003)
    engine = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        execution_engine=ExecutionEngine(config=exec_config),
        initial_capital=100000.0,
    )
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE", risk_engine=engine.risk_engine)

    # Process bars 0..20 (first 21 candles)
    for _ in range(21):
        engine.step(strategy=strategy)

    # At bar 20: Strategy emitted BUY for candle 20 Close (2100.0)
    # Position must NOT exist yet!
    assert engine.portfolio.get_position("RELIANCE") is None
    assert len(engine.pending_strategy_orders) == 1
    pending = engine.pending_strategy_orders[0]
    assert pending.side == OrderSide.BUY
    assert pending.stop_loss == round(2100.0 * 0.98, 2)  # 2058.0

    # Step bar 21: Order executes at Candle 21 OPEN!
    res21 = engine.step(strategy=strategy)
    assert res21 is not None
    assert len(res21.strategy_orders_executed) == 1
    fill = res21.strategy_orders_executed[0]
    assert fill.status == OrderStatus.FILLED
    assert fill.market_price == candles[21].open
    assert fill.executed_at == candles[21].timestamp

    # Position is now open with exact stop-loss preserved
    pos = engine.portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == pending.quantity
    assert pos.stop_loss == 2058.0  # Exactly based on decision Close 2100, NOT fill price!


def test_stop_loss_not_calculated_from_fill_price_or_next_open():
    """Verify stop_loss remains based on decision candle Close even if next candle gaps up or down."""
    # Decision candle Close: 2000.0 -> SL = 1960.0
    # Next candle Open gaps up to 2100.0, fill price is 2101.05
    closes = [1900.0] * 20 + [2000.0]
    candles = _build_candles_with_closes(closes)

    # Manually append next candle with open 2100.0
    next_ts = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)
    candle_next = _make_candle(next_ts, 2100.0, 2110.0, 2090.0, 2105.0, symbol="RELIANCE")
    candles.append(candle_next)

    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE", initial_capital=100000.0)
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE", risk_engine=engine.risk_engine)

    # Process all candles
    summary = engine.run(strategy=strategy)

    assert len(summary.executions) == 1
    fill = summary.executions[0]
    assert fill.status == OrderStatus.FILLED
    assert fill.market_price == 2100.0

    pos = engine.portfolio.get_position("RELIANCE")
    assert pos is not None
    # SL is strictly 1960.0 (based on 2000.0 Close), NOT 2058.0 (based on 2100.0 Open)
    assert pos.stop_loss == 1960.0


# ==============================================================================
# 7. Zero Market-Regime Dependency
# ==============================================================================


def test_zero_market_regime_dependency():
    """Verify baseline strategy does not import or depend on market regime classifier."""
    import ast
    import inspect

    import app.trading.strategy.baseline as baseline_module

    tree = ast.parse(inspect.getsource(baseline_module))
    imported_modules = set()
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module)
            for alias in node.names:
                imported_names.add(alias.name)

    # Must not import regime module or regime classes
    assert not any("regime" in m for m in imported_modules)
    assert "TrendRegime" not in imported_names
    assert "VolatilityRegime" not in imported_names


# ==============================================================================
# 8. Deterministic Output Reproducibility
# ==============================================================================


def test_deterministic_identical_outputs():
    """Verify calling baseline strategy repeatedly with identical context produces identical OrderRequests."""
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE")
    portfolio = PortfolioTracker(initial_capital=100000.0)

    closes = [100.0] * 20 + [150.0]
    candles = _build_candles_with_closes(closes)
    ctx = _make_context(candles, portfolio.get_state(), step_index=20)

    orders1 = strategy(ctx)
    orders2 = strategy(ctx)

    assert len(orders1) == len(orders2) == 1
    o1 = orders1[0]
    o2 = orders2[0]

    # Bit-for-bit equivalence including deterministic order_id
    assert o1.order_id == o2.order_id
    assert o1.symbol == o2.symbol
    assert o1.side == o2.side
    assert o1.quantity == o2.quantity
    assert o1.decision_time == o2.decision_time
    assert o1.decision_price == o2.decision_price
    assert o1.stop_loss == o2.stop_loss
    assert o1 == o2


@pytest.mark.asyncio
async def test_baseline_integration_with_simulation_clock():
    """Verify BenchmarkBaselineStrategy integrates seamlessly with SimulationClock (Phase 6B)."""
    from app.trading.simulation.clock import SimulationClock, SimulationLifecycleState

    closes = [2000.0] * 20 + [2100.0, 2150.0, 2160.0]
    candles = _build_candles_with_closes(closes)

    engine = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        initial_capital=100000.0,
    )
    strategy = BenchmarkBaselineStrategy(symbol="RELIANCE", risk_engine=engine.risk_engine)
    clock = SimulationClock(engine=engine, strategy=strategy, speed=1.0, base_delay=0.0)

    await clock.start()
    summary = await clock.wait_until_complete(timeout=2.0)

    assert clock.state == SimulationLifecycleState.COMPLETED
    assert summary.total_steps == len(candles)
    # BUY executed at candle 21 Open
    assert len(summary.executions) == 1
    assert summary.executions[0].status == OrderStatus.FILLED
    assert summary.executions[0].side == OrderSide.BUY
