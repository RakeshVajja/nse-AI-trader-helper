"""Unit tests for Phase 4B: Deterministic Descriptive Market Regime Classification:
- Trend Regime: 3-of-4 Majority Voting (BULLISH / BEARISH / SIDEWAYS)
- Volatility Regime: 100-Bar Historical Rolling Percentiles (HIGH / NORMAL / LOW)
- Strict No-Look-Ahead & Independent Warmup Semantics
- Engine Series & Snapshot Integration
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.indicators.engine import QuantitativeIndicatorEngine, get_indicator_engine
from app.indicators.regime import (
    classify_market_regime_snapshot,
    classify_trend_bar,
    classify_volatility_bar,
    compute_market_regimes_series,
)
from app.indicators.schemas import (
    TrendRegime,
    VolatilityRegime,
)
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
# 1. Trend Regime Classification Tests (3-of-4 Majority Voting)
# =====================================================================


def test_trend_regime_4_bullish_votes():
    """Verify 4-0 bullish signals classify as BULLISH."""
    # Close > SMA50, EMA9 > EMA20, MACD > 0, RSI14 > 50
    regime, details = classify_trend_bar(
        close=105.0,
        sma50=100.0,
        ema9=104.0,
        ema20=102.0,
        macd=1.5,
        rsi14=65.0,
    )
    assert regime == TrendRegime.BULLISH
    assert details.bullish_votes == 4
    assert details.bearish_votes == 0
    assert details.close_vs_sma50 == "BULLISH"
    assert details.ema9_vs_ema20 == "BULLISH"
    assert details.macd_vs_zero == "BULLISH"
    assert details.rsi14_vs_50 == "BULLISH"


def test_trend_regime_3_bullish_1_bearish():
    """Verify 3 bullish + 1 bearish signals classify as BULLISH."""
    # Close > SMA50 (B), EMA9 > EMA20 (B), MACD > 0 (B), RSI14 < 50 (BEAR)
    regime, details = classify_trend_bar(
        close=105.0,
        sma50=100.0,
        ema9=104.0,
        ema20=102.0,
        macd=1.5,
        rsi14=45.0,
    )
    assert regime == TrendRegime.BULLISH
    assert details.bullish_votes == 3
    assert details.bearish_votes == 1


def test_trend_regime_3_bullish_1_neutral():
    """Verify 3 bullish + 1 neutral signals classify as BULLISH."""
    # Close == SMA50 (NEUTRAL), EMA9 > EMA20 (B), MACD > 0 (B), RSI14 > 50 (B)
    regime, details = classify_trend_bar(
        close=100.0,
        sma50=100.0,
        ema9=104.0,
        ema20=102.0,
        macd=1.5,
        rsi14=60.0,
    )
    assert regime == TrendRegime.BULLISH
    assert details.bullish_votes == 3
    assert details.bearish_votes == 0
    assert details.close_vs_sma50 == "NEUTRAL"


def test_trend_regime_4_bearish_votes():
    """Verify 0-4 bearish signals classify as BEARISH."""
    # Close < SMA50, EMA9 < EMA20, MACD < 0, RSI14 < 50
    regime, details = classify_trend_bar(
        close=95.0,
        sma50=100.0,
        ema9=96.0,
        ema20=98.0,
        macd=-1.5,
        rsi14=35.0,
    )
    assert regime == TrendRegime.BEARISH
    assert details.bullish_votes == 0
    assert details.bearish_votes == 4


def test_trend_regime_3_bearish_1_bullish():
    """Verify 3 bearish + 1 bullish signals classify as BEARISH."""
    # Close < SMA50 (BEAR), EMA9 < EMA20 (BEAR), MACD < 0 (BEAR), RSI14 > 50 (BULL)
    regime, details = classify_trend_bar(
        close=95.0,
        sma50=100.0,
        ema9=96.0,
        ema20=98.0,
        macd=-1.5,
        rsi14=55.0,
    )
    assert regime == TrendRegime.BEARISH
    assert details.bullish_votes == 1
    assert details.bearish_votes == 3


def test_trend_regime_2_2_tie_is_sideways():
    """Verify 2 bullish + 2 bearish signals result in SIDEWAYS."""
    # Close > SMA50 (B), EMA9 > EMA20 (B), MACD < 0 (BEAR), RSI14 < 50 (BEAR)
    regime, details = classify_trend_bar(
        close=105.0,
        sma50=100.0,
        ema9=104.0,
        ema20=102.0,
        macd=-0.5,
        rsi14=45.0,
    )
    assert regime == TrendRegime.SIDEWAYS
    assert details.bullish_votes == 2
    assert details.bearish_votes == 2


def test_trend_regime_2_1_1_split_is_sideways():
    """Verify 2 bullish + 1 bearish + 1 neutral signals result in SIDEWAYS."""
    # Close > SMA50 (B), EMA9 > EMA20 (B), MACD < 0 (BEAR), RSI14 == 50 (NEUTRAL)
    regime, details = classify_trend_bar(
        close=105.0,
        sma50=100.0,
        ema9=104.0,
        ema20=102.0,
        macd=-0.5,
        rsi14=50.0,
    )
    assert regime == TrendRegime.SIDEWAYS
    assert details.bullish_votes == 2
    assert details.bearish_votes == 1


def test_trend_regime_warmup_returns_none():
    """Verify if ANY of the 4 indicators is None, trend_regime is None."""
    # Missing SMA50 (warmup)
    regime, details = classify_trend_bar(
        close=105.0,
        sma50=None,
        ema9=104.0,
        ema20=102.0,
        macd=1.5,
        rsi14=60.0,
    )
    assert regime is None
    assert details.close_vs_sma50 is None
    assert details.bullish_votes == 3

    # Missing MACD
    regime2, details2 = classify_trend_bar(
        close=105.0,
        sma50=100.0,
        ema9=104.0,
        ema20=102.0,
        macd=None,
        rsi14=60.0,
    )
    assert regime2 is None
    assert details2.macd_vs_zero is None


# =====================================================================
# 2. Volatility Regime Classification Tests (100-Bar Historical Percentiles)
# =====================================================================


def test_volatility_regime_insufficient_history_returns_none():
    """Verify fewer than 100 valid preceding observations strictly returns None (never NORMAL)."""
    # 99 historical observations (< 100)
    history_99 = [1.5 + (i * 0.01) for i in range(99)]
    current_atrp = 2.0

    regime, metrics = classify_volatility_bar(current_atrp, history_99)
    assert regime is None
    assert metrics.current_atrp14 == 2.0
    assert metrics.p20_threshold is None
    assert metrics.p80_threshold is None
    assert metrics.sample_count == 99


def test_volatility_regime_none_current_atrp_returns_none():
    """Verify None current ATRP returns None volatility regime."""
    history_100 = [float(i) for i in range(1, 101)]
    regime, metrics = classify_volatility_bar(None, history_100)
    assert regime is None
    assert metrics.current_atrp14 is None


def test_volatility_regime_percentile_classifications():
    """Verify LOW (<= p20), HIGH (>= p80), and NORMAL classifications on 100-bar sample."""
    # 100 values from 1.0 to 100.0: p20 = 20.8, p80 = 80.2
    history_100 = [float(i) for i in range(1, 101)]

    # 1. Below p20 -> LOW
    reg_low, met_low = classify_volatility_bar(15.0, history_100)
    assert reg_low == VolatilityRegime.LOW
    assert met_low.p20_threshold == pytest.approx(20.8, abs=0.1)
    assert met_low.p80_threshold == pytest.approx(80.2, abs=0.1)
    assert met_low.sample_count == 100

    # 2. Above p80 -> HIGH
    reg_high, _ = classify_volatility_bar(85.0, history_100)
    assert reg_high == VolatilityRegime.HIGH

    # 3. In-between -> NORMAL
    reg_norm, _ = classify_volatility_bar(50.0, history_100)
    assert reg_norm == VolatilityRegime.NORMAL

    # 4. Boundary cases
    p20_val = met_low.p20_threshold
    assert p20_val is not None
    reg_p20, _ = classify_volatility_bar(p20_val, history_100)
    assert reg_p20 == VolatilityRegime.LOW

    p80_val = met_low.p80_threshold
    assert p80_val is not None
    reg_p80, _ = classify_volatility_bar(p80_val, history_100)
    assert reg_p80 == VolatilityRegime.HIGH


def test_volatility_regime_unrounded_percentile_boundary_classification():
    """Verify that classification uses full-precision unrounded percentile thresholds.

    Demonstrates that a current ATRP value falling between the unrounded percentile
    and the 4-decimal rounded threshold is correctly classified according to the
    unrounded mathematical value.
    """
    # Construct 100 values where x[19] = 1.00001 and x[20] = 2.00001
    # Linear interpolation at index 19.8 yields p20_raw = 1.00001 + 0.8 * 1.0 = 1.80001
    # The 4-decimal rounded threshold is 1.8000
    history = [1.0] * 19 + [1.00001, 2.00001] + [5.0] * 79
    assert len(history) == 100

    # 1. current_atrp = 1.800005 (< 1.80001 raw threshold, but > 1.8000 rounded threshold)
    # With raw unrounded classification, 1.800005 <= 1.80001 -> LOW
    # If rounded threshold (1.8000) were used, 1.800005 > 1.8000 -> incorrectly NORMAL
    reg_low, met_low = classify_volatility_bar(1.800005, history)
    assert reg_low == VolatilityRegime.LOW
    assert met_low.p20_threshold == 1.8000

    # 2. current_atrp = 1.800015 (> 1.80001 raw threshold)
    # With raw unrounded classification, 1.800015 > 1.80001 -> NORMAL
    reg_norm, met_norm = classify_volatility_bar(1.800015, history)
    assert reg_norm == VolatilityRegime.NORMAL
    assert met_norm.p20_threshold == 1.8000

    # Construct p80 boundary test:
    # x[79] = 10.00001, x[80] = 11.00001 -> index 79.2 yields p80_raw = 10.00001 + 0.2 * 1.0 = 10.20001
    # The 4-decimal rounded threshold is 10.2000
    history_p80 = [1.0] * 79 + [10.00001, 11.00001] + [20.0] * 19
    assert len(history_p80) == 100

    # current_atrp = 10.200005 (< 10.20001 raw threshold, but > 10.2000 rounded threshold)
    # With raw unrounded classification, 10.200005 < 10.20001 -> NORMAL
    # If rounded threshold (10.2000) were used, 10.200005 >= 10.2000 -> incorrectly HIGH
    reg_p80_norm, met_p80_norm = classify_volatility_bar(10.200005, history_p80)
    assert reg_p80_norm == VolatilityRegime.NORMAL
    assert met_p80_norm.p80_threshold == 10.2000

    # current_atrp = 10.200015 (>= 10.20001 raw threshold) -> HIGH
    reg_p80_high, met_p80_high = classify_volatility_bar(10.200015, history_p80)
    assert reg_p80_high == VolatilityRegime.HIGH
    assert met_p80_high.p80_threshold == 10.2000


def test_volatility_regime_window_sliding_uses_last_100():
    """Verify when history > 100, exactly the previous 100 valid observations are used."""
    # 150 values: 1..50 are 1.0, 51..150 are 10.0..109.0
    history_150 = [1.0] * 50 + [float(i) for i in range(10, 110)]
    assert len(history_150) == 150

    # The last 100 values are [10, 11, ..., 109], so p20 is ~29.8, not ~1.0
    _, metrics = classify_volatility_bar(50.0, history_150)
    assert metrics.sample_count == 100
    assert metrics.p20_threshold is not None
    assert metrics.p20_threshold > 20.0


def test_volatility_regime_zero_dispersion_flat_series():
    """Verify flat zero-dispersion historical series (p20 == p80) classifies cleanly."""
    flat_100 = [2.5] * 100
    # Current value equals baseline -> NORMAL
    reg_eq, met_eq = classify_volatility_bar(2.5, flat_100)
    assert reg_eq == VolatilityRegime.NORMAL
    assert met_eq.p20_threshold == 2.5
    assert met_eq.p80_threshold == 2.5

    # Current value lower than flat baseline -> LOW
    reg_lt, _ = classify_volatility_bar(1.0, flat_100)
    assert reg_lt == VolatilityRegime.LOW

    # Current value higher than flat baseline -> HIGH
    reg_gt, _ = classify_volatility_bar(4.0, flat_100)
    assert reg_gt == VolatilityRegime.HIGH


# =====================================================================
# 3. Strict No-Look-Ahead & Independent Warmup Semantics Tests
# =====================================================================


def test_compute_market_regimes_series_lookahead_prevention():
    """Verify compute_market_regimes_series passes only prior observations strictly before t."""
    # Construct synthetic series of 150 candles
    prices = [100.0 + i for i in range(150)]
    ema9_s = [100.0 + i for i in range(150)]
    ema20_s = [100.0 + i for i in range(150)]
    sma50_s = [100.0 + i for i in range(150)]
    rsi14_s = [60.0] * 150
    macd_s = [1.0] * 150
    atrp14_s = [float(i % 20 + 1) for i in range(150)]

    tr_regimes, vol_regimes, tr_details, vol_metrics = compute_market_regimes_series(
        closes=prices,
        ema9_series=ema9_s,
        ema20_series=ema20_s,
        sma50_series=sma50_s,
        rsi14_series=rsi14_s,
        macd_series=macd_s,
        atrp14_series=atrp14_s,
    )

    assert len(tr_regimes) == 150
    assert len(vol_regimes) == 150
    assert len(tr_details) == 150

    # Bar 0 has 0 historical ATRP observations strictly before it -> None
    assert vol_regimes[0] is None
    assert vol_metrics[0] is not None
    assert vol_metrics[0].sample_count == 0

    # Bar 99 has 99 historical observations strictly before it -> None (< 100)
    assert vol_regimes[99] is None
    assert vol_metrics[99] is not None
    assert vol_metrics[99].sample_count == 99

    # Bar 100 has exactly 100 historical observations strictly before it -> valid classification
    assert vol_regimes[100] is not None
    assert vol_metrics[100] is not None
    assert vol_metrics[100].sample_count == 100


def test_independent_warmup_trend_vs_volatility():
    """Verify Trend is classified at bar 60 (since >= 50 bars) while Volatility is None (since < 100 prior ATRPs)."""
    # 70 candles
    prices = [1000.0 + i * 2.0 for i in range(70)]
    candles = _create_candles(prices)

    engine = get_indicator_engine()
    series = engine.compute_series(symbol="RELIANCE", timeframe="15m", candles=candles)

    # At bar 60 (index 59):
    # - SMA50 is available (starts at index 49)
    # - MACD, RSI, EMA9, EMA20 are available
    # -> trend_regime is populated
    assert series.trend_regimes[59] == TrendRegime.BULLISH

    # - ATRP14 starts at index 13, so by index 59 there are only 59 - 13 = 46 valid prior ATRP values (< 100)
    # -> volatility_regime MUST be None
    assert series.volatility_regimes[59] is None

    # Snapshot at 70 candles also has trend_regime but volatility_regime is None
    snapshot = engine.compute_snapshot(symbol="RELIANCE", timeframe="15m", candles=candles)
    assert snapshot is not None
    assert snapshot.trend_regime == TrendRegime.BULLISH
    assert snapshot.volatility_regime is None


# =====================================================================
# 4. Engine Series, Snapshot & Reproducibility Tests
# =====================================================================


def test_engine_full_mature_series_and_snapshot():
    """Verify QuantitativeIndicatorEngine computes aligned regimes on 150 mature candles."""
    engine = get_indicator_engine()

    # 150 candles: Sufficient for both Trend (>= 50 bars) and Volatility (>= 114 bars)
    prices = [2500.0 + (i * 1.2) + ((i % 7) * 2.0) for i in range(150)]
    candles = _create_candles(prices)

    series = engine.compute_series(symbol="TCS", timeframe="15m", candles=candles)

    assert series.count == 150
    assert len(series.trend_regimes) == 150
    assert len(series.volatility_regimes) == 150

    # At the end of the series, both regimes must be populated
    assert series.trend_regimes[-1] is not None
    assert series.volatility_regimes[-1] is not None

    snapshot = engine.compute_snapshot(symbol="TCS", timeframe="15m", candles=candles)
    assert snapshot is not None
    assert snapshot.trend_regime == series.trend_regimes[-1]
    assert snapshot.volatility_regime == series.volatility_regimes[-1]
    assert snapshot.trend_details is not None
    assert snapshot.volatility_details is not None
    assert snapshot.volatility_details.sample_count == 100

    # Standalone regime snapshot helper
    reg_snap = classify_market_regime_snapshot(candles)
    assert reg_snap is not None
    assert reg_snap.trend_regime == snapshot.trend_regime
    assert reg_snap.volatility_regime == snapshot.volatility_regime


def test_engine_empty_input():
    """Verify empty candle list returns empty series and None snapshot."""
    engine = QuantitativeIndicatorEngine()
    series = engine.compute_series("INFY", "15m", [])
    assert series.count == 0
    assert series.trend_regimes == []
    assert series.volatility_regimes == []

    snapshot = engine.compute_snapshot("INFY", "15m", [])
    assert snapshot is None

    reg_snap = classify_market_regime_snapshot([])
    assert reg_snap is None


def test_regime_deterministic_reproducibility():
    """Verify consecutive regime classifications on identical data yield exact matching results."""
    engine = get_indicator_engine()
    prices = [1500.0 + ((i * 4.3) % 40) for i in range(130)]
    candles = _create_candles(prices)

    run1 = engine.compute_snapshot("HDFCBANK", "15m", candles)
    run2 = engine.compute_snapshot("HDFCBANK", "15m", candles)

    assert run1 is not None and run2 is not None
    assert run1.trend_regime == run2.trend_regime
    assert run1.volatility_regime == run2.volatility_regime
    assert run1.trend_details == run2.trend_details
    assert run1.volatility_details == run2.volatility_details
    assert run1.model_dump() == run2.model_dump()
