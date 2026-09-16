"""Indicator and Market Regime application service layer."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.indicators.engine import (
    QuantitativeIndicatorEngine,
    get_indicator_engine,
)
from app.indicators.schemas import (
    IndicatorSeries,
    IndicatorSnapshotResponse,
    MarketRegimeResponse,
)
from app.market_data.service import (
    MarketDataService,
    get_market_data_service,
)

logger = logging.getLogger(__name__)


class IndicatorService:
    """Coordinates indicator calculation requests with market data retrieval."""

    def __init__(
        self,
        market_data_service: Optional[MarketDataService] = None,
        indicator_engine: Optional[QuantitativeIndicatorEngine] = None,
    ) -> None:
        self.market_data_service = (
            market_data_service if market_data_service is not None else get_market_data_service()
        )
        self.indicator_engine = (
            indicator_engine if indicator_engine is not None else get_indicator_engine()
        )

    async def get_indicator_series(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str = "15m",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        instrument_type: str = "EQUITY",
    ) -> IndicatorSeries:
        """Fetch historical candles and compute complete aligned indicator time series.

        Args:
            db: Active AsyncSession database transaction.
            symbol: Trading symbol (e.g. RELIANCE).
            timeframe: Candle interval (e.g. 15m).
            start_date: Start of historical window (defaults to 60 days before end_date).
            end_date: End of historical window (defaults to now).
            instrument_type: EQUITY or INDEX.

        Returns:
            IndicatorSeries with calculated indicators, trend regimes, and volatility regimes.
        """
        now = datetime.now(timezone.utc)
        req_end = end_date or now
        req_start = start_date or (req_end - timedelta(days=60))

        hist_resp = await self.market_data_service.get_historical_candles(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
            start_date=req_start,
            end_date=req_end,
            instrument_type=instrument_type,
        )

        return self.indicator_engine.compute_series(
            symbol=hist_resp.symbol,
            timeframe=timeframe,
            candles=hist_resp.candles,
        )

    async def get_indicator_snapshot(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str = "15m",
        lookback_days: int = 60,
        instrument_type: str = "EQUITY",
    ) -> IndicatorSnapshotResponse:
        """Fetch recent candle history and compute the latest indicator state snapshot.

        Args:
            db: Active AsyncSession database transaction.
            symbol: Trading symbol.
            timeframe: Candle interval.
            lookback_days: Number of days to retrieve for indicator warmup (default 60 days).
            instrument_type: EQUITY or INDEX.

        Returns:
            IndicatorSnapshotResponse containing latest snapshot or None.
        """
        clean_symbol = symbol.strip().upper()
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=lookback_days)

        hist_resp = await self.market_data_service.get_historical_candles(
            db=db,
            symbol=clean_symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=now,
            instrument_type=instrument_type,
        )

        snapshot = self.indicator_engine.compute_snapshot(
            symbol=hist_resp.symbol,
            timeframe=timeframe,
            candles=hist_resp.candles,
        )

        return IndicatorSnapshotResponse(
            symbol=clean_symbol,
            timeframe=timeframe,
            snapshot=snapshot,
        )

    async def get_market_regime(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str = "15m",
        lookback_days: int = 60,
        instrument_type: str = "EQUITY",
    ) -> MarketRegimeResponse:
        """Fetch recent candle history and compute the latest descriptive market regime.

        Args:
            db: Active AsyncSession database transaction.
            symbol: Trading symbol.
            timeframe: Candle interval.
            lookback_days: Number of days to retrieve for indicator warmup (default 60 days).
            instrument_type: EQUITY or INDEX.

        Returns:
            MarketRegimeResponse with descriptive TrendRegime and VolatilityRegime.
        """
        clean_symbol = symbol.strip().upper()
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=lookback_days)

        hist_resp = await self.market_data_service.get_historical_candles(
            db=db,
            symbol=clean_symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=now,
            instrument_type=instrument_type,
        )

        regime = self.indicator_engine.compute_regime_snapshot(hist_resp.candles)

        return MarketRegimeResponse(
            symbol=clean_symbol,
            timeframe=timeframe,
            regime=regime,
        )


_indicator_service_instance: Optional[IndicatorService] = None


def get_indicator_service() -> IndicatorService:
    """Dependency provider returning singleton IndicatorService instance."""
    global _indicator_service_instance
    if _indicator_service_instance is None:
        _indicator_service_instance = IndicatorService()
    return _indicator_service_instance
