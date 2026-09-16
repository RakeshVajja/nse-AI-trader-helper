"""Deterministic Exponential Moving Average (EMA) calculation."""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

import pandas as pd

from app.market_data.schema import CandleData


def calculate_ema(
    prices: Sequence[float],
    period: int,
    min_periods: Optional[int] = None,
) -> List[Optional[float]]:
    """Calculate Exponential Moving Average (EMA) over a sequence of prices.

    Uses the standard recursive formula:
        alpha = 2 / (period + 1)
        EMA_t = alpha * Price_t + (1 - alpha) * EMA_{t-1}

    Args:
        prices: Sequence of price floats (typically Close prices).
        period: Time period window (e.g., 9 or 20). Must be >= 1.
        min_periods: Minimum required data points before outputting a value.
                     Defaults to `period` (values before `period - 1` are None).

    Returns:
        List of calculated EMA values or None where insufficient data exists.
    """
    if period < 1:
        raise ValueError(f"EMA period must be >= 1, got {period}")

    n = len(prices)
    if n == 0:
        return []

    required_min = period if min_periods is None else min_periods
    if n < required_min:
        return [None] * n

    # Convert to pandas Series for numerical calculation
    series = pd.Series(prices, dtype=float)
    # Using adjust=False matches standard TA-Lib / TradingView recursive EMA
    ema_series = series.ewm(span=period, adjust=False).mean()

    result: List[Optional[float]] = []
    for i, val in enumerate(ema_series):
        if i < required_min - 1 or math.isnan(val) or math.isinf(val):
            result.append(None)
        else:
            result.append(round(float(val), 4))

    return result


def calculate_ema_from_candles(
    candles: Sequence[CandleData],
    period: int,
    min_periods: Optional[int] = None,
) -> List[Optional[float]]:
    """Calculate EMA series from a sequence of CandleData using close prices."""
    closes = [c.close for c in candles]
    return calculate_ema(closes, period=period, min_periods=min_periods)


def get_latest_ema(
    prices: Sequence[float],
    period: int,
) -> Optional[float]:
    """Calculate and return only the latest EMA value for the given price series."""
    ema_list = calculate_ema(prices, period=period)
    if not ema_list:
        return None
    return ema_list[-1]
