"""Deterministic Average True Range (ATR) and ATR Percentage (ATRP) calculation."""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

from app.market_data.schema import CandleData


def calculate_true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> List[float]:
    """Calculate the True Range (TR) sequence for given High, Low, and Close prices.

    Formulas:
        TR_0 = High_0 - Low_0
        TR_t = max(High_t - Low_t, |High_t - Close_{t-1}|, |Low_t - Close_{t-1}|) for t >= 1

    Args:
        highs: Sequence of high prices.
        lows: Sequence of low prices.
        closes: Sequence of close prices.

    Returns:
        List of non-negative float True Range values.
    """
    n = len(highs)
    if n == 0:
        return []
    if len(lows) != n or len(closes) != n:
        raise ValueError("highs, lows, and closes sequences must have identical lengths")

    tr_list: List[float] = []
    for i in range(n):
        hl = max(0.0, float(highs[i]) - float(lows[i]))
        if i == 0:
            tr_list.append(hl)
        else:
            prev_close = float(closes[i - 1])
            hc = abs(float(highs[i]) - prev_close)
            lc = abs(float(lows[i]) - prev_close)
            tr_list.append(max(hl, hc, lc))

    return tr_list


def calculate_atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Calculate Average True Range (ATR) using J. Welles Wilder's smoothing method.

    Formulas:
        Initial ATR at index (period - 1):
            ATR_{period-1} = mean(TR[0..period-1])

        Subsequent Wilder's recursive smoothing:
            ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period

    Args:
        highs: Sequence of high prices.
        lows: Sequence of low prices.
        closes: Sequence of close prices.
        period: ATR lookback period (default 14). Must be >= 1.

    Returns:
        List of ATR values or None for bars with insufficient lookback.
    """
    if period < 1:
        raise ValueError(f"ATR period must be >= 1, got {period}")

    n = len(highs)
    if n == 0:
        return []
    if len(lows) != n or len(closes) != n:
        raise ValueError("highs, lows, and closes sequences must have identical lengths")

    if n < period:
        return [None] * n

    tr = calculate_true_range(highs, lows, closes)
    atr: List[Optional[float]] = [None] * n

    # Initial SMA over first `period` true ranges (indices 0 to period - 1)
    initial_atr = sum(tr[:period]) / period
    atr[period - 1] = round(initial_atr, 4)

    running_atr = initial_atr
    for i in range(period, n):
        running_atr = (running_atr * (period - 1) + tr[i]) / period
        atr[i] = round(running_atr, 4)

    return atr


def calculate_atrp(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Calculate ATR Percentage (ATRP) series = (ATR / Close) * 100.

    Args:
        highs: Sequence of high prices.
        lows: Sequence of low prices.
        closes: Sequence of close prices.
        period: ATR lookback period (default 14). Must be >= 1.

    Returns:
        List of ATRP float percentages (e.g. 1.75 for 1.75%) or None where undefined.
    """
    atr_series = calculate_atr(highs, lows, closes, period=period)
    atrp_series: List[Optional[float]] = []

    for i, atr_val in enumerate(atr_series):
        close_val = float(closes[i]) if i < len(closes) else 0.0
        if atr_val is None or close_val <= 0.0 or math.isnan(close_val) or math.isinf(close_val):
            atrp_series.append(None)
        else:
            atrp_series.append(round((atr_val / close_val) * 100.0, 4))

    return atrp_series


def calculate_atr_from_candles(
    candles: Sequence[CandleData],
    period: int = 14,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Calculate ATR and ATRP series from a sequence of CandleData.

    Args:
        candles: Sequence of CandleData.
        period: ATR lookback period (default 14).

    Returns:
        Tuple of (atr_series, atrp_series).
    """
    if not candles:
        return [], []

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]

    atr = calculate_atr(highs, lows, closes, period=period)
    atrp = calculate_atrp(highs, lows, closes, period=period)
    return atr, atrp


def get_latest_atr(
    candles: Sequence[CandleData],
    period: int = 14,
) -> Tuple[Optional[float], Optional[float]]:
    """Calculate and return only the latest (ATR, ATRP) values for the candles."""
    atr_series, atrp_series = calculate_atr_from_candles(candles, period=period)
    if not atr_series:
        return None, None
    return atr_series[-1], atrp_series[-1]
