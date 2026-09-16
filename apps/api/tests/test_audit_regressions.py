"""Targeted regression tests for Phase 3 audit fixes:
- H2: Gap-unaware MarketDataRange caching & non-contiguous interval fetch.
- H1: Standardized transaction ownership without premature service-level commits.
- M1/M3: OpenChart IST naive timestamp localization and UTC conversion.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.market_data.openchart_adapter import NSEPublicProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataResponse,
)
from app.market_data.service import (
    MarketDataService,
    calculate_missing_ranges,
)


def _make_candle(ts: datetime, close: float = 2500.0) -> CandleData:
    """Helper to create valid CandleData."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return CandleData(
        timestamp=ts,
        open=close - 5.0,
        high=close + 10.0,
        low=close - 10.0,
        close=close,
        volume=1000.0,
    )


# =====================================================================
# H2: Gap-Unaware Range Caching & Non-Contiguous Fetch Tests
# =====================================================================


def test_calculate_missing_ranges_bridges_non_contiguous_jumps():
    """Verify that calculate_missing_ranges bridges gaps when requests jump forward or backward."""
    t0 = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    t1 = datetime(2025, 1, 5, 15, 30, tzinfo=timezone.utc)

    # Existing cached range: [Jan 1, Jan 5]
    existing_range = models.MarketDataRange(
        instrument_id=1,
        timeframe="15m",
        earliest_timestamp=t0,
        latest_timestamp=t1,
        total_candles=100,
        last_updated=t1,
    )

    # 1. Forward jump: Request [Feb 1, Feb 5] (req_start > latest)
    req_start_fwd = datetime(2025, 2, 1, 9, 15, tzinfo=timezone.utc)
    req_end_fwd = datetime(2025, 2, 5, 15, 30, tzinfo=timezone.utc)
    missing_fwd = calculate_missing_ranges(existing_range, req_start_fwd, req_end_fwd)

    assert len(missing_fwd) == 1
    # Must fetch from (latest + 1s) to req_end to bridge the cache without creating interior gaps
    assert missing_fwd[0][0] == t1 + timedelta(seconds=1)
    assert missing_fwd[0][1] == req_end_fwd

    # 2. Backward jump: Request [Dec 20, Dec 25] (req_end < earliest)
    req_start_bwd = datetime(2024, 12, 20, 9, 15, tzinfo=timezone.utc)
    req_end_bwd = datetime(2024, 12, 25, 15, 30, tzinfo=timezone.utc)
    missing_bwd = calculate_missing_ranges(existing_range, req_start_bwd, req_end_bwd)

    assert len(missing_bwd) == 1
    # Must fetch from req_start up to (earliest - 1s) to bridge to existing cache
    assert missing_bwd[0][0] == req_start_bwd
    assert missing_bwd[0][1] == t0 - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_h2_non_contiguous_fetches_never_produce_false_cache_hits(db_session: AsyncSession):
    """Regression Test H2: Fetching non-contiguous windows does not cause intermediate windows to return 0 candles."""
    mock_provider = AsyncMock()
    service = MarketDataService(provider=mock_provider)

    # Batch 1: Jan 1 - Jan 5 (5 candles)
    t_jan1 = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    candles_jan = [_make_candle(t_jan1 + timedelta(days=i), close=2400.0 + i) for i in range(5)]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=candles_jan,
        count=len(candles_jan),
    )

    # 1. Fetch Jan 1 - Jan 5
    r1 = await service.get_historical_candles(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=t_jan1,
        end_date=t_jan1 + timedelta(days=4),
    )
    assert r1.count == 5

    # 2. Forward jump: Fetch Feb 1 - Feb 5 (5 candles)
    t_feb1 = datetime(2025, 2, 1, 9, 15, tzinfo=timezone.utc)
    candles_feb = [_make_candle(t_feb1 + timedelta(days=i), close=2500.0 + i) for i in range(5)]

    # Provider returns the requested bridge/forward candles
    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=candles_feb,
        count=len(candles_feb),
    )

    r2 = await service.get_historical_candles(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=t_feb1,
        end_date=t_feb1 + timedelta(days=4),
    )
    assert r2.count == 5

    # 3. Intermediate window: Fetch Jan 15 - Jan 20 (between Jan 5 and Feb 1)
    t_mid = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candles_mid = [_make_candle(t_mid + timedelta(days=i), close=2450.0 + i) for i in range(5)]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=candles_mid,
        count=len(candles_mid),
    )

    # With the fallback safety net and bridge fetching, intermediate window must fetch from provider
    # and NEVER return 0 candles falsely!
    r3 = await service.get_historical_candles(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=t_mid,
        end_date=t_mid + timedelta(days=4),
    )
    assert r3.count == 5
    assert r3.candles[0].timestamp == t_mid


# =====================================================================
# H1: Transaction Ownership & Rollback Safety Tests
# =====================================================================


@pytest.mark.asyncio
async def test_h1_transaction_rollback_reverts_service_mutations(db_session: AsyncSession):
    """Regression Test H1: Service methods do not prematurely commit, ensuring caller rollback cleans DB state."""
    mock_provider = AsyncMock()
    service = MarketDataService(provider=mock_provider)

    t0 = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candles = [_make_candle(t0 + timedelta(minutes=15 * i)) for i in range(5)]
    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="TCS",
        timeframe="15m",
        candles=candles,
        count=5,
    )

    # Call get_historical_candles (which flushes but no longer explicitly commits)
    resp = await service.get_historical_candles(
        db=db_session,
        symbol="TCS",
        timeframe="15m",
        start_date=t0,
        end_date=t0 + timedelta(minutes=60),
    )
    assert resp.count == 5

    # Simulate an error in the caller/request handler -> rollback
    await db_session.rollback()

    # Verify that TCS instrument and candles were completely rolled back
    inst_res = await db_session.execute(
        select(models.Instrument).where(models.Instrument.symbol == "TCS")
    )
    assert inst_res.scalar_one_or_none() is None

    candle_count = (await db_session.execute(select(func.count(models.Candle.id)))).scalar()
    assert candle_count == 0


@pytest.mark.asyncio
async def test_h1_seed_instruments_transaction_rollback(db_session: AsyncSession):
    """Regression Test H1: seed_default_instruments does not commit, so rollback reverts seeded rows."""
    service = MarketDataService()
    seeded = await service.seed_default_instruments(db_session)
    assert len(seeded) > 0

    # Rollback transaction
    await db_session.rollback()

    # Instruments table must be empty
    count = (await db_session.execute(select(func.count(models.Instrument.id)))).scalar()
    assert count == 0


# =====================================================================
# M1/M3: OpenChart IST Naive Timestamp Localization Tests
# =====================================================================


def test_m1_openchart_naive_ist_timestamp_converted_to_utc():
    """Regression Test M1: Naive timestamps from OpenChart (representing IST clock time) are correctly converted to UTC."""
    provider = NSEPublicProvider()

    # OpenChart returns a DataFrame with naive timestamps representing IST clock times (e.g. 09:15 for market open)
    naive_dates = pd.date_range("2025-01-15 09:15", periods=3, freq="15min")
    assert naive_dates.tz is None  # Naive timestamps from openchart.utils

    df = pd.DataFrame(
        {
            "Open": [2500.0, 2510.0, 2505.0],
            "High": [2520.0, 2525.0, 2515.0],
            "Low": [2495.0, 2505.0, 2500.0],
            "Close": [2510.0, 2515.0, 2512.0],
            "Volume": [10000.0, 15000.0, 8000.0],
        },
        index=naive_dates,
    )
    df.index.name = "Timestamp"

    candles = provider._dataframe_to_candles(df)
    assert len(candles) == 3

    # 09:15:00 IST = 03:45:00 UTC (IST is UTC+5:30)
    first_candle = candles[0]
    assert first_candle.timestamp.tzinfo == timezone.utc
    assert first_candle.timestamp.hour == 3
    assert first_candle.timestamp.minute == 45
    assert first_candle.timestamp.year == 2025
    assert first_candle.timestamp.month == 1
    assert first_candle.timestamp.day == 15

    # Second candle: 09:30:00 IST = 04:00:00 UTC
    assert candles[1].timestamp.hour == 4
    assert candles[1].timestamp.minute == 0


def test_m1_openchart_timezone_aware_utc_timestamp_preserved():
    """Regression Test M1: UTC-aware timestamps are preserved without double-shifting."""
    provider = NSEPublicProvider()

    utc_dates = pd.date_range("2025-01-15 03:45", periods=2, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "Open": [2500.0, 2510.0],
            "High": [2520.0, 2525.0],
            "Low": [2495.0, 2505.0],
            "Close": [2510.0, 2515.0],
            "Volume": [10000.0, 15000.0],
        },
        index=utc_dates,
    )
    df.index.name = "Timestamp"

    candles = provider._dataframe_to_candles(df)
    assert len(candles) == 2
    assert candles[0].timestamp.hour == 3
    assert candles[0].timestamp.minute == 45
    assert candles[0].timestamp.tzinfo == timezone.utc
