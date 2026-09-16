"""Deterministic Simple Moving Average (SMA) calculation."""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

import pandas as pd

from app.market_data.schema import CandleData


def calculate_sma(
    prices: Sequence[float],
    period: int,
    min_periods: Optional[int] = None,
) -> List[Optional[float]]:
    """Calculate Simple Moving Average (SMA) over a sequence of prices.

    Uses the rolling mean formula:
        SMA_t = (Price_t + Price_{t-1} + ... + Price_{t-period+1}) / period

    Args:
        prices: Sequence of price floats (typically Close prices).
        period: Rolling window period (e.g., 50). Must be >= 1.
        min_periods: Minimum required data points before outputting a value.
                     Defaults to `period` (values before `period - 1` are None).

    Returns:
        List of calculated SMA values or None where insufficient data exists.
    """
    if period < 1:
        raise ValueError(f"SMA period must be >= 1, got {period}")

    n = len(prices)
    if n == 0:
        return []

    required_min = period if min_periods is None else min_periods
    if n < required_min:
        return [None] * n

    series = pd.Series(prices, dtype=float)
    sma_series = series.rolling(window=period, min_periods=required_min).mean()

    result: List[Optional[float]] = []
    for val in sma_series:
        if val is None or math.isnan(val) or math.isinf(val):
            result.append(None)
        else:
            result.append(round(float(val), 4))

    return result


def calculate_sma_from_candles(
    candles: Sequence[CandleData],
    period: int,
    min_periods: Optional[int] = None,
) -> List[Optional[float]]:
    """Calculate SMA series from a sequence of CandleData using close prices."""
    closes = [c.close for c in candles]
    return calculate_sma(closes, period=period, min_periods=min_periods)


def get_latest_sma(
    prices: Sequence[float],
    period: int,
) -> Optional[float]:
    """Calculate and return only the latest SMA value for the given price series."""
    sma_list = calculate_sma(prices, period=period)
    if not sma_list:
        return None
    return sma_list[-1]
