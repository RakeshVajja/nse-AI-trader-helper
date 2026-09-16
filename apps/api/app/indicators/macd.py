"""Deterministic Moving Average Convergence Divergence (MACD) calculation."""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import pandas as pd

from app.indicators.schemas import MACDValue
from app.market_data.schema import CandleData


def calculate_macd(
    prices: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Calculate MACD Line, Signal Line, and MACD Histogram.

    Formulas:
        Fast_EMA = EMA(Close, fast_period)
        Slow_EMA = EMA(Close, slow_period)
        MACD_Line = Fast_EMA - Slow_EMA
        Signal_Line = EMA(MACD_Line, signal_period)
        Histogram = MACD_Line - Signal_Line

    Args:
        prices: Sequence of price floats (typically Close prices).
        fast_period: Lookback for fast EMA (default 12). Must be >= 1.
        slow_period: Lookback for slow EMA (default 26). Must be > fast_period.
        signal_period: Lookback for signal line EMA (default 9). Must be >= 1.

    Returns:
        Tuple of (macd_line, signal_line, histogram) lists aligned with input prices.
    """
    if fast_period < 1 or slow_period < 1 or signal_period < 1:
        raise ValueError("MACD periods must be >= 1")
    if fast_period >= slow_period:
        raise ValueError(
            f"fast_period ({fast_period}) must be strictly less than slow_period ({slow_period})"
        )

    n = len(prices)
    if n == 0:
        return [], [], []

    # If data points are fewer than slow_period, return all None
    if n < slow_period:
        return [None] * n, [None] * n, [None] * n

    series = pd.Series(prices, dtype=float)

    # Calculate Fast and Slow EMAs
    fast_ema = series.ewm(span=fast_period, adjust=False).mean()
    slow_ema = series.ewm(span=slow_period, adjust=False).mean()

    # MACD Line = Fast EMA - Slow EMA
    raw_macd = fast_ema - slow_ema

    # Warmup requirement: MACD line is valid starting at index slow_period - 1
    macd_line: List[Optional[float]] = []
    for i, val in enumerate(raw_macd):
        if i < slow_period - 1 or math.isnan(val) or math.isinf(val):
            macd_line.append(None)
        else:
            macd_line.append(round(float(val), 4))

    # Calculate Signal Line as EMA over valid MACD line values
    valid_macd_indices = [i for i, v in enumerate(macd_line) if v is not None]
    signal_line: List[Optional[float]] = [None] * n
    histogram: List[Optional[float]] = [None] * n

    if len(valid_macd_indices) >= signal_period:
        valid_macd_values = [macd_line[i] for i in valid_macd_indices if macd_line[i] is not None]
        macd_sub_series = pd.Series(valid_macd_values, dtype=float)
        raw_signal = macd_sub_series.ewm(span=signal_period, adjust=False).mean()

        for sub_i, orig_i in enumerate(valid_macd_indices):
            if sub_i >= signal_period - 1:
                sig_val = raw_signal.iloc[sub_i]
                if not (math.isnan(sig_val) or math.isinf(sig_val)):
                    sig_rounded = round(float(sig_val), 4)
                    signal_line[orig_i] = sig_rounded
                    m_val = macd_line[orig_i]
                    if m_val is not None:
                        histogram[orig_i] = round(m_val - sig_rounded, 4)

    return macd_line, signal_line, histogram


def calculate_macd_from_candles(
    candles: Sequence[CandleData],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """Calculate MACD series from a sequence of CandleData using close prices."""
    closes = [c.close for c in candles]
    return calculate_macd(
        closes,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )


def get_latest_macd(
    prices: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MACDValue:
    """Calculate and return only the latest MACD values for the given price series."""
    macd_l, sig_l, hist_l = calculate_macd(
        prices,
        fast_period=fast_period,
        slow_period=slow_period,
        signal_period=signal_period,
    )
    if not macd_l:
        return MACDValue(macd=None, signal=None, histogram=None)

    return MACDValue(
        macd=macd_l[-1],
        signal=sig_l[-1] if sig_l else None,
        histogram=hist_l[-1] if hist_l else None,
    )
