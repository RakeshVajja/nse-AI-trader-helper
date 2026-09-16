"""Unit and integration tests for MarketDataService, PostgreSQL caching, and missing range detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.market_data.schema import (
    CandleData,
    HistoricalDataResponse,
)
from app.market_data.service import MarketDataService, calculate_missing_ranges


def _make_candle(ts: datetime, close: float = 100.0) -> CandleData:
    return CandleData(
        timestamp=ts,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=1000.0,
    )


def test_calculate_missing_ranges():
    """Verify calculation of missing historical intervals against cached range metadata."""
    t0 = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc)
    t10 = t0 + timedelta(days=10)
    t20 = t0 + timedelta(days=20)
    t30 = t0 + timedelta(days=30)

    # 1. No cached range -> entire request is missing
    assert calculate_missing_ranges(None, t0, t30) == [(t0, t30)]

    cached = models.MarketDataRange(
        instrument_id=1,
        timeframe="15m",
        earliest_timestamp=t10,
        latest_timestamp=t20,
        total_candles=100,
        last_updated=datetime.now(timezone.utc),
    )

    # 2. Request fully within cache -> no missing ranges
    t12 = t0 + timedelta(days=12)
    t18 = t0 + timedelta(days=18)
    assert calculate_missing_ranges(cached, t12, t18) == []

    # 3. Request extends before earliest -> missing left interval (exclusive of earliest)
    t5 = t0 + timedelta(days=5)
    assert calculate_missing_ranges(cached, t5, t18) == [(t5, t10 - timedelta(seconds=1))]

    # 4. Request extends past latest -> missing right interval (exclusive of latest)
    t25 = t0 + timedelta(days=25)
    assert calculate_missing_ranges(cached, t12, t25) == [(t20 + timedelta(seconds=1), t25)]

    # 5. Request extends both before and after -> missing two intervals
    assert calculate_missing_ranges(cached, t5, t25) == [
        (t5, t10 - timedelta(seconds=1)),
        (t20 + timedelta(seconds=1), t25),
    ]


@pytest.mark.asyncio
async def test_get_or_create_instrument(db_session: AsyncSession):
    """Verify instrument creation and reuse."""
    service = MarketDataService()

    inst1 = await service.get_or_create_instrument(db_session, "TCS", name="Tata Consultancy")
    assert inst1.id is not None
    assert inst1.symbol == "TCS"
    assert inst1.instrument_type == models.InstrumentType.EQUITY

    # Retrieve existing
    inst2 = await service.get_or_create_instrument(db_session, "TCS")
    assert inst2.id == inst1.id


@pytest.mark.asyncio
async def test_persist_candles_and_range_tracking(db_session: AsyncSession):
    """Verify candle persistence and automatic MarketDataRange creation/updating."""
    service = MarketDataService()
    inst = await service.get_or_create_instrument(db_session, "INFY")

    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    batch1 = [_make_candle(base + timedelta(minutes=15 * i), close=1500.0 + i) for i in range(5)]

    inserted = await service.persist_candles(db_session, inst.id, "15m", batch1)
    await db_session.commit()
    assert inserted == 5

    # Check range metadata
    rng = await service.get_market_data_range(db_session, inst.id, "15m")
    assert rng is not None
    assert rng.total_candles == 5
    earliest = (
        rng.earliest_timestamp.replace(tzinfo=timezone.utc)
        if rng.earliest_timestamp.tzinfo is None
        else rng.earliest_timestamp
    )
    latest = (
        rng.latest_timestamp.replace(tzinfo=timezone.utc)
        if rng.latest_timestamp.tzinfo is None
        else rng.latest_timestamp
    )
    assert earliest == base
    assert latest == base + timedelta(minutes=60)

    # Insert next batch extending latest
    batch2 = [
        _make_candle(base + timedelta(minutes=15 * i), close=1500.0 + i) for i in range(5, 10)
    ]
    inserted2 = await service.persist_candles(db_session, inst.id, "15m", batch2)
    await db_session.commit()
    assert inserted2 == 5

    rng_updated = await service.get_market_data_range(db_session, inst.id, "15m")
    assert rng_updated.total_candles == 10
    latest_upd = (
        rng_updated.latest_timestamp.replace(tzinfo=timezone.utc)
        if rng_updated.latest_timestamp.tzinfo is None
        else rng_updated.latest_timestamp
    )
    assert latest_upd == base + timedelta(minutes=135)


@pytest.mark.asyncio
async def test_on_demand_fetch_and_caching_flow(db_session: AsyncSession):
    """Verify end-to-end caching flow: Provider called on miss, served from DB on hit."""
    mock_provider = AsyncMock()
    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    mock_candles = [
        _make_candle(base + timedelta(minutes=15 * i), close=2500.0 + i) for i in range(4)
    ]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=mock_candles,
        count=len(mock_candles),
    )

    service = MarketDataService(provider=mock_provider)

    req_start = base
    req_end = base + timedelta(minutes=45)

    # 1. First fetch -> Cache MISS -> Calls provider & persists to DB
    resp1 = await service.get_historical_candles(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=req_start,
        end_date=req_end,
    )
    assert resp1.count == 4
    assert mock_provider.get_historical_data.call_count == 1

    # 2. Second fetch with same interval -> Cache HIT -> Served directly from DB (Provider not called)
    resp2 = await service.get_historical_candles(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=req_start,
        end_date=req_end,
    )
    assert resp2.count == 4
    assert mock_provider.get_historical_data.call_count == 1  # Still 1!

    # 3. Third fetch expanding interval -> Cache PARTIAL -> Calls provider ONLY for missing interval
    extended_start = base - timedelta(minutes=30)
    extra_candles = [
        _make_candle(extended_start + timedelta(minutes=15 * i), close=2490.0 + i) for i in range(2)
    ]
    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=extra_candles,
        count=len(extra_candles),
    )

    resp3 = await service.get_historical_candles(
        db=db_session,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=extended_start,
        end_date=req_end,
    )
    assert resp3.count == 6
    assert mock_provider.get_historical_data.call_count == 2


@pytest.mark.asyncio
async def test_provider_failure_and_empty_response_handling(db_session: AsyncSession):
    """Verify service gracefully handles provider failures without corrupting cache or crashing."""
    mock_provider = AsyncMock()
    mock_provider.get_historical_data.side_effect = Exception("NSE Gateway 504 Gateway Timeout")

    service = MarketDataService(provider=mock_provider)
    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    # Empty cache + provider failure -> returns empty response without raising
    resp = await service.get_historical_candles(
        db=db_session,
        symbol="WIPRO",
        timeframe="15m",
        start_date=base,
        end_date=base + timedelta(minutes=60),
    )
    assert resp.count == 0
    assert resp.candles == []

    # Pre-populate some candles into DB
    inst = await service.get_or_create_instrument(db_session, "WIPRO")
    cached_candle = _make_candle(base, close=450.0)
    await service.persist_candles(db_session, inst.id, "15m", [cached_candle])
    await db_session.commit()

    # Extend window when provider is failing -> returns existing cached data
    resp2 = await service.get_historical_candles(
        db=db_session,
        symbol="WIPRO",
        timeframe="15m",
        start_date=base,
        end_date=base + timedelta(hours=2),
    )
    assert resp2.count == 1
    assert resp2.candles[0].close == 450.0


@pytest.mark.asyncio
async def test_idempotent_duplicate_candle_persistence(db_session: AsyncSession):
    """Verify persisting identical candles multiple times is strictly idempotent."""
    service = MarketDataService()
    inst = await service.get_or_create_instrument(db_session, "HDFCBANK")

    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    batch = [_make_candle(base + timedelta(minutes=15 * i), close=1600.0) for i in range(3)]

    first_insert = await service.persist_candles(db_session, inst.id, "15m", batch)
    await db_session.commit()
    assert first_insert == 3

    # Attempt second and third persistence of the exact same data
    second_insert = await service.persist_candles(db_session, inst.id, "15m", batch)
    await db_session.commit()
    third_insert = await service.persist_candles(db_session, inst.id, "15m", batch)
    await db_session.commit()
    assert second_insert == 0
    assert third_insert == 0

    rng = await service.get_market_data_range(db_session, inst.id, "15m")
    assert rng is not None
    assert rng.total_candles == 3


@pytest.mark.asyncio
async def test_invalid_range_requests(db_session: AsyncSession):
    """Verify invalid start/end dates (start > end) return empty responses cleanly."""
    service = MarketDataService()
    t_start = datetime(2025, 1, 15, 15, 30, tzinfo=timezone.utc)
    t_end = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    assert calculate_missing_ranges(None, t_start, t_end) == []

    resp = await service.get_historical_candles(
        db=db_session,
        symbol="SBIN",
        timeframe="15m",
        start_date=t_start,
        end_date=t_end,
    )
    assert resp.count == 0
    assert resp.candles == []


@pytest.mark.asyncio
async def test_multi_timeframe_isolation(db_session: AsyncSession):
    """Verify that multiple timeframes (e.g. 15m and 1d) for the same symbol are isolated."""
    service = MarketDataService()
    inst = await service.get_or_create_instrument(db_session, "ITC")

    base_15m = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candles_15m = [
        _make_candle(base_15m + timedelta(minutes=15 * i), close=400.0 + i) for i in range(4)
    ]

    base_1d = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    candles_1d = [_make_candle(base_1d + timedelta(days=i), close=410.0 + i) for i in range(3)]

    await service.persist_candles(db_session, inst.id, "15m", candles_15m)
    await service.persist_candles(db_session, inst.id, "1d", candles_1d)
    await db_session.commit()

    rng_15m = await service.get_market_data_range(db_session, inst.id, "15m")
    rng_1d = await service.get_market_data_range(db_session, inst.id, "1d")

    assert rng_15m is not None and rng_15m.total_candles == 4
    assert rng_1d is not None and rng_1d.total_candles == 3

    resp_15m = await service.get_historical_candles(
        db=db_session,
        symbol="ITC",
        timeframe="15m",
        start_date=base_15m,
        end_date=base_15m + timedelta(hours=2),
    )
    assert resp_15m.count == 4

    resp_1d = await service.get_historical_candles(
        db=db_session,
        symbol="ITC",
        timeframe="1d",
        start_date=base_1d,
        end_date=base_1d + timedelta(days=5),
    )
    assert resp_1d.count == 3


@pytest.mark.asyncio
async def test_mixed_valid_and_invalid_candles_from_provider(db_session: AsyncSession):
    """Verify provider returning corrupt candles has invalid bars filtered out before persisting."""
    mock_provider = AsyncMock()
    base = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    mixed_candles = [
        _make_candle(base, close=100.0),
        _make_candle(base + timedelta(minutes=15), close=-10.0),  # Negative price -> Invalid
        _make_candle(base + timedelta(minutes=30), close=102.0),
    ]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="MARUTI",
        timeframe="15m",
        candles=mixed_candles,
        count=3,
    )

    service = MarketDataService(provider=mock_provider)
    resp = await service.get_historical_candles(
        db=db_session,
        symbol="MARUTI",
        timeframe="15m",
        start_date=base,
        end_date=base + timedelta(minutes=45),
    )

    assert resp.count == 2
    assert resp.candles[0].timestamp == base
    assert resp.candles[1].timestamp == base + timedelta(minutes=30)
