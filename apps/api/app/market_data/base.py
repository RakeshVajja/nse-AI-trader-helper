"""Market Data Provider Abstract Base Class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.market_data.schema import (
    CandleData,
    HistoricalDataRequest,
    HistoricalDataResponse,
    InstrumentInfo,
)


class MarketDataProvider(ABC):
    """Abstract interface isolating external market data sources (e.g. OpenChart, NSE, Yahoo)."""

    @abstractmethod
    async def get_historical_data(self, request: HistoricalDataRequest) -> HistoricalDataResponse:
        """Fetch historical OHLCV data for a given instrument and timeframe."""

    @abstractmethod
    async def get_latest_data(self, symbol: str, timeframe: str = "15m") -> Optional[CandleData]:
        """Fetch the most recent single candle for a given instrument."""

    @abstractmethod
    async def search_instruments(self, query: str) -> List[InstrumentInfo]:
        """Search available instruments matching the given query string."""
