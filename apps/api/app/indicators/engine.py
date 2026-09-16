"""Quantitative technical indicator calculation engine."""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.indicators.atr import calculate_atr_from_candles
from app.indicators.ema import calculate_ema_from_candles
from app.indicators.macd import calculate_macd_from_candles
from app.indicators.regime import (
    classify_market_regime_snapshot,
    classify_trend_bar,
    classify_volatility_bar,
    compute_market_regimes_series,
)
from app.indicators.rsi import calculate_rsi_from_candles
from app.indicators.schemas import (
    IndicatorSeries,
    IndicatorSnapshot,
    MarketRegimeSnapshot,
)
from app.indicators.sma import calculate_sma_from_candles
from app.market_data.schema import CandleData

logger = logging.getLogger(__name__)


class QuantitativeIndicatorEngine:
    """Deterministic quantitative indicator and descriptive market regime engine.

    Calculates:
    - EMA9 (9-period Exponential Moving Average)
    - EMA20 (20-period Exponential Moving Average)
    - SMA50 (50-period Simple Moving Average)
    - RSI14 (14-period Relative Strength Index)
    - MACD (12, 26, 9: Fast EMA, Slow EMA, Signal line, Histogram)
    - ATR14 (14-period Average True Range)
    - ATRP14 (14-period ATR Percentage)
    - TrendRegime (Descriptive 3-of-4 majority voting: BULLISH, BEARISH, SIDEWAYS)
    - VolatilityRegime (Descriptive 100-bar historical ATRP percentile: HIGH, NORMAL, LOW)

    All calculations are strictly deterministic, isolated from external LLM reasoning,
    and optimized for both batch historical time-series processing and single-candle
    state snapshots.
    """

    @staticmethod
    def compute_series(
        symbol: str,
        timeframe: str,
        candles: Sequence[CandleData],
    ) -> IndicatorSeries:
        """Compute time-series for all technical indicators and market regimes.

        Args:
            symbol: Trading symbol (e.g. RELIANCE).
            timeframe: Candle interval (e.g. 15m).
            candles: Chronologically sorted sequence of CandleData.

        Returns:
            IndicatorSeries containing aligned arrays of calculated indicators and regimes.
        """
        if not candles:
            return IndicatorSeries(
                symbol=symbol,
                timeframe=timeframe,
                timestamps=[],
                closes=[],
                ema9=[],
                ema20=[],
                sma50=[],
                rsi14=[],
                macd_line=[],
                macd_signal=[],
                macd_histogram=[],
                atr14=[],
                atrp14=[],
                trend_regimes=[],
                volatility_regimes=[],
                count=0,
            )

        timestamps = [c.timestamp for c in candles]
        closes = [c.close for c in candles]

        ema9 = calculate_ema_from_candles(candles, period=9)
        ema20 = calculate_ema_from_candles(candles, period=20)
        sma50 = calculate_sma_from_candles(candles, period=50)
        rsi14 = calculate_rsi_from_candles(candles, period=14)
        macd_line, macd_signal, macd_hist = calculate_macd_from_candles(
            candles, fast_period=12, slow_period=26, signal_period=9
        )
        atr14, atrp14 = calculate_atr_from_candles(candles, period=14)

        # Compute aligned descriptive market regimes (Trend and Volatility)
        trend_regimes, vol_regimes, _, _ = compute_market_regimes_series(
            closes=closes,
            ema9_series=ema9,
            ema20_series=ema20,
            sma50_series=sma50,
            rsi14_series=rsi14,
            macd_series=macd_line,
            atrp14_series=atrp14,
        )

        return IndicatorSeries(
            symbol=symbol,
            timeframe=timeframe,
            timestamps=timestamps,
            closes=closes,
            ema9=ema9,
            ema20=ema20,
            sma50=sma50,
            rsi14=rsi14,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_hist,
            atr14=atr14,
            atrp14=atrp14,
            trend_regimes=trend_regimes,
            volatility_regimes=vol_regimes,
            count=len(candles),
        )

    @staticmethod
    def compute_snapshot(
        symbol: str,
        timeframe: str,
        candles: Sequence[CandleData],
    ) -> Optional[IndicatorSnapshot]:
        """Compute the latest indicator and regime state snapshot at the most recent candle bar.

        Args:
            symbol: Trading symbol.
            timeframe: Candle interval.
            candles: Chronologically sorted sequence of CandleData.

        Returns:
            IndicatorSnapshot at the latest completed candle, or None if candles is empty.
        """
        if not candles:
            return None

        series = QuantitativeIndicatorEngine.compute_series(symbol, timeframe, candles)
        last_candle = candles[-1]

        # Calculate supporting details for the latest snapshot
        _, last_trend_details = classify_trend_bar(
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

        return IndicatorSnapshot(
            timestamp=last_candle.timestamp,
            close=last_candle.close,
            volume=last_candle.volume,
            ema9=series.ema9[-1] if series.ema9 else None,
            ema20=series.ema20[-1] if series.ema20 else None,
            sma50=series.sma50[-1] if series.sma50 else None,
            rsi14=series.rsi14[-1] if series.rsi14 else None,
            macd=series.macd_line[-1] if series.macd_line else None,
            macd_signal=series.macd_signal[-1] if series.macd_signal else None,
            macd_histogram=series.macd_histogram[-1] if series.macd_histogram else None,
            atr14=series.atr14[-1] if series.atr14 else None,
            atrp14=series.atrp14[-1] if series.atrp14 else None,
            trend_regime=series.trend_regimes[-1] if series.trend_regimes else None,
            volatility_regime=series.volatility_regimes[-1] if series.volatility_regimes else None,
            trend_details=last_trend_details,
            volatility_details=last_vol_metrics,
        )

    @staticmethod
    def compute_regime_snapshot(
        candles: Sequence[CandleData],
    ) -> Optional[MarketRegimeSnapshot]:
        """Compute standalone MarketRegimeSnapshot from candles."""
        return classify_market_regime_snapshot(candles)


_indicator_engine_instance: Optional[QuantitativeIndicatorEngine] = None


def get_indicator_engine() -> QuantitativeIndicatorEngine:
    """Dependency provider returning singleton QuantitativeIndicatorEngine instance."""
    global _indicator_engine_instance
    if _indicator_engine_instance is None:
        _indicator_engine_instance = QuantitativeIndicatorEngine()
    return _indicator_engine_instance
