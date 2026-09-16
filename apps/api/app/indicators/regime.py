"""Deterministic descriptive market regime classifier (Trend and Volatility)."""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from app.indicators.schemas import (
    MarketRegimeSnapshot,
    TrendRegime,
    TrendSignalDetails,
    VolatilityMetrics,
    VolatilityRegime,
)
from app.market_data.schema import CandleData


def classify_trend_bar(
    close: Optional[float],
    sma50: Optional[float],
    ema9: Optional[float],
    ema20: Optional[float],
    macd: Optional[float],
    rsi14: Optional[float],
) -> Tuple[Optional[TrendRegime], TrendSignalDetails]:
    """Classify descriptive trend regime for a single bar using 3-of-4 majority voting.

    Indicator Conditions evaluated:
    1. Close vs SMA50 (Bullish: Close > SMA50, Bearish: Close < SMA50)
    2. EMA9 vs EMA20 (Bullish: EMA9 > EMA20, Bearish: EMA9 < EMA20)
    3. MACD vs Zero (Bullish: MACD > 0, Bearish: MACD < 0)
    4. RSI14 vs 50 (Bullish: RSI14 > 50, Bearish: RSI14 < 50)

    Majority Voting Rule:
    - >= 3 Bullish signals -> BULLISH
    - >= 3 Bearish signals -> BEARISH
    - Otherwise -> SIDEWAYS
    - Warmup: If any of the required indicator values is None -> trend_regime = None

    Args:
        close: Close price at current candle.
        sma50: SMA50 value at current candle.
        ema9: EMA9 value at current candle.
        ema20: EMA20 value at current candle.
        macd: MACD line value at current candle.
        rsi14: RSI14 value at current candle.

    Returns:
        Tuple of (Optional[TrendRegime], TrendSignalDetails).
    """
    # Evaluate Condition 1: Close vs SMA50
    c1: Optional[str] = None
    if close is not None and sma50 is not None:
        if close > sma50:
            c1 = "BULLISH"
        elif close < sma50:
            c1 = "BEARISH"
        else:
            c1 = "NEUTRAL"

    # Evaluate Condition 2: EMA9 vs EMA20
    c2: Optional[str] = None
    if ema9 is not None and ema20 is not None:
        if ema9 > ema20:
            c2 = "BULLISH"
        elif ema9 < ema20:
            c2 = "BEARISH"
        else:
            c2 = "NEUTRAL"

    # Evaluate Condition 3: MACD vs Zero
    c3: Optional[str] = None
    if macd is not None:
        if macd > 0.0:
            c3 = "BULLISH"
        elif macd < 0.0:
            c3 = "BEARISH"
        else:
            c3 = "NEUTRAL"

    # Evaluate Condition 4: RSI14 vs 50
    c4: Optional[str] = None
    if rsi14 is not None:
        if rsi14 > 50.0:
            c4 = "BULLISH"
        elif rsi14 < 50.0:
            c4 = "BEARISH"
        else:
            c4 = "NEUTRAL"

    signals = [c1, c2, c3, c4]
    bullish_votes = sum(1 for s in signals if s == "BULLISH")
    bearish_votes = sum(1 for s in signals if s == "BEARISH")

    details = TrendSignalDetails(
        close_vs_sma50=c1,
        ema9_vs_ema20=c2,
        macd_vs_zero=c3,
        rsi14_vs_50=c4,
        bullish_votes=bullish_votes,
        bearish_votes=bearish_votes,
    )

    # Warmup check: If any condition is incomplete due to missing lookback -> None
    if any(s is None for s in signals):
        return None, details

    if bullish_votes >= 3:
        return TrendRegime.BULLISH, details
    if bearish_votes >= 3:
        return TrendRegime.BEARISH, details
    return TrendRegime.SIDEWAYS, details


def classify_volatility_bar(
    current_atrp14: Optional[float],
    historical_atrp14_observations: Sequence[Optional[float]],
) -> Tuple[Optional[VolatilityRegime], VolatilityMetrics]:
    """Classify descriptive volatility regime for a candle against previous 100 valid observations.

    Rule:
    - Uses the previous 100 VALID ATRP14 observations strictly before current candle t.
    - Current candle ATRP14 is strictly excluded from the reference lookback distribution.
    - If fewer than 100 valid preceding observations exist -> volatility_regime = None (Warmup).
    - Thresholds: p20 (20th percentile) and p80 (80th percentile) computed on the 100-bar sample.
    - Classification:
        ATRP14 <= p20 -> LOW
        ATRP14 >= p80 -> HIGH
        p20 < ATRP14 < p80 -> NORMAL

    Args:
        current_atrp14: ATRP14 value at current candle t.
        historical_atrp14_observations: Sequence of historical ATRP14 values strictly before t.

    Returns:
        Tuple of (Optional[VolatilityRegime], VolatilityMetrics).
    """
    valid_hist = [
        float(v)
        for v in historical_atrp14_observations
        if v is not None and not math.isnan(v) and not math.isinf(v)
    ]

    sample_count = len(valid_hist)

    # Warmup check: Must have current ATRP and at least 100 valid preceding observations
    if current_atrp14 is None or sample_count < 100:
        return None, VolatilityMetrics(
            current_atrp14=current_atrp14,
            p20_threshold=None,
            p80_threshold=None,
            sample_count=sample_count,
        )

    # Take exactly the last 100 valid observations strictly before current candle
    window = valid_hist[-100:]
    p20_raw = float(np.percentile(window, 20, method="linear"))
    p80_raw = float(np.percentile(window, 80, method="linear"))

    # Perform classification using full-precision unrounded percentile thresholds
    if p20_raw == p80_raw:
        if current_atrp14 < p20_raw:
            regime = VolatilityRegime.LOW
        elif current_atrp14 > p80_raw:
            regime = VolatilityRegime.HIGH
        else:
            regime = VolatilityRegime.NORMAL
    elif current_atrp14 <= p20_raw:
        regime = VolatilityRegime.LOW
    elif current_atrp14 >= p80_raw:
        regime = VolatilityRegime.HIGH
    else:
        regime = VolatilityRegime.NORMAL

    # Exposed metrics round the thresholds only for display/storage
    metrics = VolatilityMetrics(
        current_atrp14=current_atrp14,
        p20_threshold=round(p20_raw, 4),
        p80_threshold=round(p80_raw, 4),
        sample_count=len(window),
    )

    return regime, metrics


def compute_market_regimes_series(
    closes: Sequence[float],
    ema9_series: Sequence[Optional[float]],
    ema20_series: Sequence[Optional[float]],
    sma50_series: Sequence[Optional[float]],
    rsi14_series: Sequence[Optional[float]],
    macd_series: Sequence[Optional[float]],
    atrp14_series: Sequence[Optional[float]],
) -> Tuple[
    List[Optional[TrendRegime]],
    List[Optional[VolatilityRegime]],
    List[Optional[TrendSignalDetails]],
    List[Optional[VolatilityMetrics]],
]:
    """Compute aligned time-series of trend and volatility regimes for all candles.

    Strictly enforces no-look-ahead by passing only historical observations strictly
    before candle t for volatility percentiles.
    """
    n = len(closes)
    trend_regimes: List[Optional[TrendRegime]] = []
    vol_regimes: List[Optional[VolatilityRegime]] = []
    trend_details_list: List[Optional[TrendSignalDetails]] = []
    vol_metrics_list: List[Optional[VolatilityMetrics]] = []

    for t in range(n):
        close_t = closes[t] if t < len(closes) else None
        ema9_t = ema9_series[t] if t < len(ema9_series) else None
        ema20_t = ema20_series[t] if t < len(ema20_series) else None
        sma50_t = sma50_series[t] if t < len(sma50_series) else None
        rsi14_t = rsi14_series[t] if t < len(rsi14_series) else None
        macd_t = macd_series[t] if t < len(macd_series) else None
        atrp14_t = atrp14_series[t] if t < len(atrp14_series) else None

        # 1. Trend classification
        tr_regime, tr_details = classify_trend_bar(
            close=close_t,
            sma50=sma50_t,
            ema9=ema9_t,
            ema20=ema20_t,
            macd=macd_t,
            rsi14=rsi14_t,
        )
        trend_regimes.append(tr_regime)
        trend_details_list.append(tr_details)

        # 2. Volatility classification: strictly preceding ATRP14 values before t
        prior_atrp = atrp14_series[:t] if t > 0 else []
        vol_regime, vol_metrics = classify_volatility_bar(
            current_atrp14=atrp14_t,
            historical_atrp14_observations=prior_atrp,
        )
        vol_regimes.append(vol_regime)
        vol_metrics_list.append(vol_metrics)

    return trend_regimes, vol_regimes, trend_details_list, vol_metrics_list


def classify_market_regime_snapshot(
    candles: Sequence[CandleData],
) -> Optional[MarketRegimeSnapshot]:
    """Compute the latest descriptive market regime snapshot from candles."""
    if not candles:
        return None

    from app.indicators.engine import QuantitativeIndicatorEngine

    series = QuantitativeIndicatorEngine.compute_series(symbol="", timeframe="", candles=candles)

    last_candle = candles[-1]
    last_tr = series.trend_regimes[-1] if series.trend_regimes else None
    last_vol = series.volatility_regimes[-1] if series.volatility_regimes else None

    # Re-evaluate details for the last candle
    _, last_tr_details = classify_trend_bar(
        close=last_candle.close,
        sma50=series.sma50[-1] if series.sma50 else None,
        ema9=series.ema9[-1] if series.ema9 else None,
        ema20=series.ema20[-1] if series.ema20 else None,
        macd=series.macd_line[-1] if series.macd_line else None,
        rsi14=series.rsi14[-1] if series.rsi14 else None,
    )

    prior_atrp = series.atrp14[:-1] if len(series.atrp14) > 1 else []
    _, last_vol_metrics = classify_volatility_bar(
        current_atrp14=series.atrp14[-1] if series.atrp14 else None,
        historical_atrp14_observations=prior_atrp,
    )

    return MarketRegimeSnapshot(
        timestamp=last_candle.timestamp,
        trend_regime=last_tr,
        volatility_regime=last_vol,
        trend_details=last_tr_details,
        volatility_details=last_vol_metrics,
    )
