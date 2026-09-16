"""Market Data Provider layer."""

from app.market_data.base import MarketDataProvider
from app.market_data.openchart_adapter import NSEPublicProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataRequest,
    HistoricalDataResponse,
    InstrumentInfo,
    InstrumentListResponse,
    InstrumentResponse,
    LatestCandleResponse,
)
from app.market_data.service import (
    DEFAULT_SUPPORTED_INSTRUMENTS,
    MarketDataService,
    calculate_missing_ranges,
    get_market_data_service,
)
from app.market_data.validator import (
    OHLCVValidationError,
    is_chronologically_sorted,
    validate_and_clean_candles,
    validate_candle,
)

__all__ = [
    "DEFAULT_SUPPORTED_INSTRUMENTS",
    "CandleData",
    "HistoricalDataRequest",
    "HistoricalDataResponse",
    "InstrumentInfo",
    "InstrumentListResponse",
    "InstrumentResponse",
    "LatestCandleResponse",
    "MarketDataProvider",
    "MarketDataService",
    "NSEPublicProvider",
    "OHLCVValidationError",
    "calculate_missing_ranges",
    "get_market_data_service",
    "is_chronologically_sorted",
    "validate_and_clean_candles",
    "validate_candle",
]
