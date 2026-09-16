"""Tests for REST API endpoints: Instruments and Market Data (Phase 3A)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.session import get_db_session
from app.main import app
from app.market_data.base import MarketDataProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataResponse,
)
from app.market_data.service import MarketDataService, get_market_data_service


def _make_candle(ts: datetime, close: float = 2500.0) -> CandleData:
    return CandleData(
        timestamp=ts,
        open=close - 5.0,
        high=close + 10.0,
        low=close - 10.0,
        close=close,
        volume=15000.0,
    )


@pytest.fixture
async def test_env():
    """Create isolated in-memory database and configured MarketDataService for API tests."""
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
async def test_list_instruments_auto_seeds_defaults(test_env):
    """GET /api/v1/instruments should auto-seed default instruments when empty."""
    client = test_env["client"]

    response = await client.get("/api/v1/instruments")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 10
    assert data["count"] == 10
    symbols = [inst["symbol"] for inst in data["instruments"]]
    assert "RELIANCE" in symbols
    assert "NIFTY 50" in symbols
    assert "TCS" in symbols


@pytest.mark.asyncio
async def test_list_instruments_search_and_filter(test_env):
    """GET /api/v1/instruments supports query searching and type filtering."""
    client = test_env["client"]

    # Filter by index
    idx_resp = await client.get("/api/v1/instruments?instrument_type=INDEX")
    assert idx_resp.status_code == 200
    idx_data = idx_resp.json()
    assert idx_data["total"] == 3
    for inst in idx_data["instruments"]:
        assert inst["instrument_type"] == "INDEX"

    # Search by symbol/name query
    search_resp = await client.get("/api/v1/instruments?query=tcs")
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["total"] == 1
    assert search_data["instruments"][0]["symbol"] == "TCS"

    # Pagination
    page_resp = await client.get("/api/v1/instruments?limit=3&offset=2")
    assert page_resp.status_code == 200
    page_data = page_resp.json()
    assert page_data["total"] == 10
    assert page_data["count"] == 3
    assert len(page_data["instruments"]) == 3


@pytest.mark.asyncio
async def test_seed_instruments_endpoint(test_env):
    """POST /api/v1/instruments/seed explicitly seeds default instruments."""
    client = test_env["client"]

    response = await client.post("/api/v1/instruments/seed")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 10
    assert len(data["instruments"]) == 10


@pytest.mark.asyncio
async def test_get_instrument_by_symbol(test_env):
    """GET /api/v1/instruments/{symbol} returns details or 404."""
    client = test_env["client"]

    # Trigger seeding first by listing
    await client.get("/api/v1/instruments")

    # Existing instrument
    response = await client.get("/api/v1/instruments/RELIANCE")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert data["name"] == "Reliance Industries Ltd"
    assert data["instrument_type"] == "EQUITY"
    assert data["exchange"] == "NSE"

    # Non-existent instrument
    not_found = await client.get("/api/v1/instruments/UNKNOWN_SYM")
    assert not_found.status_code == 404
    assert "not found" in not_found.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_candles_query_endpoint(test_env):
    """GET /api/v1/market-data/candles retrieves candles with on-demand caching."""
    client = test_env["client"]
    mock_provider = test_env["provider"]

    t0 = datetime(2025, 2, 1, 9, 15, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=15)
    t2 = t0 + timedelta(minutes=30)
    mock_candles = [_make_candle(t0, 2500.0), _make_candle(t1, 2510.0), _make_candle(t2, 2520.0)]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=mock_candles,
        count=3,
    )

    response = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": (t0 + timedelta(days=1)).isoformat(),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "RELIANCE"
    assert data["timeframe"] == "15m"
    assert data["count"] == 3
    assert len(data["candles"]) == 3
    assert data["candles"][0]["close"] == 2500.0


@pytest.mark.asyncio
async def test_get_symbol_historical_endpoint(test_env):
    """GET /api/v1/market-data/{symbol}/historical retrieves candles by path param."""
    client = test_env["client"]
    mock_provider = test_env["provider"]

    t0 = datetime(2025, 2, 1, 9, 15, tzinfo=timezone.utc)
    mock_candles = [_make_candle(t0, 18000.0)]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="NIFTY 50",
        timeframe="15m",
        candles=mock_candles,
        count=1,
    )

    response = await client.get(
        "/api/v1/market-data/NIFTY 50/historical",
        params={
            "timeframe": "15m",
            "start_date": t0.isoformat(),
            "end_date": (t0 + timedelta(days=1)).isoformat(),
            "instrument_type": "INDEX",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "NIFTY 50"
    assert data["count"] == 1
    assert data["candles"][0]["close"] == 18000.0


@pytest.mark.asyncio
async def test_get_symbol_latest_endpoint(test_env):
    """GET /api/v1/market-data/{symbol}/latest returns the most recent completed candle."""
    client = test_env["client"]
    mock_provider = test_env["provider"]

    t0 = datetime(2025, 2, 1, 15, 15, tzinfo=timezone.utc)
    mock_provider.get_latest_data.return_value = _make_candle(t0, 3500.0)

    response = await client.get(
        "/api/v1/market-data/TCS/latest",
        params={"timeframe": "15m"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TCS"
    assert data["timeframe"] == "15m"
    assert data["candle"] is not None
    assert data["candle"]["close"] == 3500.0


@pytest.mark.asyncio
async def test_validation_errors(test_env):
    """Validate invalid inputs yield appropriate 400 or 422 HTTP responses."""
    client = test_env["client"]

    # 1. Unsupported timeframe -> 400
    t0 = datetime(2025, 2, 1, 9, 15, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=1)
    res = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "999invalid",
            "start_date": t0.isoformat(),
            "end_date": t1.isoformat(),
        },
    )
    assert res.status_code == 400
    assert "Unsupported timeframe" in res.json()["detail"]

    # 2. start_date > end_date -> 400
    res = await client.get(
        "/api/v1/market-data/candles",
        params={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": t1.isoformat(),
            "end_date": t0.isoformat(),
        },
    )
    assert res.status_code == 400
    assert "must be before or equal" in res.json()["detail"]

    # 3. Missing required start_date -> 422
    res = await client.get(
        "/api/v1/market-data/candles",
        params={"symbol": "RELIANCE", "timeframe": "15m"},
    )
    assert res.status_code == 422
