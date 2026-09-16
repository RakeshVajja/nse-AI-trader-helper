"""Pydantic schemas for technical indicators and quantitative calculations."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TrendRegime(str, Enum):
    """Deterministic market trend regime classification."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"


class VolatilityRegime(str, Enum):
    """Deterministic market volatility regime classification."""

    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class MACDValue(BaseModel):
    """MACD indicator components."""

    model_config = ConfigDict(frozen=True)

    macd: Optional[float] = Field(None, description="MACD line (Fast EMA - Slow EMA)")
    signal: Optional[float] = Field(None, description="Signal line (EMA of MACD line)")
    histogram: Optional[float] = Field(None, description="MACD Histogram (MACD - Signal)")


class TrendSignalDetails(BaseModel):
    """Supporting quantitative evidence for 3-of-4 trend regime voting."""

    model_config = ConfigDict(frozen=True)

    close_vs_sma50: Optional[str] = Field(
        None, description="Signal from Close vs SMA50 (BULLISH, BEARISH, or NEUTRAL)"
    )
    ema9_vs_ema20: Optional[str] = Field(
        None, description="Signal from EMA9 vs EMA20 (BULLISH, BEARISH, or NEUTRAL)"
    )
    macd_vs_zero: Optional[str] = Field(
        None, description="Signal from MACD Line vs Zero (BULLISH, BEARISH, or NEUTRAL)"
    )
    rsi14_vs_50: Optional[str] = Field(
        None, description="Signal from RSI14 vs 50 (BULLISH, BEARISH, or NEUTRAL)"
    )
    bullish_votes: int = Field(default=0, description="Total bullish votes (0 to 4)")
    bearish_votes: int = Field(default=0, description="Total bearish votes (0 to 4)")


class VolatilityMetrics(BaseModel):
    """Supporting quantitative evidence for historical rolling volatility regime classification."""

    model_config = ConfigDict(frozen=True)

    current_atrp14: Optional[float] = Field(None, description="Current candle ATRP14 (%)")
    p20_threshold: Optional[float] = Field(
        None, description="20th percentile threshold from previous 100 valid ATRP14 observations"
    )
    p80_threshold: Optional[float] = Field(
        None, description="80th percentile threshold from previous 100 valid ATRP14 observations"
    )
    sample_count: int = Field(
        default=0,
        description="Number of valid historical ATRP14 observations strictly before current candle",
    )


class MarketRegimeSnapshot(BaseModel):
    """Descriptive market state regime snapshot."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="UTC timestamp of the candle")
    trend_regime: Optional[TrendRegime] = Field(
        None, description="Descriptive trend classification (BULLISH, BEARISH, SIDEWAYS, or None)"
    )
    volatility_regime: Optional[VolatilityRegime] = Field(
        None, description="Descriptive volatility classification (HIGH, NORMAL, LOW, or None)"
    )
    trend_details: Optional[TrendSignalDetails] = Field(
        None, description="Quantitative vote breakdown for trend classification"
    )
    volatility_details: Optional[VolatilityMetrics] = Field(
        None, description="Quantitative thresholds and sample counts for volatility classification"
    )


class IndicatorSnapshot(BaseModel):
    """Latest calculated quantitative indicator snapshot for an instrument."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="UTC timestamp of the candle")
    close: float = Field(..., description="Close price")
    volume: float = Field(default=0.0, description="Volume")
    ema9: Optional[float] = Field(None, description="9-period Exponential Moving Average")
    ema20: Optional[float] = Field(None, description="20-period Exponential Moving Average")
    sma50: Optional[float] = Field(None, description="50-period Simple Moving Average")
    rsi14: Optional[float] = Field(None, description="14-period Relative Strength Index (0-100)")
    macd: Optional[float] = Field(None, description="MACD line (12, 26)")
    macd_signal: Optional[float] = Field(None, description="MACD signal line (9)")
    macd_histogram: Optional[float] = Field(None, description="MACD histogram")
    atr14: Optional[float] = Field(None, description="14-period Average True Range")
    atrp14: Optional[float] = Field(
        None, description="14-period ATR Percentage (ATR14 / Close * 100)"
    )
    trend_regime: Optional[TrendRegime] = Field(
        None, description="Descriptive trend classification"
    )
    volatility_regime: Optional[VolatilityRegime] = Field(
        None, description="Descriptive volatility classification"
    )
    trend_details: Optional[TrendSignalDetails] = Field(
        None, description="Supporting trend signals"
    )
    volatility_details: Optional[VolatilityMetrics] = Field(
        None, description="Supporting volatility metrics"
    )


class IndicatorPoint(BaseModel):
    """Time-series point for chart indicator overlay."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="UTC timestamp")
    value: Optional[float] = Field(None, description="Indicator numerical value or None if warmup")


class MACDPoint(BaseModel):
    """Time-series point for MACD overlay."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(..., description="UTC timestamp")
    macd: Optional[float] = Field(None, description="MACD line")
    signal: Optional[float] = Field(None, description="Signal line")
    histogram: Optional[float] = Field(None, description="Histogram value")


class IndicatorSeries(BaseModel):
    """Full historical time-series of calculated technical indicators and market regimes."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading symbol (e.g. RELIANCE)")
    timeframe: str = Field(..., description="Timeframe interval (e.g. 15m)")
    timestamps: List[datetime] = Field(default_factory=list, description="List of UTC timestamps")
    closes: List[float] = Field(default_factory=list, description="List of close prices")
    ema9: List[Optional[float]] = Field(default_factory=list, description="EMA 9 series")
    ema20: List[Optional[float]] = Field(default_factory=list, description="EMA 20 series")
    sma50: List[Optional[float]] = Field(default_factory=list, description="SMA 50 series")
    rsi14: List[Optional[float]] = Field(default_factory=list, description="RSI 14 series")
    macd_line: List[Optional[float]] = Field(default_factory=list, description="MACD line series")
    macd_signal: List[Optional[float]] = Field(
        default_factory=list, description="MACD signal series"
    )
    macd_histogram: List[Optional[float]] = Field(
        default_factory=list, description="MACD histogram series"
    )
    atr14: List[Optional[float]] = Field(default_factory=list, description="ATR 14 series")
    atrp14: List[Optional[float]] = Field(default_factory=list, description="ATRP 14 series")
    trend_regimes: List[Optional[TrendRegime]] = Field(
        default_factory=list, description="Trend regime series"
    )
    volatility_regimes: List[Optional[VolatilityRegime]] = Field(
        default_factory=list, description="Volatility regime series"
    )
    count: int = 0


class IndicatorSnapshotResponse(BaseModel):
    """API response model for latest indicator snapshot."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading symbol (e.g. RELIANCE)")
    timeframe: str = Field(..., description="Timeframe interval (e.g. 15m)")
    snapshot: Optional[IndicatorSnapshot] = Field(
        None, description="Latest calculated indicator snapshot or None if no data"
    )


class MarketRegimeResponse(BaseModel):
    """API response model for standalone descriptive market regime."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading symbol (e.g. RELIANCE)")
    timeframe: str = Field(..., description="Timeframe interval (e.g. 15m)")
    regime: Optional[MarketRegimeSnapshot] = Field(
        None, description="Latest market regime snapshot or None if no data"
    )
