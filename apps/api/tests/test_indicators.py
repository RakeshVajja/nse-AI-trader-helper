"""Unit tests for deterministic Quantitative Indicator Engine:
- EMA 9, EMA 20
- SMA 50
- RSI 14 (Wilder's smoothing)
- MACD (12, 26, 9)
- ATR 14 (Wilder's smoothing) and ATRP 14
- Insufficient history, edge cases, and QuantitativeIndicatorEngine snapshots.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.indicators.atr import (
    calculate_atr,
    calculate_atr_from_candles,
    calculate_atrp,
    calculate_true_range,
    get_latest_atr,
)
from app.indicators.ema import calculate_ema, calculate_ema_from_candles, get_latest_ema
from app.indicators.engine import QuantitativeIndicatorEngine, get_indicator_engine
from app.indicators.macd import (
    calculate_macd,
    calculate_macd_from_candles,
    get_latest_macd,
)
from app.indicators.rsi import calculate_rsi, calculate_rsi_from_candles, get_latest_rsi
from app.indicators.sma import calculate_sma, calculate_sma_from_candles, get_latest_sma
from app.market_data.schema import CandleData


def _create_candles(prices: list[float], start_time: datetime | None = None) -> list[CandleData]:
    """Helper to generate CandleData list from a list of close prices."""
    base_time = start_time or datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    return [
        CandleData(
            timestamp=base_time + timedelta(minutes=15 * i),
            open=p - 1.0,
            high=p + 2.0,
            low=p - 2.0,
            close=p,
            volume=1000.0 + i * 10,
        )
        for i, p in enumerate(prices)
    ]


# =====================================================================
# 1. EMA Tests (EMA 9, EMA 20)
# =====================================================================


def test_ema_formula_and_known_values():
    """Verify EMA matches recursive alpha multiplier formula."""
    # For period=3, alpha = 2/(3+1) = 0.5
    # Price sequence: [10.0, 20.0, 30.0, 40.0]
    # EMA_0 = 10.0
    # EMA_1 = 0.5*20.0 + 0.5*10.0 = 15.0
    # EMA_2 = 0.5*30.0 + 0.5*15.0 = 22.5
    # EMA_3 = 0.5*40.0 + 0.5*22.5 = 31.25
    prices = [10.0, 20.0, 30.0, 40.0]
    ema = calculate_ema(prices, period=3, min_periods=1)
    assert ema == [10.0, 15.0, 22.5, 31.25]


def test_ema_warmup_masking():
    """Verify that indices before `period - 1` default to None."""
    prices = [100.0 + i for i in range(15)]
    ema9 = calculate_ema(prices, period=9)

    # First 8 items (indices 0..7) should be None
    for i in range(8):
        assert ema9[i] is None

    # Index 8 and beyond should have float values
    assert isinstance(ema9[8], float)
    assert ema9[8] is not None
    assert ema9[-1] is not None


def test_ema_constant_prices():
    """Verify EMA of a constant series equals the constant price."""
    prices = [250.0] * 30
    ema9 = calculate_ema(prices, period=9)
    ema20 = calculate_ema(prices, period=20)

    assert ema9[-1] == 250.0
    assert ema20[-1] == 250.0


def test_ema_insufficient_data():
    """Verify EMA returns None values when data length is smaller than period."""
    prices = [100.0, 101.0, 102.0]
    ema9 = calculate_ema(prices, period=9)
    assert ema9 == [None, None, None]
    assert get_latest_ema(prices, period=9) is None

    # Empty
    assert calculate_ema([], period=9) == []
    assert get_latest_ema([], period=9) is None


def test_ema_invalid_period():
    """Verify ValueError is raised for invalid periods."""
    with pytest.raises(ValueError, match="period must be >= 1"):
        calculate_ema([100.0, 101.0], period=0)


def test_ema_from_candles():
    """Verify calculate_ema_from_candles extracts close prices correctly."""
    candles = _create_candles([100.0 + i for i in range(25)])
    ema9 = calculate_ema_from_candles(candles, period=9)
    ema20 = calculate_ema_from_candles(candles, period=20)

    assert len(ema9) == 25
    assert len(ema20) == 25
    assert ema9[-1] is not None
    assert ema20[-1] is not None
    # In an uptrend, EMA9 should be greater than EMA20
    assert ema9[-1] > ema20[-1]


# =====================================================================
# 2. SMA Tests (SMA 50)
# =====================================================================


def test_sma_known_values():
    """Verify SMA calculation against known arithmetic means."""
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    sma3 = calculate_sma(prices, period=3)

    # Indices 0, 1 should be None
    assert sma3[0] is None
    assert sma3[1] is None
    # Index 2: mean(10, 20, 30) = 20.0
    assert sma3[2] == 20.0
    # Index 3: mean(20, 30, 40) = 30.0
    assert sma3[3] == 30.0
    # Index 4: mean(30, 40, 50) = 40.0
    assert sma3[4] == 40.0


def test_sma50_calculation():
    """Verify SMA50 calculation on 60 data points."""
    # 60 prices: 1, 2, ..., 60
    prices = [float(i) for i in range(1, 61)]
    sma50 = calculate_sma(prices, period=50)

    assert len(sma50) == 60
    # First 49 bars (0..48) must be None
    for i in range(49):
        assert sma50[i] is None

    # Bar 49 (50th price): sum(1..50)/50 = 1275/50 = 25.5
    assert sma50[49] == 25.5
    # Bar 59 (60th price): sum(11..60)/50 = 1775/50 = 35.5
    assert sma50[59] == 35.5
    assert get_latest_sma(prices, period=50) == 35.5


def test_sma_insufficient_data():
    """Verify SMA returns all None when data length < period."""
    prices = [10.0] * 30
    sma50 = calculate_sma(prices, period=50)
    assert len(sma50) == 30
    assert all(v is None for v in sma50)
    assert get_latest_sma(prices, period=50) is None

    assert calculate_sma([], period=50) == []
    assert get_latest_sma([], period=50) is None


def test_sma_from_candles():
    """Verify calculate_sma_from_candles extracts close prices correctly."""
    candles = _create_candles([50.0] * 55)
    sma50 = calculate_sma_from_candles(candles, period=50)
    assert len(sma50) == 55
    assert sma50[-1] == 50.0


# =====================================================================
# 3. RSI Tests (RSI 14 with Wilder's Smoothing)
# =====================================================================


def test_rsi_wilder_published_reference_data():
    """Verify RSI 14 against J. Welles Wilder's textbook published reference dataset (1978)."""
    # Classic dataset from Wilder's "New Concepts in Technical Trading Systems"
    wilder_prices = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
        46.00,
    ]
    rsi = calculate_rsi(wilder_prices, period=14)

    assert len(rsi) == 16
    # Indices 0 to 13 (first 14 prices) must be None
    for i in range(14):
        assert rsi[i] is None

    # Index 14 (15th price, 46.28) -> expected ~70.46
    assert rsi[14] is not None
    assert pytest.approx(rsi[14], abs=0.1) == 70.46

    # Index 15 (16th price, 46.00) -> expected ~66.25
    assert rsi[15] is not None
    assert pytest.approx(rsi[15], abs=0.1) == 66.25
    assert get_latest_rsi(wilder_prices, period=14) == rsi[-1]


def test_rsi_monotonically_increasing():
    """Verify RSI is 100 when prices strictly increase (0 losses)."""
    prices = [100.0 + i * 2.0 for i in range(25)]
    rsi = calculate_rsi(prices, period=14)
    assert rsi[-1] == 100.0


def test_rsi_monotonically_decreasing():
    """Verify RSI is 0 when prices strictly decrease (0 gains)."""
    prices = [200.0 - i * 2.0 for i in range(25)]
    rsi = calculate_rsi(prices, period=14)
    assert rsi[-1] == 0.0


def test_rsi_flat_zero_volatility():
    """Verify RSI returns neutral 50.0 when prices are completely flat."""
    prices = [150.0] * 30
    rsi = calculate_rsi(prices, period=14)
    assert rsi[-1] == 50.0


def test_rsi_boundedness():
    """Verify RSI is strictly bounded between 0.0 and 100.0."""
    import random

    random.seed(42)
    prices = [100.0]
    for _ in range(100):
        prices.append(prices[-1] + random.uniform(-5.0, 5.0))

    rsi = calculate_rsi(prices, period=14)
    valid_rsi = [v for v in rsi if v is not None]
    assert len(valid_rsi) > 0
    for val in valid_rsi:
        assert 0.0 <= val <= 100.0


def test_rsi_insufficient_data():
    """Verify RSI returns None when prices count <= period."""
    prices = [100.0 + i for i in range(14)]
    rsi = calculate_rsi(prices, period=14)
    assert len(rsi) == 14
    assert all(v is None for v in rsi)
    assert get_latest_rsi(prices, period=14) is None


def test_rsi_from_candles():
    """Verify calculate_rsi_from_candles works with CandleData list."""
    candles = _create_candles([100.0 + i for i in range(30)])
    rsi = calculate_rsi_from_candles(candles, period=14)
    assert len(rsi) == 30
    assert rsi[-1] == 100.0


# =====================================================================
# 4. MACD Tests (Fast 12, Slow 26, Signal 9)
# =====================================================================


def test_macd_flat_zero_volatility():
    """Verify MACD on constant price produces 0.0 for macd, signal, and histogram."""
    prices = [500.0] * 60
    macd_line, sig_line, hist = calculate_macd(prices, 12, 26, 9)

    assert len(macd_line) == 60
    assert len(sig_line) == 60
    assert len(hist) == 60

    assert macd_line[-1] == 0.0
    assert sig_line[-1] == 0.0
    assert hist[-1] == 0.0

    latest = get_latest_macd(prices, 12, 26, 9)
    assert latest.macd == 0.0
    assert latest.signal == 0.0
    assert latest.histogram == 0.0


def test_macd_bullish_trend():
    """Verify MACD reflects positive momentum in accelerating uptrend."""
    # Exponentially accelerating uptrend
    prices = [100.0 * (1.02**i) for i in range(60)]
    macd_line, sig_line, hist = calculate_macd(prices, 12, 26, 9)

    # In accelerating uptrend, Fast EMA > Slow EMA -> MACD > 0
    assert macd_line[-1] is not None
    assert macd_line[-1] > 0
    assert sig_line[-1] is not None
    assert sig_line[-1] > 0
    assert hist[-1] is not None
    assert hist[-1] > 0


def test_macd_insufficient_data():
    """Verify MACD handles fewer bars than slow_period and signal_period."""
    # Fewer than 26 bars -> All None
    short_prices = [100.0 + i for i in range(20)]
    m_short, s_short, h_short = calculate_macd(short_prices, 12, 26, 9)
    assert all(v is None for v in m_short)
    assert all(v is None for v in s_short)
    assert all(v is None for v in h_short)

    # 30 bars (>= 26, but < 26 + 9 - 1) -> MACD line has values, but Signal is None
    mid_prices = [100.0 + i for i in range(30)]
    m_mid, s_mid, h_mid = calculate_macd(mid_prices, 12, 26, 9)
    assert m_mid[-1] is not None
    assert s_mid[-1] is None
    assert h_mid[-1] is None

    # Empty
    m_empty, s_empty, h_empty = calculate_macd([], 12, 26, 9)
    assert m_empty == []
    assert s_empty == []
    assert h_empty == []


def test_macd_invalid_parameters():
    """Verify ValueError on invalid MACD parameter configurations."""
    with pytest.raises(ValueError, match="must be >= 1"):
        calculate_macd([100.0] * 50, fast_period=0, slow_period=26, signal_period=9)

    with pytest.raises(ValueError, match="strictly less than slow_period"):
        calculate_macd([100.0] * 50, fast_period=26, slow_period=26, signal_period=9)

    with pytest.raises(ValueError, match="strictly less than slow_period"):
        calculate_macd([100.0] * 50, fast_period=30, slow_period=26, signal_period=9)


def test_macd_from_candles():
    """Verify calculate_macd_from_candles operates correctly on CandleData."""
    candles = _create_candles([100.0 + i * 0.5 for i in range(50)])
    m_l, s_l, h_l = calculate_macd_from_candles(candles, 12, 26, 9)
    assert len(m_l) == 50
    assert m_l[-1] is not None
    assert s_l[-1] is not None
    assert h_l[-1] is not None


# =====================================================================
# 5. ATR and ATRP Tests (ATR 14 with Wilder's Smoothing)
# =====================================================================


def test_true_range_calculation():
    """Verify True Range computes max(H-L, |H-Cp|, |L-Cp|)."""
    highs = [105.0, 110.0, 102.0]
    lows = [100.0, 95.0, 98.0]
    closes = [102.0, 96.0, 101.0]

    tr = calculate_true_range(highs, lows, closes)
    assert len(tr) == 3
    # Bar 0: H0 - L0 = 105 - 100 = 5.0
    assert tr[0] == 5.0
    # Bar 1: max(110-95=15, |110-102|=8, |95-102|=7) = 15.0
    assert tr[1] == 15.0
    # Bar 2: max(102-98=4, |102-96|=6, |98-96|=2) = 6.0
    assert tr[2] == 6.0


def test_atr_wilder_published_reference_data():
    """Verify ATR 14 against J. Welles Wilder's textbook published reference dataset (1978)."""
    # Classic dataset from Wilder's "New Concepts in Technical Trading Systems"
    wilder_data = [
        (45.62, 44.50, 44.87),  # 1
        (45.00, 44.12, 44.25),  # 2
        (44.87, 44.12, 44.62),  # 3
        (45.50, 44.25, 45.12),  # 4
        (45.87, 45.12, 45.50),  # 5
        (46.00, 45.37, 45.87),  # 6
        (46.75, 45.87, 46.50),  # 7
        (47.00, 46.25, 46.87),  # 8
        (47.25, 46.50, 47.00),  # 9
        (47.12, 46.62, 46.75),  # 10
        (47.37, 46.75, 47.12),  # 11
        (47.25, 46.50, 46.75),  # 12
        (47.12, 46.37, 46.87),  # 13
        (47.50, 46.62, 47.37),  # 14
        (47.50, 46.87, 47.00),  # 15
        (47.00, 46.00, 46.25),  # 16
    ]

    highs = [d[0] for d in wilder_data]
    lows = [d[1] for d in wilder_data]
    closes = [d[2] for d in wilder_data]

    atr = calculate_atr(highs, lows, closes, period=14)
    atrp = calculate_atrp(highs, lows, closes, period=14)

    assert len(atr) == 16
    assert len(atrp) == 16

    # First 13 bars (indices 0..12) must be None
    for i in range(13):
        assert atr[i] is None
        assert atrp[i] is None

    # Bar index 13 (14th price): expected ~0.8043
    assert atr[13] is not None
    assert pytest.approx(atr[13], abs=0.01) == 0.8043
    assert atrp[13] is not None
    # ATRP: (0.8043 / 47.37) * 100 = ~1.6979%
    assert pytest.approx(atrp[13], abs=0.02) == 1.70

    # Bar index 14 (15th price): expected ~0.7918
    assert atr[14] is not None
    assert pytest.approx(atr[14], abs=0.01) == 0.7918

    # Bar index 15 (16th price): expected ~0.8067
    assert atr[15] is not None
    assert pytest.approx(atr[15], abs=0.01) == 0.8067


def test_atr_zero_volatility_flat_prices():
    """Verify ATR and ATRP on constant flat price are exactly 0.0."""
    highs = [100.0] * 20
    lows = [100.0] * 20
    closes = [100.0] * 20

    atr = calculate_atr(highs, lows, closes, period=14)
    atrp = calculate_atrp(highs, lows, closes, period=14)

    assert atr[-1] == 0.0
    assert atrp[-1] == 0.0


def test_atr_insufficient_data():
    """Verify ATR and ATRP return None when data length < period."""
    highs = [100.0 + i for i in range(10)]
    lows = [95.0 + i for i in range(10)]
    closes = [98.0 + i for i in range(10)]

    atr = calculate_atr(highs, lows, closes, period=14)
    atrp = calculate_atrp(highs, lows, closes, period=14)

    assert len(atr) == 10
    assert all(v is None for v in atr)
    assert all(v is None for v in atrp)

    assert calculate_atr([], [], [], period=14) == []
    assert calculate_atrp([], [], [], period=14) == []


def test_atrp_zero_or_invalid_close():
    """Verify ATRP gracefully handles zero or negative close prices without error."""
    highs = [10.0] * 15
    lows = [5.0] * 15
    closes = [10.0] * 14 + [0.0]  # Last close is 0.0

    atrp = calculate_atrp(highs, lows, closes, period=14)
    assert atrp[13] is not None  # 14th bar has positive close
    assert atrp[14] is None  # 15th bar close is 0.0 -> None


def test_atr_invalid_parameters():
    """Verify ValueError on invalid ATR parameter configurations."""
    with pytest.raises(ValueError, match="period must be >= 1"):
        calculate_atr([100.0], [90.0], [95.0], period=0)

    with pytest.raises(ValueError, match="identical lengths"):
        calculate_atr([100.0, 101.0], [90.0], [95.0, 96.0], period=14)


def test_atr_from_candles():
    """Verify calculate_atr_from_candles and get_latest_atr helpers."""
    candles = _create_candles([100.0 + i for i in range(30)])
    atr_s, atrp_s = calculate_atr_from_candles(candles, period=14)

    assert len(atr_s) == 30
    assert len(atrp_s) == 30
    assert atr_s[-1] is not None
    assert atrp_s[-1] is not None

    lat_atr, lat_atrp = get_latest_atr(candles, period=14)
    assert lat_atr == atr_s[-1]
    assert lat_atrp == atrp_s[-1]

    # Empty candles
    e_atr, e_atrp = get_latest_atr([], period=14)
    assert e_atr is None
    assert e_atrp is None


# =====================================================================
# 6. QuantitativeIndicatorEngine & Snapshot Integration Tests
# =====================================================================


def test_indicator_engine_full_series_and_snapshot():
    """Verify QuantitativeIndicatorEngine computes aligned series and complete snapshot."""
    engine = get_indicator_engine()

    # 100 candles simulating RELIANCE 15m price movements
    prices = [2400.0 + i * 1.5 + (i % 5) * 2.0 for i in range(100)]
    candles = _create_candles(prices)

    series = engine.compute_series(symbol="RELIANCE", timeframe="15m", candles=candles)

    assert series.symbol == "RELIANCE"
    assert series.timeframe == "15m"
    assert series.count == 100
    assert len(series.timestamps) == 100
    assert len(series.closes) == 100
    assert len(series.ema9) == 100
    assert len(series.ema20) == 100
    assert len(series.sma50) == 100
    assert len(series.rsi14) == 100
    assert len(series.macd_line) == 100
    assert len(series.macd_signal) == 100
    assert len(series.macd_histogram) == 100
    assert len(series.atr14) == 100
    assert len(series.atrp14) == 100

    # Verify latest values exist and are populated
    snapshot = engine.compute_snapshot(symbol="RELIANCE", timeframe="15m", candles=candles)
    assert snapshot is not None
    assert snapshot.close == prices[-1]
    assert snapshot.ema9 == series.ema9[-1]
    assert snapshot.ema20 == series.ema20[-1]
    assert snapshot.sma50 == series.sma50[-1]
    assert snapshot.rsi14 == series.rsi14[-1]
    assert snapshot.macd == series.macd_line[-1]
    assert snapshot.macd_signal == series.macd_signal[-1]
    assert snapshot.macd_histogram == series.macd_histogram[-1]
    assert snapshot.atr14 == series.atr14[-1]
    assert snapshot.atrp14 == series.atrp14[-1]

    assert snapshot.ema9 is not None
    assert snapshot.ema20 is not None
    assert snapshot.sma50 is not None
    assert snapshot.rsi14 is not None
    assert snapshot.macd is not None
    assert snapshot.macd_signal is not None
    assert snapshot.macd_histogram is not None
    assert snapshot.atr14 is not None
    assert snapshot.atrp14 is not None


def test_indicator_engine_short_history():
    """Verify engine gracefully handles short candle history (< 50 bars)."""
    engine = QuantitativeIndicatorEngine()
    # 25 candles: Enough for EMA9, EMA20, RSI14, ATR14, but not SMA50 or full MACD signal
    candles = _create_candles([2500.0 + i for i in range(25)])

    snapshot = engine.compute_snapshot(symbol="TCS", timeframe="15m", candles=candles)
    assert snapshot is not None
    assert snapshot.ema9 is not None
    assert snapshot.ema20 is not None
    assert snapshot.rsi14 is not None
    assert snapshot.atr14 is not None
    assert snapshot.atrp14 is not None
    assert snapshot.sma50 is None  # < 50 bars
    assert snapshot.macd is None  # < 26 bars


def test_indicator_engine_empty_input():
    """Verify engine handles empty candle lists without crashing."""
    engine = QuantitativeIndicatorEngine()
    series = engine.compute_series("INFY", "15m", [])
    assert series.count == 0
    assert series.timestamps == []
    assert series.atr14 == []
    assert series.atrp14 == []

    snapshot = engine.compute_snapshot("INFY", "15m", [])
    assert snapshot is None


def test_deterministic_reproducibility():
    """Verify consecutive calculations on identical input produce exact matching results."""
    engine = get_indicator_engine()
    prices = [1000.0 + (i * 3.7) % 50 for i in range(80)]
    candles = _create_candles(prices)

    run1 = engine.compute_snapshot("SBIN", "15m", candles)
    run2 = engine.compute_snapshot("SBIN", "15m", candles)

    assert run1 == run2
    assert run1.model_dump() == run2.model_dump()
