"""OHLCV Data Validation and Integrity Verification."""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence, Tuple

from app.market_data.schema import CandleData

logger = logging.getLogger(__name__)


class OHLCVValidationError(ValueError):
    """Raised when candlestick bar violates financial/mathematical OHLCV integrity rules."""


def validate_candle(candle: CandleData, tolerance: float = 1e-6) -> Tuple[bool, List[str]]:
    """Validate a single candlestick bar for mathematical and financial correctness.

    Rules:
    1. Open, High, Low, Close must all be strictly positive (> 0).
    2. Volume must be non-negative (>= 0).
    3. High must be >= max(Open, Close) (allowing small floating point tolerance).
    4. Low must be <= min(Open, Close) (allowing small floating point tolerance).
    5. Low must be <= High.
    6. Timestamp must have timezone information.

    Returns:
        Tuple of (is_valid: bool, issues: List[str])
    """
    issues: List[str] = []

    if candle.open <= 0:
        issues.append(f"Open price {candle.open} is <= 0")
    if candle.high <= 0:
        issues.append(f"High price {candle.high} is <= 0")
    if candle.low <= 0:
        issues.append(f"Low price {candle.low} is <= 0")
    if candle.close <= 0:
        issues.append(f"Close price {candle.close} is <= 0")
    if candle.volume < 0:
        issues.append(f"Volume {candle.volume} is < 0")

    if candle.high + tolerance < max(candle.open, candle.close):
        issues.append(
            f"High ({candle.high}) is less than max(Open={candle.open}, Close={candle.close})"
        )

    if candle.low - tolerance > min(candle.open, candle.close):
        issues.append(
            f"Low ({candle.low}) is greater than min(Open={candle.open}, Close={candle.close})"
        )

    if candle.low - tolerance > candle.high:
        issues.append(f"Low ({candle.low}) is greater than High ({candle.high})")

    if candle.timestamp is None or candle.timestamp.tzinfo is None:
        issues.append("Timestamp must be timezone-aware")

    return len(issues) == 0, issues


def is_chronologically_sorted(candles: Sequence[CandleData]) -> bool:
    """Check if candle sequence is strictly monotonically increasing by timestamp."""
    if len(candles) <= 1:
        return True

    for i in range(len(candles) - 1):
        if candles[i].timestamp >= candles[i + 1].timestamp:
            return False
    return True


def validate_and_clean_candles(
    candles: Sequence[CandleData],
    strict: bool = False,
    deduplicate: bool = True,
) -> List[CandleData]:
    """Validate, filter, deduplicate, and sort a sequence of candlestick bars.

    Args:
        candles: Input list of CandleData.
        strict: If True, raises OHLCVValidationError on the first invalid candle.
                If False, logs a warning and discards the invalid candle.
        deduplicate: If True, keeps the last valid candle for duplicate timestamps.

    Returns:
        Strictly chronological, deduplicated, validated list of CandleData.
    """
    if not candles:
        return []

    valid_candles: List[CandleData] = []

    for idx, c in enumerate(candles):
        is_valid, issues = validate_candle(c)
        if not is_valid:
            msg = f"Candle at index {idx} ({c.timestamp}) failed validation: {'; '.join(issues)}"
            if strict:
                raise OHLCVValidationError(msg)
            logger.warning(msg)
            continue
        valid_candles.append(c)

    if not valid_candles:
        return []

    if deduplicate:
        # Keep latest entry for each unique timestamp
        unique_map: Dict[int, CandleData] = {}
        for c in valid_candles:
            ts_key = int(c.timestamp.timestamp())
            unique_map[ts_key] = c
        valid_candles = list(unique_map.values())

    # Sort strictly by timestamp ascending
    valid_candles.sort(key=lambda x: x.timestamp)
    return valid_candles
