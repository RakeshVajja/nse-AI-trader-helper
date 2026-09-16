"""Deterministic Relative Strength Index (RSI) calculation using Wilder's smoothing."""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from app.market_data.schema import CandleData


def calculate_rsi(
    prices: Sequence[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Calculate Relative Strength Index (RSI) using J. Welles Wilder's smoothing method.

    Formulas:
        Delta_t = Price_t - Price_{t-1}
        Gain_t = max(Delta_t, 0)
        Loss_t = max(-Delta_t, 0)

        Initial averages (at bar index = period):
            AvgGain_period = mean(Gains[1..period])
            AvgLoss_period = mean(Losses[1..period])

        Subsequent Wilder's recursive smoothed averages:
            AvgGain_t = (AvgGain_{t-1} * (period - 1) + Gain_t) / period
            AvgLoss_t = (AvgLoss_{t-1} * (period - 1) + Loss_t) / period

        Relative Strength (RS) = AvgGain / AvgLoss
        RSI = 100 - (100 / (1 + RS))

    Args:
        prices: Sequence of price floats (typically Close prices).
        period: RSI lookback period (default 14). Must be >= 1.

    Returns:
        List of RSI values (0.0 to 100.0) or None for bars with insufficient lookback.
    """
    if period < 1:
        raise ValueError(f"RSI period must be >= 1, got {period}")

    n = len(prices)
    if n == 0:
        return []

    # Need at least period + 1 prices to calculate initial average over `period` deltas
    if n <= period:
        return [None] * n

    deltas = np.diff(prices)
    gains = np.where(deltas > 0.0, deltas, 0.0)
    losses = np.where(deltas < 0.0, -deltas, 0.0)

    result: List[Optional[float]] = [None] * n

    # Initial SMA over first `period` deltas (indices 0 to period - 1 in deltas array)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # First RSI value is at index `period` (the (period+1)-th price)
    if avg_loss == 0.0:
        rsi_val = 100.0 if avg_gain > 0.0 else 50.0
    elif avg_gain == 0.0:
        rsi_val = 0.0
    else:
        rs = avg_gain / avg_loss
        rsi_val = 100.0 - (100.0 / (1.0 + rs))

    result[period] = round(float(np.clip(rsi_val, 0.0, 100.0)), 4)

    # Recursive Wilder's smoothing for subsequent bars
    for i in range(period, len(deltas)):
        gain = float(gains[i])
        loss = float(losses[i])

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0.0:
            rsi_val = 100.0 if avg_gain > 0.0 else 50.0
        elif avg_gain == 0.0:
            rsi_val = 0.0
        else:
            rs = avg_gain / avg_loss
            rsi_val = 100.0 - (100.0 / (1.0 + rs))

        result[i + 1] = round(float(np.clip(rsi_val, 0.0, 100.0)), 4)

    return result


def calculate_rsi_from_candles(
    candles: Sequence[CandleData],
    period: int = 14,
) -> List[Optional[float]]:
    """Calculate RSI series from a sequence of CandleData using close prices."""
    closes = [c.close for c in candles]
    return calculate_rsi(closes, period=period)


def get_latest_rsi(
    prices: Sequence[float],
    period: int = 14,
) -> Optional[float]:
    """Calculate and return only the latest RSI value for the given price series."""
    rsi_list = calculate_rsi(prices, period=period)
    if not rsi_list:
        return None
    return rsi_list[-1]
