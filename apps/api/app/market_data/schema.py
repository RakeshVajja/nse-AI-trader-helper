"""Pydantic schemas for Market Data Provider layer."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CandleData(BaseModel):
    """Normalized OHLCV candlestick bar."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="UTC Timestamp of candle open")
    open: float = Field(..., description="Open price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Close price")
    volume: float = Field(default=0.0, description="Trading volume")


class InstrumentInfo(BaseModel):
    """Instrument metadata."""

    symbol: str = Field(..., description="NSE Symbol (e.g. RELIANCE, NIFTY 50)")
    name: str = Field(..., description="Company name or Index description")
    exchange: str = Field(default="NSE", description="Exchange identifier")
    instrument_type: str = Field(default="EQUITY", description="EQUITY or INDEX")
    is_active: bool = Field(default=True, description="Active trading status")


class HistoricalDataRequest(BaseModel):
    """Request parameter for fetching historical OHLCV data."""

    symbol: str = Field(..., description="NSE Trading symbol")
    timeframe: str = Field(default="15m", description="Candle interval (e.g. 1m, 5m, 15m, 1h, 1d)")
    start_date: datetime = Field(..., description="Start of historical window (UTC)")
    end_date: datetime = Field(..., description="End of historical window (UTC)")
    instrument_type: str = Field(default="EQUITY", description="EQUITY or INDEX")


class HistoricalDataResponse(BaseModel):
    """Response containing validated OHLCV candles."""

    symbol: str
    timeframe: str
    candles: List[CandleData] = Field(default_factory=list)
    count: int = 0


class InstrumentResponse(BaseModel):
    """Pydantic model for API instrument responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str
    exchange: str = "NSE"
    instrument_type: str
    is_active: bool = True
    created_at: Optional[datetime] = None


class InstrumentListResponse(BaseModel):
    """Paginated response of instruments."""

    instruments: List[InstrumentResponse] = Field(default_factory=list)
    total: int = 0
    count: int = 0


class LatestCandleResponse(BaseModel):
    """Response containing the latest single candle."""

    symbol: str
    timeframe: str
    candle: Optional[CandleData] = None
