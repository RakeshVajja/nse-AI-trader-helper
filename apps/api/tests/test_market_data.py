"""Unit and integration tests for MarketDataProvider and NSEPublicProvider."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.market_data.base import MarketDataProvider
from app.market_data.openchart_adapter import NSEPublicProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataRequest,
    HistoricalDataResponse,
    InstrumentInfo,
)


def test_schema_instantiation():
    """Verify CandleData and request/response schema creation and validation."""
    now = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candle = CandleData(
        timestamp=now,
        open=2500.0,
        high=2520.0,
        low=2490.0,
        close=2510.0,
        volume=100000.0,
    )
    assert candle.close == 2510.0
    assert candle.timestamp.tzinfo == timezone.utc

    req = HistoricalDataRequest(
        symbol="RELIANCE",
        timeframe="15m",
        start_date=now,
        end_date=now,
        instrument_type="EQUITY",
    )
    assert req.symbol == "RELIANCE"

    resp = HistoricalDataResponse(
        symbol="RELIANCE",
        timeframe="15m",
        candles=[candle],
        count=1,
    )
    assert resp.count == 1
    assert resp.candles[0].open == 2500.0


@pytest.mark.asyncio
async def test_nse_public_provider_contract():
    """Verify that NSEPublicProvider implements MarketDataProvider ABC."""
    provider = NSEPublicProvider()
    assert isinstance(provider, MarketDataProvider)


@pytest.mark.asyncio
async def test_nse_public_provider_dataframe_parsing():
    """Verify conversion of OpenChart OHLCV DataFrame into typed CandleData models."""
    mock_client = MagicMock()

    # Sample DataFrame matching openchart.historical output
    dates = pd.date_range("2025-01-15 09:15", periods=3, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "Open": [2500.0, 2510.0, 2505.0],
            "High": [2520.0, 2525.0, 2515.0],
            "Low": [2495.0, 2505.0, 2500.0],
            "Close": [2510.0, 2515.0, 2512.0],
            "Volume": [10000.0, 15000.0, 8000.0],
        },
        index=dates,
    )
    df.index.name = "Timestamp"
    mock_client.historical.return_value = df

    provider = NSEPublicProvider(nse_client=mock_client)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        timeframe="15m",
        start_date=datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 15, 9, 45, tzinfo=timezone.utc),
        instrument_type="EQUITY",
    )
    response = await provider.get_historical_data(req)

    assert response.symbol == "RELIANCE"
    assert response.timeframe == "15m"
    assert response.count == 3
    assert len(response.candles) == 3
    assert response.candles[0].open == 2500.0
    assert response.candles[0].high == 2520.0
    assert response.candles[0].close == 2510.0
    assert response.candles[0].volume == 10000.0
    assert response.candles[0].timestamp.tzinfo is not None

    mock_client.historical.assert_called_once_with(
        symbol="RELIANCE",
        segment="EQ",
        start=req.start_date,
        end=req.end_date,
        interval="15m",
    )


@pytest.mark.asyncio
async def test_nse_public_provider_index_segment_mapping():
    """Verify segment is correctly mapped to IDX for index instruments."""
    mock_client = MagicMock()
    mock_client.historical.return_value = pd.DataFrame()

    provider = NSEPublicProvider(nse_client=mock_client)
    req = HistoricalDataRequest(
        symbol="NIFTY 50",
        timeframe="1d",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 10, tzinfo=timezone.utc),
        instrument_type="INDEX",
    )
    await provider.get_historical_data(req)

    mock_client.historical.assert_called_once_with(
        symbol="NIFTY 50",
        segment="IDX",
        start=req.start_date,
        end=req.end_date,
        interval="1d",
    )


@pytest.mark.asyncio
async def test_nse_public_provider_empty_and_error_handling():
    """Verify graceful handling when OpenChart returns empty data or raises an exception."""
    mock_client = MagicMock()
    mock_client.historical.side_effect = Exception("API Network Timeout")

    provider = NSEPublicProvider(nse_client=mock_client)
    req = HistoricalDataRequest(
        symbol="INVALID",
        timeframe="15m",
        start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    response = await provider.get_historical_data(req)

    assert response.count == 0
    assert response.candles == []


@pytest.mark.asyncio
async def test_nse_public_provider_search():
    """Verify search_instruments parses search results into InstrumentInfo list."""
    mock_client = MagicMock()
    search_df = pd.DataFrame(
        [
            {
                "symbol": "RELIANCE",
                "description": "Reliance Industries Ltd",
                "type": "Equity",
                "exchange": "NSE",
            },
            {
                "symbol": "TCS",
                "description": "Tata Consultancy Services",
                "type": "Equity",
                "exchange": "NSE",
            },
        ]
    )
    mock_client.search.return_value = search_df

    provider = NSEPublicProvider(nse_client=mock_client)
    results = await provider.search_instruments("REL")

    assert len(results) == 2
    assert isinstance(results[0], InstrumentInfo)
    assert results[0].symbol == "RELIANCE"
    assert results[0].name == "Reliance Industries Ltd"


@pytest.mark.asyncio
async def test_nse_public_provider_get_latest_data():
    """Verify get_latest_data returns the most recent candle."""
    mock_client = MagicMock()
    dates = pd.date_range("2025-01-15 09:15", periods=2, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "Open": [2500.0, 2520.0],
            "High": [2510.0, 2530.0],
            "Low": [2490.0, 2515.0],
            "Close": [2505.0, 2525.0],
            "Volume": [1000.0, 2000.0],
        },
        index=dates,
    )
    df.index.name = "Timestamp"
    mock_client.historical.return_value = df

    provider = NSEPublicProvider(nse_client=mock_client)
    latest_candle = await provider.get_latest_data("RELIANCE", timeframe="15m")

    assert latest_candle is not None
    assert latest_candle.close == 2525.0
    assert latest_candle.volume == 2000.0


@pytest.mark.asyncio
async def test_nse_public_provider_symbol_resolution_and_aliases():
    """Verify common index symbol aliases resolve to canonical names and IDX segment."""
    provider = NSEPublicProvider()

    sym, seg = provider._resolve_symbol_and_segment("BANKNIFTY")
    assert sym == "NIFTY BANK"
    assert seg == "IDX"

    sym, seg = provider._resolve_symbol_and_segment("NIFTY50")
    assert sym == "NIFTY 50"
    assert seg == "IDX"

    sym, seg = provider._resolve_symbol_and_segment("NIFTY")
    assert sym == "NIFTY 50"
    assert seg == "IDX"

    sym, seg = provider._resolve_symbol_and_segment("INDIA VIX")
    assert sym == "INDIA VIX"
    assert seg == "IDX"

    sym, seg = provider._resolve_symbol_and_segment("INFY", "EQUITY")
    assert sym == "INFY"
    assert seg == "EQ"


def test_nse_public_provider_interval_normalization():
    """Verify timeframe aliases normalize to supported canonical values."""
    provider = NSEPublicProvider()

    assert provider._normalize_timeframe("daily") == "1d"
    assert provider._normalize_timeframe("day") == "1d"
    assert provider._normalize_timeframe("15min") == "15m"
    assert provider._normalize_timeframe("1hour") == "1h"
    assert provider._normalize_timeframe("weekly") == "1w"
    assert provider._normalize_timeframe("monthly") == "1M"
    assert provider._normalize_timeframe("5mins") == "5m"
    assert provider._normalize_timeframe("unknown") == "15m"


@pytest.mark.asyncio
async def test_nse_public_provider_search_fallback_to_index():
    """Verify search falls back to index search if equity search is empty."""
    mock_client = MagicMock()
    # First call (EQ) returns empty, second call (IDX) returns Nifty
    mock_client.search.side_effect = [
        pd.DataFrame(),
        pd.DataFrame(
            [
                {
                    "symbol": "NIFTY 50",
                    "description": "NIFTY 50 Index",
                    "type": "Index",
                    "exchange": "NSE",
                }
            ]
        ),
    ]

    provider = NSEPublicProvider(nse_client=mock_client)
    results = await provider.search_instruments("NIFTY")

    assert len(results) == 1
    assert results[0].symbol == "NIFTY 50"
    assert results[0].instrument_type == "INDEX"


@pytest.mark.asyncio
async def test_nse_public_provider_skips_zero_price_candles():
    """Verify candles with zero open/close prices are filtered out."""
    mock_client = MagicMock()
    dates = pd.date_range("2025-01-15 09:15", periods=2, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "Open": [0.0, 2500.0],
            "High": [0.0, 2510.0],
            "Low": [0.0, 2490.0],
            "Close": [0.0, 2505.0],
            "Volume": [0.0, 1000.0],
        },
        index=dates,
    )
    df.index.name = "Timestamp"
    mock_client.historical.return_value = df

    provider = NSEPublicProvider(nse_client=mock_client)
    req = HistoricalDataRequest(
        symbol="RELIANCE",
        timeframe="15m",
        start_date=datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc),
        end_date=datetime(2025, 1, 15, 9, 30, tzinfo=timezone.utc),
    )
    resp = await provider.get_historical_data(req)
    assert resp.count == 1
    assert resp.candles[0].open == 2500.0


@pytest.mark.asyncio
async def test_get_latest_data_lookback_spans_weekend():
    """G6 regression: Verify intraday lookback windows are wide enough to span a full weekend.

    If get_latest_data is called on a Monday morning before market open (or Saturday),
    the lookback must reach back to Friday's session.
    """
    provider = NSEPublicProvider()

    intraday_timeframes = ["1m", "3m", "5m", "10m", "15m", "30m", "1h"]
    for tf in intraday_timeframes:
        lookback = provider._LATEST_LOOKBACK.get(tf)
        assert lookback is not None, f"Missing lookback for timeframe {tf}"
        assert lookback.total_seconds() >= 3 * 86400, (
            f"Lookback for {tf} is {lookback}, must be >= 3 days to cover weekends"
        )


@pytest.mark.asyncio
async def test_get_latest_data_empty_provider_returns_none():
    """Verify get_latest_data returns None when provider has no data (e.g. weekend)."""
    mock_client = MagicMock()
    mock_client.historical.return_value = pd.DataFrame()

    provider = NSEPublicProvider(nse_client=mock_client)
    result = await provider.get_latest_data("RELIANCE", timeframe="15m")
    assert result is None
