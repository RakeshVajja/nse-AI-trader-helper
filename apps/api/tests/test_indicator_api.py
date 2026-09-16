"""Integration and API unit tests for Phase 4C: Indicator & Market Regime Endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.session import get_db_session
from app.indicators.engine import QuantitativeIndicatorEngine
from app.indicators.service import IndicatorService, get_indicator_service
from app.main import app
from app.market_data.base import MarketDataProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataResponse,
)
from app.market_data.service import MarketDataService, get_market_data_service


def _generate_synthetic_candles(
    count: int = 150,
    base_price: float = 2500.0,
    start_time: datetime | None = None,
) -> list[CandleData]:
    """Generate deterministic sequence of candles for indicator testing."""
    base_ts = start_time or (datetime.now(timezone.utc) - timedelta(minutes=15 * count))
    candles = []
    for i in range(count):
        # Create an upward-trending sequence with mild oscillation
        price = base_price + (i * 1.5) + ((i % 5) * 0.8)
        candles.append(
            CandleData(
                timestamp=base_ts + timedelta(minutes=15 * i),
                open=price - 2.0,
                high=price + 5.0,
                low=price - 3.0,
                close=price,
                volume=10000.0 + i * 50,
            )
        )
    return candles


@pytest.fixture
async def indicator_api_env():
    """Create isolated in-memory DB, mocked provider, and configured services for indicator API tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    mock_provider = AsyncMock(spec=MarketDataProvider)
    market_service = MarketDataService(provider=mock_provider)
    indicator_engine = QuantitativeIndicatorEngine()
    indicator_service = IndicatorService(
        market_data_service=market_service,
        indicator_engine=indicator_engine,
    )

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_market_service():
        return market_service

    def override_get_indicator_service():
        return indicator_service

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_market_data_service] = override_get_market_service
    app.dependency_overrides[get_indicator_service] = override_get_indicator_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "mock_provider": mock_provider,
            "market_service": market_service,
            "indicator_service": indicator_service,
            "session_factory": session_factory,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_indicator_series_endpoint(indicator_api_env):
    """GET /api/v1/indicators/{symbol} should return full calculated indicator and regime series."""
    client = indicator_api_env["client"]
    mock_provider = indicator_api_env["mock_provider"]

    # Mock provider to return 150 candles
    candles = _generate_synthetic_candles(count=150, base_price=2500.0)
    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=candles,
        count=len(candles),
    )

    start_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    response = await client.get(
        "/api/v1/indicators/RELIANCE",
        params={"timeframe": "15m", "start_date": start_date},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "RELIANCE"
    assert data["timeframe"] == "15m"
    assert data["count"] == 150
    assert len(data["timestamps"]) == 150
    assert len(data["closes"]) == 150
    assert len(data["ema9"]) == 150
    assert len(data["ema20"]) == 150
    assert len(data["sma50"]) == 150
    assert len(data["rsi14"]) == 150
    assert len(data["macd_line"]) == 150
    assert len(data["macd_signal"]) == 150
    assert len(data["macd_histogram"]) == 150
    assert len(data["atr14"]) == 150
    assert len(data["atrp14"]) == 150
    assert len(data["trend_regimes"]) == 150
    assert len(data["volatility_regimes"]) == 150

    # Verify warmup properties in series:
    # SMA50 has first 49 values as null/None
    assert data["sma50"][0] is None
    assert data["sma50"][48] is None
    assert data["sma50"][49] is not None

    # Trend regime is None before bar 50
    assert data["trend_regimes"][0] is None
    assert data["trend_regimes"][-1] in ["BULLISH", "BEARISH", "SIDEWAYS"]

    # Volatility regime is None before 100 valid ATRP observations
    assert data["volatility_regimes"][0] is None
    assert data["volatility_regimes"][-1] in ["HIGH", "NORMAL", "LOW"]


@pytest.mark.asyncio
async def test_get_latest_indicator_snapshot_endpoint(indicator_api_env):
    """GET /api/v1/indicators/{symbol}/latest should return latest single-candle snapshot and regimes."""
    client = indicator_api_env["client"]
    mock_provider = indicator_api_env["mock_provider"]

    candles = _generate_synthetic_candles(count=150, base_price=1000.0)
    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="TCS",
        timeframe="15m",
        candles=candles,
        count=len(candles),
    )

    response = await client.get("/api/v1/indicators/TCS/latest", params={"timeframe": "15m"})
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "TCS"
    assert data["timeframe"] == "15m"
    assert data["snapshot"] is not None

    snap = data["snapshot"]
    assert snap["close"] == candles[-1].close
    assert snap["ema9"] is not None
    assert snap["ema20"] is not None
    assert snap["sma50"] is not None
    assert snap["rsi14"] is not None
    assert snap["macd"] is not None
    assert snap["atr14"] is not None
    assert snap["atrp14"] is not None

    # Verify regime classifications in snapshot
    assert snap["trend_regime"] in ["BULLISH", "BEARISH", "SIDEWAYS"]
    assert snap["volatility_regime"] in ["HIGH", "NORMAL", "LOW"]
    assert snap["trend_details"] is not None
    assert snap["trend_details"]["bullish_votes"] >= 0
    assert snap["trend_details"]["bearish_votes"] >= 0
    assert snap["volatility_details"] is not None
    assert snap["volatility_details"]["sample_count"] == 100


@pytest.mark.asyncio
async def test_get_current_market_regime_endpoint(indicator_api_env):
    """GET /api/v1/indicators/{symbol}/regime should return standalone descriptive regime snapshot."""
    client = indicator_api_env["client"]
    mock_provider = indicator_api_env["mock_provider"]

    candles = _generate_synthetic_candles(count=150, base_price=1500.0)
    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="INFY",
        timeframe="15m",
        candles=candles,
        count=len(candles),
    )

    response = await client.get("/api/v1/indicators/INFY/regime", params={"timeframe": "15m"})
    assert response.status_code == 200
    data = response.json()

    assert data["symbol"] == "INFY"
    assert data["timeframe"] == "15m"
    assert data["regime"] is not None

    regime = data["regime"]
    assert regime["trend_regime"] in ["BULLISH", "BEARISH", "SIDEWAYS"]
    assert regime["volatility_regime"] in ["HIGH", "NORMAL", "LOW"]
    assert regime["trend_details"] is not None
    assert regime["volatility_details"] is not None
    assert regime["volatility_details"]["sample_count"] == 100


@pytest.mark.asyncio
async def test_indicator_endpoints_validation_errors(indicator_api_env):
    """Verify indicator endpoints validate timeframes and date ranges with HTTP 400."""
    client = indicator_api_env["client"]

    # 1. Invalid timeframe
    resp_bad_tf = await client.get(
        "/api/v1/indicators/RELIANCE",
        params={"timeframe": "45m"},
    )
    assert resp_bad_tf.status_code == 400
    assert "Unsupported timeframe" in resp_bad_tf.json()["detail"]

    # 2. Invalid date range (start_date > end_date)
    now = datetime.now(timezone.utc)
    resp_bad_range = await client.get(
        "/api/v1/indicators/RELIANCE",
        params={
            "timeframe": "15m",
            "start_date": (now + timedelta(days=5)).isoformat(),
            "end_date": now.isoformat(),
        },
    )
    assert resp_bad_range.status_code == 400
    assert "must be before or equal to end_date" in resp_bad_range.json()["detail"]


@pytest.mark.asyncio
async def test_indicator_service_empty_candles(indicator_api_env):
    """Verify indicator endpoints handle empty candle history gracefully."""
    client = indicator_api_env["client"]
    mock_provider = indicator_api_env["mock_provider"]

    mock_provider.get_historical_data.return_value = HistoricalDataResponse(
        symbol="EMPTY_SYM",
        timeframe="15m",
        candles=[],
        count=0,
    )

    resp_series = await client.get(
        "/api/v1/indicators/EMPTY_SYM",
        params={"timeframe": "15m"},
    )
    assert resp_series.status_code == 200
    assert resp_series.json()["count"] == 0

    resp_latest = await client.get(
        "/api/v1/indicators/EMPTY_SYM/latest",
        params={"timeframe": "15m"},
    )
    assert resp_latest.status_code == 200
    assert resp_latest.json()["snapshot"] is None
