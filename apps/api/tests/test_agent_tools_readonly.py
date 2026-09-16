"""Unit tests for Phase 7B Read-Only Agent Tools (Phase 7D).

Covers the 7 read-only / advisory tools:
1. get_market_data
2. get_indicators
3. get_market_regime
4. get_position
5. get_portfolio
6. get_trade_history
7. calculate_position_size
"""

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.market_data.schema import CandleData
from app.trading.agent.schemas import (
    CalculatePositionSizeInput,
    GetIndicatorsInput,
    GetMarketDataInput,
    GetMarketRegimeInput,
    GetPositionInput,
    GetTradeHistoryInput,
)
from app.trading.agent.tools import (
    ToolExecutionContext,
    calculate_position_size,
    get_indicators,
    get_market_data,
    get_market_regime,
    get_portfolio,
    get_position,
    get_trade_history,
)
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderSide, TradeRecord

# ==============================================================================
# Test Fixtures & Helpers
# ==============================================================================


def generate_synthetic_candles(
    count: int = 30,
    base_price: float = 2500.0,
    start_time: datetime = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
) -> List[CandleData]:
    """Generate an ascending historical candle series."""
    candles: List[CandleData] = []
    curr_price = base_price
    for i in range(count):
        ts = start_time + timedelta(minutes=15 * i)
        o = curr_price
        h = curr_price + 10.0
        l = curr_price - 5.0
        c = curr_price + (2.0 if i % 2 == 0 else -1.0)
        v = 50000.0 + (i * 1000.0)
        candles.append(CandleData(timestamp=ts, open=o, high=h, low=l, close=c, volume=v))
        curr_price = c
    return candles


@pytest.fixture
def base_candles() -> List[CandleData]:
    return generate_synthetic_candles(count=20, base_price=2500.0)


@pytest.fixture
def tool_context(base_candles: List[CandleData]) -> ToolExecutionContext:
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    current = base_candles[-1]
    return ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=current.timestamp,
        current_candle=current,
        visible_candles=base_candles,
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=[],
    )


# ==============================================================================
# 1. get_market_data Tests
# ==============================================================================


def test_get_market_data_defaults_and_values(tool_context: ToolExecutionContext):
    out = get_market_data(tool_context)
    assert out.symbol == "RELIANCE"
    assert out.timeframe == "15m"
    assert len(out.recent_candles) == 10  # default lookback
    assert out.current_candle.timestamp == tool_context.current_candle.timestamp
    assert out.current_price == tool_context.current_candle.close
    assert out.current_volume == tool_context.current_candle.volume

    expected_change = round(
        float(tool_context.visible_candles[-1].close)
        - float(tool_context.visible_candles[-2].close),
        4,
    )
    assert out.price_change == expected_change

    # Read-only check: portfolio and staged orders completely untouched
    assert tool_context.portfolio.cash == 100000.0
    assert len(tool_context.staged_orders) == 0


def test_get_market_data_custom_lookback(tool_context: ToolExecutionContext):
    inp = GetMarketDataInput(lookback=5)
    out = get_market_data(tool_context, inp)
    assert len(out.recent_candles) == 5


def test_get_market_data_lookback_exceeds_available(tool_context: ToolExecutionContext):
    # lookback 50 when only 20 candles exist -> returns all 20
    inp = GetMarketDataInput(lookback=50)
    out = get_market_data(tool_context, inp)
    assert len(out.recent_candles) == 20


def test_get_market_data_single_candle():
    c = CandleData(
        timestamp=datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
        open=2500.0,
        high=2510.0,
        low=2490.0,
        close=2505.0,
        volume=10000.0,
    )
    ctx = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c.timestamp,
        current_candle=c,
        visible_candles=[c],
        portfolio=PortfolioTracker(),
        risk_engine=RiskEngine(),
    )
    out = get_market_data(ctx)
    assert out.price_change == 0.0
    assert out.price_change_pct == 0.0


def test_get_market_data_symbol_mismatch(tool_context: ToolExecutionContext):
    inp = GetMarketDataInput(symbol="TCS")
    with pytest.raises(ValueError, match="Symbol mismatch"):
        get_market_data(tool_context, inp)


def test_get_market_data_symbol_case_insensitive(tool_context: ToolExecutionContext):
    inp = GetMarketDataInput(symbol="reliance")
    out = get_market_data(tool_context, inp)
    assert out.symbol == "RELIANCE"


def test_get_market_data_empty_candles_raises():
    c = CandleData(
        timestamp=datetime.now(timezone.utc),
        open=2500.0,
        high=2510.0,
        low=2490.0,
        close=2500.0,
        volume=1000.0,
    )
    ctx = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c.timestamp,
        current_candle=c,
        visible_candles=[],
        portfolio=PortfolioTracker(),
        risk_engine=RiskEngine(),
    )
    with pytest.raises(ValueError, match="no visible candles"):
        get_market_data(ctx)


# ==============================================================================
# 2. get_indicators Tests
# ==============================================================================


def test_get_indicators_warmup_and_structure(tool_context: ToolExecutionContext):
    out = get_indicators(tool_context)
    assert out.symbol == "RELIANCE"
    assert out.close == tool_context.current_candle.close
    assert out.timestamp == tool_context.current_candle.timestamp
    # Base fixture only has 20 candles, SMA50 needs 50 -> is_warmed_up should be False
    assert out.is_warmed_up is False
    assert out.sma_50 is None

    # Read-only check
    assert tool_context.portfolio.cash == 100000.0
    assert len(tool_context.staged_orders) == 0


def test_get_indicators_warmed_up():
    long_series = generate_synthetic_candles(count=60, base_price=2500.0)
    ctx = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=long_series[-1].timestamp,
        current_candle=long_series[-1],
        visible_candles=long_series,
        portfolio=PortfolioTracker(),
        risk_engine=RiskEngine(),
    )
    out = get_indicators(ctx)
    assert out.is_warmed_up is True
    assert out.ema_9 is not None
    assert out.ema_20 is not None
    assert out.sma_50 is not None
    assert out.rsi_14 is not None
    assert out.macd is not None
    assert out.macd_signal is not None
    assert out.macd_histogram is not None


def test_get_indicators_symbol_mismatch(tool_context: ToolExecutionContext):
    inp = GetIndicatorsInput(symbol="INFY")
    with pytest.raises(ValueError, match="Symbol mismatch"):
        get_indicators(tool_context, inp)


def test_get_indicators_empty_candles_raises():
    c = CandleData(
        timestamp=datetime.now(timezone.utc),
        open=2500.0,
        high=2510.0,
        low=2490.0,
        close=2500.0,
        volume=1000.0,
    )
    ctx = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c.timestamp,
        current_candle=c,
        visible_candles=[],
        portfolio=PortfolioTracker(),
        risk_engine=RiskEngine(),
    )
    with pytest.raises(ValueError, match="no visible candles"):
        get_indicators(ctx)


# ==============================================================================
# 3. get_market_regime Tests
# ==============================================================================


def test_get_market_regime_integration(tool_context: ToolExecutionContext):
    out = get_market_regime(tool_context)
    assert out.symbol == "RELIANCE"
    assert out.timestamp == tool_context.current_candle.timestamp
    assert out.trend_signals is not None
    assert out.volatility_metrics is not None

    # Read-only check
    assert tool_context.portfolio.cash == 100000.0
    assert len(tool_context.staged_orders) == 0


def test_get_market_regime_warmed_up():
    long_series = generate_synthetic_candles(count=120, base_price=2500.0)
    ctx = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=long_series[-1].timestamp,
        current_candle=long_series[-1],
        visible_candles=long_series,
        portfolio=PortfolioTracker(),
        risk_engine=RiskEngine(),
    )
    out = get_market_regime(ctx)
    assert out.symbol == "RELIANCE"
    assert out.trend_regime in ["BULLISH", "BEARISH", "SIDEWAYS"]
    assert out.volatility_regime in ["HIGH", "NORMAL", "LOW"]


def test_get_market_regime_symbol_mismatch(tool_context: ToolExecutionContext):
    inp = GetMarketRegimeInput(symbol="SBIN")
    with pytest.raises(ValueError, match="Symbol mismatch"):
        get_market_regime(tool_context, inp)


def test_get_market_regime_empty_candles_raises():
    c = CandleData(
        timestamp=datetime.now(timezone.utc),
        open=2500.0,
        high=2510.0,
        low=2490.0,
        close=2500.0,
        volume=1000.0,
    )
    ctx = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c.timestamp,
        current_candle=c,
        visible_candles=[],
        portfolio=PortfolioTracker(),
        risk_engine=RiskEngine(),
    )
    with pytest.raises(ValueError, match="no visible candles"):
        get_market_regime(ctx)


# ==============================================================================
# 4. get_position Tests
# ==============================================================================


def test_get_position_flat(tool_context: ToolExecutionContext):
    out = get_position(tool_context)
    assert out.symbol == "RELIANCE"
    assert out.is_open is False
    assert out.quantity == 0
    assert out.average_entry_price is None
    assert out.market_value == 0.0
    assert out.unrealized_pnl == 0.0
    assert out.current_price == tool_context.current_candle.close


def test_get_position_open(tool_context: ToolExecutionContext):
    # Simulate an active position in portfolio
    tool_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=20,
        price=2450.0,
        transaction_cost=20.0,
        slippage_cost=10.0,
        timestamp=datetime(2025, 1, 1, 9, 30, tzinfo=timezone.utc),
        stop_loss=2400.0,
        take_profit=2550.0,
    )
    # Update mark to market with current candle close
    tool_context.portfolio.update_market_price(
        symbol="RELIANCE",
        current_price=tool_context.current_candle.close,
        timestamp=tool_context.current_candle.timestamp,
    )

    out = get_position(tool_context)
    assert out.is_open is True
    assert out.quantity == 20
    assert out.average_entry_price == 2450.0
    assert out.stop_loss == 2400.0
    assert out.take_profit == 2550.0
    expected_mv = round(20 * float(tool_context.current_candle.close), 4)
    assert out.market_value == expected_mv


def test_get_position_symbol_mismatch(tool_context: ToolExecutionContext):
    inp = GetPositionInput(symbol="WIPRO")
    with pytest.raises(ValueError, match="Symbol mismatch"):
        get_position(tool_context, inp)


# ==============================================================================
# 5. get_portfolio Tests
# ==============================================================================


def test_get_portfolio_integration(tool_context: ToolExecutionContext):
    out = get_portfolio(tool_context)
    assert out.initial_capital == 100000.0
    assert out.cash == 100000.0
    assert out.total_portfolio_value == 100000.0
    assert out.total_market_value == 0.0
    assert out.open_positions_count == 0
    assert out.exposure_pct == 0.0
    assert out.net_pnl == 0.0

    # Read-only check
    assert tool_context.portfolio.cash == 100000.0
    assert len(tool_context.staged_orders) == 0


def test_get_portfolio_with_position(tool_context: ToolExecutionContext):
    tool_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2500.0,
        transaction_cost=10.0,
        slippage_cost=5.0,
        timestamp=tool_context.virtual_time,
    )
    tool_context.portfolio.update_market_price(
        symbol="RELIANCE",
        current_price=2520.0,
        timestamp=tool_context.virtual_time,
    )
    out = get_portfolio(tool_context)
    assert out.open_positions_count == 1
    assert out.total_market_value == 25200.0
    assert out.unrealized_gross_pnl == 200.0
    assert out.exposure_pct > 0.0


# ==============================================================================
# 6. get_trade_history Tests
# ==============================================================================


def test_get_trade_history_empty(tool_context: ToolExecutionContext):
    out = get_trade_history(tool_context)
    assert out.total_closed_trades == 0
    assert out.trades == []


def test_get_trade_history_filtering_and_limits(tool_context: ToolExecutionContext):
    now = datetime.now(timezone.utc)
    for i in range(5):
        tool_context.portfolio.closed_trades.append(
            TradeRecord(
                trade_id=f"TR-{i}",
                symbol="RELIANCE" if i % 2 == 0 else "TCS",
                side=OrderSide.BUY,
                quantity=10,
                entry_price=2400.0,
                exit_price=2450.0,
                entry_time=now,
                exit_time=now,
                exit_reason="TP",
                gross_pnl=500.0,
                net_pnl=480.0,
                transaction_costs=15.0,
                slippage_cost=5.0,
            )
        )

    # Limit 2
    out_lim = get_trade_history(tool_context, GetTradeHistoryInput(limit=2))
    assert out_lim.total_closed_trades == 5
    assert len(out_lim.trades) == 2
    assert out_lim.trades[-1].trade_id == "TR-4"

    # Filter symbol
    out_sym = get_trade_history(tool_context, GetTradeHistoryInput(symbol="TCS", limit=10))
    assert out_sym.total_closed_trades == 2
    assert len(out_sym.trades) == 2
    for t in out_sym.trades:
        assert t.symbol == "TCS"


# ==============================================================================
# 7. calculate_position_size Tests
# ==============================================================================


def test_calculate_position_size_approved(tool_context: ToolExecutionContext):
    inp = CalculatePositionSizeInput(
        entry_price=2500.0,
        stop_loss_price=2450.0,  # 50 rs risk per share
    )
    out = calculate_position_size(tool_context, inp)
    assert out.status == "APPROVED"
    assert out.target_quantity > 0
    assert out.estimated_execution_price >= 2500.0
    assert out.risk_amount > 0.0
    assert out.risk_pct_of_portfolio <= 2.05

    # Pure calculation check: portfolio state completely untouched
    assert tool_context.portfolio.cash == 100000.0
    assert len(tool_context.staged_orders) == 0


def test_calculate_position_size_invalid_sl(tool_context: ToolExecutionContext):
    # SL >= entry price for BUY is invalid
    inp = CalculatePositionSizeInput(
        entry_price=2500.0,
        stop_loss_price=2510.0,
    )
    out = calculate_position_size(tool_context, inp)
    assert out.status == "REJECTED"
    assert out.target_quantity == 0
    assert "Stop-loss price must be strictly less than entry price" in str(out.reason)


def test_calculate_position_size_equal_sl(tool_context: ToolExecutionContext):
    inp = CalculatePositionSizeInput(
        entry_price=2500.0,
        stop_loss_price=2500.0,
    )
    out = calculate_position_size(tool_context, inp)
    assert out.status == "REJECTED"
    assert out.target_quantity == 0


def test_calculate_position_size_risk_override(tool_context: ToolExecutionContext):
    inp_default = CalculatePositionSizeInput(entry_price=2500.0, stop_loss_price=2300.0)
    out_default = calculate_position_size(tool_context, inp_default)

    # 0.5% risk override instead of default 2%
    inp_custom = CalculatePositionSizeInput(
        entry_price=2500.0,
        stop_loss_price=2300.0,
        risk_per_trade=0.005,
    )
    out_custom = calculate_position_size(tool_context, inp_custom)

    assert out_custom.status == "APPROVED"
    assert out_custom.target_quantity < out_default.target_quantity
    # Context risk engine remains unmutated
    assert tool_context.risk_engine.config.max_risk_per_trade == 0.02


def test_calculate_position_size_exhausted_capital(tool_context: ToolExecutionContext):
    # Drain cash
    tool_context.portfolio.cash = 0.0
    inp = CalculatePositionSizeInput(entry_price=2500.0, stop_loss_price=2450.0)
    out = calculate_position_size(tool_context, inp)
    assert out.status == "REJECTED"
    assert out.target_quantity == 0


def test_calculate_position_size_symbol_mismatch(tool_context: ToolExecutionContext):
    inp = CalculatePositionSizeInput(
        symbol="HDFCBANK",
        entry_price=1600.0,
        stop_loss_price=1550.0,
    )
    with pytest.raises(ValueError, match="Symbol mismatch"):
        calculate_position_size(tool_context, inp)
