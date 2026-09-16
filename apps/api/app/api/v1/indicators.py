"""Quantitative Indicators & Market Regime REST API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.indicators.schemas import (
    IndicatorSeries,
    IndicatorSnapshotResponse,
    MarketRegimeResponse,
)
from app.indicators.service import IndicatorService, get_indicator_service
from app.market_data.openchart_adapter import NSEPublicProvider

router = APIRouter(prefix="/indicators", tags=["indicators"])


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
    "/{symbol}",
    response_model=IndicatorSeries,
    summary="Get calculated indicator time series",
    description="Fetch historical OHLCV candles and compute aligned time-series for EMA, SMA, RSI, MACD, ATR, and Market Regimes.",
)
async def get_indicator_series(
    symbol: str,
    timeframe: str = Query("15m", description="Candle interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)"),
    start_date: Optional[datetime] = Query(
        None,
        description="Start of historical window (UTC ISO 8601, defaults to 60 days before end_date)",
    ),
    end_date: Optional[datetime] = Query(
        None, description="End of historical window (UTC ISO 8601, defaults to now)"
    ),
    instrument_type: str = Query("EQUITY", description="EQUITY or INDEX"),
    db: AsyncSession = Depends(get_db_session),
    service: IndicatorService = Depends(get_indicator_service),
) -> IndicatorSeries:
    """Compute and return full historical technical indicator and market regime time series."""
    clean_tf = _validate_timeframe_and_range(timeframe, start_date, end_date)
    return await service.get_indicator_series(
        db=db,
        symbol=symbol,
        timeframe=clean_tf,
        start_date=start_date,
        end_date=end_date,
        instrument_type=instrument_type,
    )


@router.get(
    "/{symbol}/latest",
    response_model=IndicatorSnapshotResponse,
    summary="Get latest indicator state snapshot",
    description="Fetch the single most recent completed candle's indicator snapshot, trend regime, and volatility regime.",
)
async def get_latest_indicator_snapshot(
    symbol: str,
    timeframe: str = Query("15m", description="Candle interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)"),
    lookback_days: int = Query(60, ge=1, le=365, description="Historical warmup window in days"),
    instrument_type: str = Query("EQUITY", description="EQUITY or INDEX"),
    db: AsyncSession = Depends(get_db_session),
    service: IndicatorService = Depends(get_indicator_service),
) -> IndicatorSnapshotResponse:
    """Compute and return the latest single-candle indicator snapshot."""
    clean_tf = _validate_timeframe_and_range(timeframe)
    return await service.get_indicator_snapshot(
        db=db,
        symbol=symbol,
        timeframe=clean_tf,
        lookback_days=lookback_days,
        instrument_type=instrument_type,
    )


@router.get(
    "/{symbol}/regime",
    response_model=MarketRegimeResponse,
    summary="Get current descriptive market regime",
    description="Fetch the latest descriptive TrendRegime and VolatilityRegime classifications with quantitative supporting evidence.",
)
async def get_current_market_regime(
    symbol: str,
    timeframe: str = Query("15m", description="Candle interval (e.g. 1m, 5m, 15m, 30m, 1h, 1d)"),
    lookback_days: int = Query(60, ge=1, le=365, description="Historical warmup window in days"),
    instrument_type: str = Query("EQUITY", description="EQUITY or INDEX"),
    db: AsyncSession = Depends(get_db_session),
    service: IndicatorService = Depends(get_indicator_service),
) -> MarketRegimeResponse:
    """Compute and return standalone market regime snapshot with supporting signals and metrics."""
    clean_tf = _validate_timeframe_and_range(timeframe)
    return await service.get_market_regime(
        db=db,
        symbol=symbol,
        timeframe=clean_tf,
        lookback_days=lookback_days,
        instrument_type=instrument_type,
    )
