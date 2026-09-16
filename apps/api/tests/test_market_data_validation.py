"""Unit tests for OHLCV data validation, sorting, deduplication, and integrity checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.market_data.schema import CandleData
from app.market_data.validator import (
    OHLCVValidationError,
    is_chronologically_sorted,
    validate_and_clean_candles,
    validate_candle,
)


def _make_candle(
    ts: datetime,
    o: float = 100.0,
    h: float = 105.0,
    l: float = 95.0,
    c: float = 102.0,
    v: float = 1000.0,
) -> CandleData:
    return CandleData(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def test_validate_candle_valid():
    """Verify that a compliant OHLCV candle passes validation."""
    ts = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candle = _make_candle(ts, o=100.0, h=105.0, l=95.0, c=102.0, v=500.0)
    is_valid, issues = validate_candle(candle)
    assert is_valid is True
    assert len(issues) == 0


def test_validate_candle_negative_prices_and_volume():
    """Verify rejection of zero/negative prices and negative volumes."""
    ts = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Zero open
    c_zero_open = _make_candle(ts, o=0.0)
    is_valid, issues = validate_candle(c_zero_open)
    assert is_valid is False
    assert any("Open price" in s for s in issues)

    # Negative volume
    c_neg_vol = _make_candle(ts, v=-50.0)
    is_valid, issues = validate_candle(c_neg_vol)
    assert is_valid is False
    assert any("Volume" in s for s in issues)


def test_validate_candle_high_low_violations():
    """Verify rejection when High < max(Open, Close) or Low > min(Open, Close)."""
    ts = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    # High lower than open
    c_bad_high = _make_candle(ts, o=100.0, h=98.0, l=90.0, c=95.0)
    is_valid, issues = validate_candle(c_bad_high)
    assert is_valid is False
    assert any("High (98.0) is less than max" in s for s in issues)

    # Low higher than close
    c_bad_low = _make_candle(ts, o=100.0, h=110.0, l=106.0, c=105.0)
    is_valid, issues = validate_candle(c_bad_low)
    assert is_valid is False
    assert any("Low (106.0) is greater than min" in s for s in issues)

    # Low higher than high
    c_inverted = _make_candle(ts, o=100.0, h=95.0, l=105.0, c=100.0)
    is_valid, issues = validate_candle(c_inverted)
    assert is_valid is False


def test_is_chronologically_sorted():
    """Verify chronological order detection."""
    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    c1 = _make_candle(base)
    c2 = _make_candle(base + timedelta(minutes=15))
    c3 = _make_candle(base + timedelta(minutes=30))

    assert is_chronologically_sorted([c1, c2, c3]) is True
    assert is_chronologically_sorted([c3, c2, c1]) is False
    assert is_chronologically_sorted([c1, c1]) is False
    assert is_chronologically_sorted([c1]) is True
    assert is_chronologically_sorted([]) is True


def test_validate_and_clean_candles_deduplication_and_sorting():
    """Verify deduplication and chronological sorting in candle cleaner."""
    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    t1 = base
    t2 = base + timedelta(minutes=15)
    t3 = base + timedelta(minutes=30)

    c1 = _make_candle(t1, c=101.0)
    c1_dup = _make_candle(t1, c=101.5)  # Duplicate timestamp with updated close
    c2 = _make_candle(t2, c=102.0)
    c3 = _make_candle(t3, c=103.0)

    # Pass in unsorted list with duplicate
    raw_candles = [c3, c1, c2, c1_dup]
    cleaned = validate_and_clean_candles(raw_candles, deduplicate=True)

    assert len(cleaned) == 3
    assert is_chronologically_sorted(cleaned) is True
    assert cleaned[0].timestamp == t1
    assert cleaned[0].close == 101.5  # Kept the latest duplicate
    assert cleaned[1].timestamp == t2
    assert cleaned[2].timestamp == t3


def test_validate_and_clean_candles_strict_vs_non_strict():
    """Verify strict mode raises error whereas non-strict filters invalid candles."""
    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    valid_c = _make_candle(base)
    invalid_c = _make_candle(base + timedelta(minutes=15), h=50.0, o=100.0)  # Bad high

    # Strict mode
    with pytest.raises(OHLCVValidationError):
        validate_and_clean_candles([valid_c, invalid_c], strict=True)

    # Non-strict mode
    cleaned = validate_and_clean_candles([valid_c, invalid_c], strict=False)
    assert len(cleaned) == 1
    assert cleaned[0].timestamp == base
