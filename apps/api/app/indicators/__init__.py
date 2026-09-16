"""Quantitative Technical Indicator Engine package."""

from app.indicators.atr import (
    calculate_atr,
    calculate_atr_from_candles,
    calculate_atrp,
    calculate_true_range,
    get_latest_atr,
)
from app.indicators.ema import calculate_ema, calculate_ema_from_candles, get_latest_ema
from app.indicators.engine import (
    QuantitativeIndicatorEngine,
    get_indicator_engine,
)
from app.indicators.macd import (
    calculate_macd,
    calculate_macd_from_candles,
    get_latest_macd,
)
from app.indicators.regime import (
    classify_market_regime_snapshot,
    classify_trend_bar,
    classify_volatility_bar,
    compute_market_regimes_series,
)
from app.indicators.rsi import calculate_rsi, calculate_rsi_from_candles, get_latest_rsi
from app.indicators.schemas import (
    IndicatorPoint,
    IndicatorSeries,
    IndicatorSnapshot,
    IndicatorSnapshotResponse,
    MACDPoint,
    MACDValue,
    MarketRegimeResponse,
    MarketRegimeSnapshot,
    TrendRegime,
    TrendSignalDetails,
    VolatilityMetrics,
    VolatilityRegime,
)
from app.indicators.service import (
    IndicatorService,
    get_indicator_service,
)
from app.indicators.sma import calculate_sma, calculate_sma_from_candles, get_latest_sma

__all__ = [
    "IndicatorPoint",
    "IndicatorSeries",
    "IndicatorService",
    "IndicatorSnapshot",
    "IndicatorSnapshotResponse",
    "MACDPoint",
    "MACDValue",
    "MarketRegimeResponse",
    "MarketRegimeSnapshot",
    "QuantitativeIndicatorEngine",
    "TrendRegime",
    "TrendSignalDetails",
    "VolatilityMetrics",
    "VolatilityRegime",
    "calculate_atr",
    "calculate_atr_from_candles",
    "calculate_atrp",
    "calculate_ema",
    "calculate_ema_from_candles",
    "calculate_macd",
    "calculate_macd_from_candles",
    "calculate_rsi",
    "calculate_rsi_from_candles",
    "calculate_sma",
    "calculate_sma_from_candles",
    "calculate_true_range",
    "classify_market_regime_snapshot",
    "classify_trend_bar",
    "classify_volatility_bar",
    "compute_market_regimes_series",
    "get_indicator_engine",
    "get_indicator_service",
    "get_latest_atr",
    "get_latest_ema",
    "get_latest_macd",
    "get_latest_rsi",
    "get_latest_sma",
]
