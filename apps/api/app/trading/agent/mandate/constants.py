"""Constants, supported vocabularies, and normalization maps for Phase 8B Agent Mandate."""

from __future__ import annotations

from typing import Dict, Set

# Supported NSE Equities from Section 2
SUPPORTED_EQUITIES: Set[str] = {
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
}

# Supported NSE Indices from Section 2
SUPPORTED_INDICES: Set[str] = {
    "NIFTY 50",
    "BANK NIFTY",
    "NIFTY IT",
}

# Total supported instruments
SUPPORTED_INSTRUMENTS: Set[str] = SUPPORTED_EQUITIES | SUPPORTED_INDICES

# Supported Timeframes from Section 3
SUPPORTED_TIMEFRAMES: Set[str] = {
    "5m",
    "15m",
    "30m",
    "1h",
    "1d",
}

# Supported Technical Indicators from Section 13
SUPPORTED_INDICATORS: Set[str] = {
    "EMA9",
    "EMA20",
    "SMA50",
    "RSI14",
    "MACD",
    "ATR14",
}

# Indicator normalization mapping
INDICATOR_SYNONYMS: Dict[str, str] = {
    "ema9": "EMA9",
    "ema 9": "EMA9",
    "ema_9": "EMA9",
    "ema20": "EMA20",
    "ema 20": "EMA20",
    "ema_20": "EMA20",
    "sma50": "SMA50",
    "sma 50": "SMA50",
    "sma_50": "SMA50",
    "rsi": "RSI14",
    "rsi14": "RSI14",
    "rsi 14": "RSI14",
    "rsi_14": "RSI14",
    "macd": "MACD",
    "atr": "ATR14",
    "atr14": "ATR14",
    "atr 14": "ATR14",
    "atr_14": "ATR14",
}

# Instrument normalization mapping
INSTRUMENT_SYNONYMS: Dict[str, str] = {
    "reliance": "RELIANCE",
    "tcs": "TCS",
    "infy": "INFY",
    "infosys": "INFY",
    "hdfc": "HDFCBANK",
    "hdfcbank": "HDFCBANK",
    "hdfc bank": "HDFCBANK",
    "icici": "ICICIBANK",
    "icicibank": "ICICIBANK",
    "icici bank": "ICICIBANK",
    "sbin": "SBIN",
    "sbi": "SBIN",
    "itc": "ITC",
    "nifty": "NIFTY 50",
    "nifty50": "NIFTY 50",
    "nifty 50": "NIFTY 50",
    "nifty_50": "NIFTY 50",
    "banknifty": "BANK NIFTY",
    "bank nifty": "BANK NIFTY",
    "bank_nifty": "BANK NIFTY",
    "niftyit": "NIFTY IT",
    "nifty it": "NIFTY IT",
    "nifty_it": "NIFTY IT",
}

# Timeframe normalization mapping
TIMEFRAME_SYNONYMS: Dict[str, str] = {
    "5m": "5m",
    "5 min": "5m",
    "5min": "5m",
    "5minute": "5m",
    "15m": "15m",
    "15 min": "15m",
    "15min": "15m",
    "15minute": "15m",
    "30m": "30m",
    "30 min": "30m",
    "30min": "30m",
    "30minute": "30m",
    "1h": "1h",
    "60m": "1h",
    "60 min": "1h",
    "1 hour": "1h",
    "1hour": "1h",
    "1d": "1d",
    "daily": "1d",
    "1 day": "1d",
    "1day": "1d",
}

# Standard defaults from Section 3, Section 11, and Section 36
DEFAULT_TIMEFRAME: str = "15m"
DEFAULT_INITIAL_CAPITAL: float = 100000.0
DEFAULT_RISK_PER_TRADE: float = 0.02
DEFAULT_MAX_POSITION_EXPOSURE: float = 0.25
DEFAULT_MAX_DAILY_LOSS: float = 0.05
