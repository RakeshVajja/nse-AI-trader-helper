"""Market Data REST API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.market_data.openchart_adapter import NSEPublicProvider
from app.market_data.schema import (
    HistoricalDataResponse,
    LatestCandleResponse,
)
from app.market_data.service import MarketDataService, get_market_data_service

router = APIRouter(prefix="/market-data", tags=["market-data"])


def _validate_timeframe_and_range(
    timeframe: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> str:
    """Validate requested timeframe and date range boundaries."""
    norm_tf = timeframe.strip()
    if norm_tf not in NSEPublicProvider.SUPPORTED_TIMEFRAMES:
        supported_str = ", ".join(sorted(NSEPublicProvider.SUPPORTED_TIMEFRAMES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported timeframe '{timeframe}'. Supported timeframes: {supported_str}",
        )

    if start_date is not None and end_date is not None:
        s_utc = start_date.replace(tzinfo=timezone.utc) if start_date.tzinfo is None else start_date
        e_utc = end_date.replace(tzinfo=timezone.utc) if end_date.tzinfo is None else end_date
        if s_utc > e_utc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"start_date ({start_date.isoformat()}) must be before or equal to end_date ({end_date.isoformat()})",
            )

    return norm_tf


@router.get(
    "/candles",
    response_model=HistoricalDataResponse,
    summary="Get historical OHLCV candles (Query Param)",
    description="Fetch historical OHLCV candlestick data with on-demand PostgreSQL caching and missing range retrieval.",
)
async def get_candles(
    symbol: str = Query(..., description="NSE Trading symbol (e.g. RELIANCE, NIFTY 50)"),
    timeframe: str = Query("15m", description="Candle interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)"),
    start_date: datetime = Query(..., description="Start of historical window (UTC ISO 8601)"),
    end_date: Optional[datetime] = Query(
        None, description="End of historical window (UTC ISO 8601, defaults to now)"
    ),
    instrument_type: str = Query("EQUITY", description="EQUITY or INDEX"),
    db: AsyncSession = Depends(get_db_session),
    service: MarketDataService = Depends(get_market_data_service),
) -> HistoricalDataResponse:
    """Fetch historical OHLCV candles with on-demand caching."""
    clean_tf = _validate_timeframe_and_range(timeframe, start_date, end_date)
    return await service.get_historical_candles(
        db=db,
        symbol=symbol,
        timeframe=clean_tf,
        start_date=start_date,
        end_date=end_date,
        instrument_type=instrument_type,
    )


@router.get(
    "/{symbol}/historical",
    response_model=HistoricalDataResponse,
    summary="Get historical OHLCV candles by symbol path",
    description="Fetch historical OHLCV candlestick data by symbol path with on-demand PostgreSQL caching.",
)
async def get_symbol_historical_candles(
    symbol: str,
    timeframe: str = Query("15m", description="Candle interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)"),
    start_date: datetime = Query(..., description="Start of historical window (UTC ISO 8601)"),
    end_date: Optional[datetime] = Query(
        None, description="End of historical window (UTC ISO 8601, defaults to now)"
    ),
    instrument_type: str = Query("EQUITY", description="EQUITY or INDEX"),
    db: AsyncSession = Depends(get_db_session),
    service: MarketDataService = Depends(get_market_data_service),
) -> HistoricalDataResponse:
    """Fetch historical OHLCV candles for symbol with on-demand caching."""
    clean_tf = _validate_timeframe_and_range(timeframe, start_date, end_date)
    return await service.get_historical_candles(
        db=db,
        symbol=symbol,
        timeframe=clean_tf,
        start_date=start_date,
        end_date=end_date,
        instrument_type=instrument_type,
    )


@router.get(
    "/{symbol}/latest",
    response_model=LatestCandleResponse,
    summary="Get latest completed candle",
    description="Fetch the single most recent completed candle for the specified instrument and timeframe.",
)
async def get_symbol_latest_candle(
    symbol: str,
    timeframe: str = Query("15m", description="Candle interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)"),
    db: AsyncSession = Depends(get_db_session),
    service: MarketDataService = Depends(get_market_data_service),
) -> LatestCandleResponse:
    """Fetch the latest completed candle for an instrument."""
    clean_tf = _validate_timeframe_and_range(timeframe)
    candle = await service.get_latest_candle(
        db=db,
        symbol=symbol,
        timeframe=clean_tf,
    )
    return LatestCandleResponse(
        symbol=symbol.strip().upper(),
        timeframe=clean_tf,
        candle=candle,
    )
