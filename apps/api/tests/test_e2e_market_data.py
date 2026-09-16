"""End-to-End verification test suite for Market Data Flow (Phase 3C).

Verifies the full lifecycle of RELIANCE 15m historical data retrieval:
1. Client request through FastAPI REST API.
2. MarketDataService cache inspection.
3. OpenChart / MarketDataProvider on-demand fetching.
4. Data validation, deduplication, and PostgreSQL persistence.
5. Missing-range calculation & incremental cache expansion.
6. Multi-instrument & multi-timeframe isolation.
7. Error isolation, graceful degradation, and edge case resilience.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import models
from app.database.base import Base
from app.database.session import get_db_session
from app.main import app
from app.market_data.base import MarketDataProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataRequest,
    HistoricalDataResponse,
)
from app.market_data.service import MarketDataService, get_market_data_service


def _generate_synthetic_candles(
    start: datetime,
    count: int,
    interval_minutes: int = 15,
    base_price: float = 2500.0,
) -> list[CandleData]:
    """Generate realistic synthetic OHLCV candles."""
    candles = []
    current_price = base_price
    for i in range(count):
        ts = start + timedelta(minutes=interval_minutes * i)
        open_p = current_price
        high_p = open_p + 12.5
        low_p = max(open_p - 8.0, 1.0)
        close_p = open_p + 4.0
        volume = 25000.0 + (i * 100)
        current_price = close_p
        candles.append(
            CandleData(
                timestamp=ts,
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=volume,
            )
        )
    return candles


@pytest.fixture
async def e2e_env():
    """Create isolated test environment with SQLite async DB and mockable MarketDataService."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    mock_provider = AsyncMock(spec=MarketDataProvider)
    service = MarketDataService(provider=mock_provider)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_service():
        return service

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_market_data_service] = override_get_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "service": service,
            "provider": mock_provider,
            "session_factory": session_factory,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_e2e_reliance_15m_initial_fetch_and_cache(e2e_env):
    """Scenario 1: Initial fetch of RELIANCE 15m data fetches from provider and caches in DB."""
    client = e2e_env["client"]
    provider = e2e_env["provider"]
    session_factory = e2e_env["session_factory"]

    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t_end = t0 + timedelta(days=2)
    synthetic_candles = _generate_synthetic_candles(
        t0, count=50, interval_minutes=15, base_price=2450.0
    )

    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=synthetic_candles,
        count=len(synthetic_candles),
    )

    # 1. Client calls REST API
    response = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t_end.isoformat(),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert data["timeframe"] == "15m"
    assert data["count"] == 50
    assert len(data["candles"]) == 50
    assert data["candles"][0]["open"] == 2450.0

    # 2. Verify database records
    async with session_factory() as db:
        # Check instrument
        inst_res = await db.execute(
            select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
        )
        inst = inst_res.scalar_one_or_none()
        assert inst is not None
        assert inst.symbol == "RELIANCE"

        # Check stored candles count
        candle_count = (
            await db.execute(
                select(func.count(models.Candle.id)).where(
                    models.Candle.instrument_id == inst.id,
                    models.Candle.timeframe == "15m",
                )
            )
        ).scalar()
        assert candle_count == 50

        # Check MarketDataRange
        range_res = await db.execute(
            select(models.MarketDataRange).where(
                models.MarketDataRange.instrument_id == inst.id,
                models.MarketDataRange.timeframe == "15m",
            )
        )
        data_range = range_res.scalar_one_or_none()
        assert data_range is not None
        assert data_range.total_candles == 50
        earliest = (
            data_range.earliest_timestamp.replace(tzinfo=timezone.utc)
            if data_range.earliest_timestamp.tzinfo is None
            else data_range.earliest_timestamp
        )
        latest = (
            data_range.latest_timestamp.replace(tzinfo=timezone.utc)
            if data_range.latest_timestamp.tzinfo is None
            else data_range.latest_timestamp
        )
        assert earliest == synthetic_candles[0].timestamp
        assert latest == synthetic_candles[-1].timestamp


@pytest.mark.asyncio
async def test_e2e_reliance_15m_cache_hit_avoids_provider(e2e_env):
    """Scenario 2: Subsequent fetch for same or sub-range serves 100% from DB cache with 0 provider calls."""
    client = e2e_env["client"]
    provider = e2e_env["provider"]

    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t_end = t0 + timedelta(days=2)
    synthetic_candles = _generate_synthetic_candles(t0, count=50, interval_minutes=15)

    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=synthetic_candles,
        count=len(synthetic_candles),
    )

    # Initial call
    await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t_end.isoformat(),
        },
    )
    assert provider.get_historical_data.call_count == 1
    provider.get_historical_data.reset_mock()

    # Second call for a sub-window
    sub_start = t0 + timedelta(hours=2)
    sub_end = t0 + timedelta(hours=6)
    sub_resp = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": sub_start.isoformat(),
            "end_date": sub_end.isoformat(),
        },
    )

    assert sub_resp.status_code == 200
    sub_data = sub_resp.json()
    assert sub_data["count"] > 0
    # Provider must NOT have been called because data is in cache
    assert provider.get_historical_data.call_count == 0


@pytest.mark.asyncio
async def test_e2e_incremental_range_expansion(e2e_env):
    """Scenario 3: Requesting an extended window only fetches the missing delta interval from provider."""
    client = e2e_env["client"]
    provider = e2e_env["provider"]
    session_factory = e2e_env["session_factory"]

    # Window 1: Day 1 (25 candles)
    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15 * 24)
    batch1 = _generate_synthetic_candles(t0, count=25, interval_minutes=15, base_price=2400.0)

    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=batch1,
        count=25,
    )

    # Fetch window 1
    resp1 = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t1.isoformat(),
        },
    )
    assert resp1.status_code == 200
    assert resp1.json()["count"] == 25
    assert provider.get_historical_data.call_count == 1

    # Window 2: Extends into Day 2 (additional 25 candles)
    t2 = t1 + timedelta(minutes=15 * 25)
    delta_start = t1 + timedelta(seconds=1)
    batch2 = _generate_synthetic_candles(
        delta_start, count=25, interval_minutes=15, base_price=2450.0
    )

    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=batch2,
        count=25,
    )

    # Fetch extended window [t0, t2]
    resp2 = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t2.isoformat(),
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["count"] == 50  # Combined 25 from DB + 25 new

    # Verify provider was only called for the missing right delta
    assert provider.get_historical_data.call_count == 2
    last_call_req: HistoricalDataRequest = provider.get_historical_data.call_args[0][0]
    assert last_call_req.start_date > t1  # Start date is strictly after previous latest timestamp

    # Verify total DB count is now 50
    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        total_in_db = (
            await db.execute(
                select(func.count(models.Candle.id)).where(models.Candle.instrument_id == inst.id)
            )
        ).scalar()
        assert total_in_db == 50


@pytest.mark.asyncio
async def test_e2e_multi_instrument_and_timeframe_isolation(e2e_env):
    """Scenario 4: Multi-instrument and multi-timeframe queries maintain independent cache states."""
    client = e2e_env["client"]
    provider = e2e_env["provider"]
    session_factory = e2e_env["session_factory"]

    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t_end = t0 + timedelta(days=1)

    # 1. Fetch RELIANCE 15m
    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=_generate_synthetic_candles(t0, 10, 15, 2500.0),
        count=10,
    )
    r1 = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t_end.isoformat(),
        },
    )
    assert r1.status_code == 200
    assert r1.json()["count"] == 10

    # 2. Fetch RELIANCE 1d (same instrument, different timeframe)
    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="1d",
        candles=_generate_synthetic_candles(t0, 5, 1440, 2500.0),
        count=5,
    )
    r2 = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "1d",
            "start_date": t0.isoformat(),
            "end_date": (t0 + timedelta(days=5)).isoformat(),
        },
    )
    assert r2.status_code == 200
    assert r2.json()["count"] == 5

    # 3. Fetch NIFTY 50 15m (different instrument, same timeframe)
    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="NIFTY 50",
        timeframe="15m",
        candles=_generate_synthetic_candles(t0, 12, 15, 22000.0),
        count=12,
    )
    r3 = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "NIFTY 50",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t_end.isoformat(),
            "instrument_type": "INDEX",
        },
    )
    assert r3.status_code == 200
    assert r3.json()["count"] == 12

    # Verify DB metadata has 3 distinct MarketDataRange records
    async with session_factory() as db:
        ranges = (await db.execute(select(models.MarketDataRange))).scalars().all()
        assert len(ranges) == 3


@pytest.mark.asyncio
async def test_e2e_graceful_handling_of_provider_failures(e2e_env):
    """Scenario 5: OpenChart/provider network errors or empty data fail gracefully without crashing."""
    client = e2e_env["client"]
    provider = e2e_env["provider"]

    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t_end = t0 + timedelta(days=1)

    # 1. Provider raises exception
    provider.get_historical_data.side_effect = RuntimeError("OpenChart connection timeout")

    res = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "SBIN",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t_end.isoformat(),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "SBIN"
    assert data["candles"] == []
    assert data["count"] == 0

    # 2. Provider returns empty candles
    provider.get_historical_data.side_effect = None
    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="SBIN",
        timeframe="15m",
        candles=[],
        count=0,
    )

    res2 = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "SBIN",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": t_end.isoformat(),
        },
    )
    assert res2.status_code == 200
    assert res2.json()["candles"] == []


@pytest.mark.asyncio
async def test_e2e_path_and_latest_endpoints(e2e_env):
    """Scenario 6: Path-based /historical and /latest endpoints function seamlessly in the flow."""
    client = e2e_env["client"]
    provider = e2e_env["provider"]

    t0 = datetime(2025, 2, 3, 9, 15, tzinfo=timezone.utc)
    t_end = t0 + timedelta(days=1)

    # Historical via path
    provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="INFY",
        timeframe="15m",
        candles=_generate_synthetic_candles(t0, 8, 15, 1850.0),
        count=8,
    )

    hist_resp = await client.get(
        "/api/v1/market-data/INFY/historical",
        params={"timeframe": "15m", "start_date": t0.isoformat(), "end_date": t_end.isoformat()},
    )
    assert hist_resp.status_code == 200
    assert hist_resp.json()["count"] == 8

    # Latest candle
    latest_c = _generate_synthetic_candles(t0 + timedelta(hours=6), 1, 15, 1870.0)[0]
    provider.get_latest_data.return_value = latest_c

    latest_resp = await client.get(
        "/api/v1/market-data/INFY/latest",
        params={"timeframe": "15m"},
    )
    assert latest_resp.status_code == 200
    latest_data = latest_resp.json()
    assert latest_data["symbol"] == "INFY"
    assert latest_data["candle"] is not None
    assert latest_data["candle"]["close"] == latest_c.close
