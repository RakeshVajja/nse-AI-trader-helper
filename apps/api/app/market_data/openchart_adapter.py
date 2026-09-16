"""OpenChart / NSE Public Market Data Provider Adapter."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Dict, List, Optional, Set

import pandas as pd
from openchart import NSEData

from app.market_data.base import MarketDataProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataRequest,
    HistoricalDataResponse,
    InstrumentInfo,
)
from app.market_data.validator import validate_and_clean_candles

logger = logging.getLogger(__name__)


class NSEPublicProvider(MarketDataProvider):
    """MarketDataProvider implementation isolating OpenChart / NSE public charting endpoints."""

    SUPPORTED_TIMEFRAMES: ClassVar[Set[str]] = {
        "1m",
        "3m",
        "5m",
        "10m",
        "15m",
        "30m",
        "1h",
        "1d",
        "1w",
        "1M",
    }

    # Common index symbol alias mapping
    INDEX_ALIAS_MAP: ClassVar[Dict[str, str]] = {
        "NIFTY": "NIFTY 50",
        "NIFTY50": "NIFTY 50",
        "BANKNIFTY": "NIFTY BANK",
        "NIFTYBANK": "NIFTY BANK",
        "BANK NIFTY": "NIFTY BANK",
        "NIFTYIT": "NIFTY IT",
        "NIFTY IT": "NIFTY IT",
        "MIDCPNIFTY": "NIFTY MIDCAP 50",
        "FINNIFTY": "NIFTY FINANCIAL SERVICES",
    }

    def __init__(self, nse_client: Optional[Any] = None) -> None:
        self._client = nse_client if nse_client is not None else NSEData()

    def _resolve_symbol_and_segment(
        self, raw_symbol: str, instrument_type: Optional[str] = None
    ) -> tuple[str, str]:
        """Normalize symbol string and determine appropriate market segment (EQ vs IDX)."""
        clean_symbol = raw_symbol.strip().upper()

        # Check index alias map
        if clean_symbol in self.INDEX_ALIAS_MAP:
            return self.INDEX_ALIAS_MAP[clean_symbol], "IDX"

        if instrument_type and instrument_type.upper() in ("INDEX", "IDX"):
            return clean_symbol, "IDX"

        if clean_symbol.startswith("NIFTY") or clean_symbol == "INDIA VIX":
            return clean_symbol, "IDX"

        # Standard equity symbol
        return clean_symbol, "EQ"

    def _normalize_timeframe(self, timeframe: str) -> str:
        """Validate and return canonical timeframe identifier."""
        tf = timeframe.strip()
        if tf in self.SUPPORTED_TIMEFRAMES:
            return tf
        # Fallback aliases
        lower_tf = tf.lower()
        if lower_tf in ("d", "day", "daily", "1day"):
            return "1d"
        if lower_tf in ("w", "week", "weekly", "1week"):
            return "1w"
        if lower_tf in ("m", "month", "monthly", "1month"):
            return "1M"
        if lower_tf in ("15", "15min", "15mins"):
            return "15m"
        if lower_tf in ("5", "5min", "5mins"):
            return "5m"
        if lower_tf in ("1", "1min"):
            return "1m"
        if lower_tf in ("60", "60m", "60min", "1hour", "1hr"):
            return "1h"
        logger.warning("Unrecognized timeframe '%s', falling back to 15m", timeframe)
        return "15m"

    def _dataframe_to_candles(self, df: pd.DataFrame) -> List[CandleData]:
        """Convert OpenChart DataFrame to validated CandleData models."""
        if df is None or df.empty:
            return []

        candles: List[CandleData] = []
        df_reset = df.reset_index() if "Timestamp" not in df.columns else df

        for _, row in df_reset.iterrows():
            ts_val = row.get(
                "Timestamp", row.get("time", row.name if hasattr(row, "name") else None)
            )
            if isinstance(ts_val, pd.Timestamp):
                ts = ts_val.to_pydatetime()
            elif isinstance(ts_val, (int, float)):
                ts = datetime.fromtimestamp(
                    ts_val / 1000.0 if ts_val > 1e11 else ts_val, tz=timezone.utc
                )
            elif isinstance(ts_val, str):
                ts = datetime.fromisoformat(ts_val)
            else:
                continue

            # OpenChart's utils.py converts raw epoch ms and strips tzinfo with dt.tz_localize(None).
            # The resulting naive timestamps represent Indian Standard Time (IST, UTC+5:30) clock times
            # (e.g. 09:15 for market opening candle).
            # We localize naive timestamps to IST (+05:30) and convert to UTC for consistent storage.
            if ts.tzinfo is None:
                ist_tz = timezone(timedelta(hours=5, minutes=30))
                ts = ts.replace(tzinfo=ist_tz).astimezone(timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)

            open_val = float(row.get("Open", row.get("open", 0.0)))
            high_val = float(row.get("High", row.get("high", 0.0)))
            low_val = float(row.get("Low", row.get("low", 0.0)))
            close_val = float(row.get("Close", row.get("close", 0.0)))
            volume_val = float(row.get("Volume", row.get("volume", 0.0)))

            # Basic price plausibility check
            if open_val <= 0 and close_val <= 0 and high_val <= 0 and low_val <= 0:
                continue

            candle = CandleData(
                timestamp=ts,
                open=open_val,
                high=high_val,
                low=low_val,
                close=close_val,
                volume=max(volume_val, 0.0),
            )
            candles.append(candle)

        return validate_and_clean_candles(candles, deduplicate=True)

    async def get_historical_data(self, request: HistoricalDataRequest) -> HistoricalDataResponse:
        """Fetch and parse historical OHLCV data asynchronously with error isolation."""
        resolved_symbol, segment = self._resolve_symbol_and_segment(
            request.symbol, request.instrument_type
        )
        timeframe = self._normalize_timeframe(request.timeframe)

        def _fetch() -> pd.DataFrame:
            return self._client.historical(
                symbol=resolved_symbol,
                segment=segment,
                start=request.start_date,
                end=request.end_date,
                interval=timeframe,
            )

        try:
            df = await asyncio.to_thread(_fetch)
            candles = self._dataframe_to_candles(df)
        except (ValueError, KeyError, AttributeError, RuntimeError) as err:
            logger.warning("Failed to fetch historical data from OpenChart: %s", err)
            candles = []
        except Exception as err:  # noqa: BLE001
            logger.warning("Unexpected error fetching historical data: %s", err)
            candles = []

        return HistoricalDataResponse(
            symbol=resolved_symbol,
            timeframe=timeframe,
            candles=candles,
            count=len(candles),
        )

    # Lookback durations per timeframe for get_latest_data.
    # Intraday timeframes use a minimum of 4 days to cover weekends + possible
    # Friday-afternoon-to-Monday-morning gaps without needing a full holiday calendar.
    _LATEST_LOOKBACK: ClassVar[Dict[str, timedelta]] = {
        "1m": timedelta(days=4),
        "3m": timedelta(days=4),
        "5m": timedelta(days=4),
        "10m": timedelta(days=4),
        "15m": timedelta(days=4),
        "30m": timedelta(days=4),
        "1h": timedelta(days=4),
        "1d": timedelta(days=10),
        "1w": timedelta(days=60),
        "1M": timedelta(days=180),
    }

    async def get_latest_data(self, symbol: str, timeframe: str = "15m") -> Optional[CandleData]:
        """Fetch the most recent completed candle using a weekend-safe lookback window.

        Uses a conservative lookback (≥4 days for intraday) so the request always
        spans at least one full trading session, even when called on weekends or
        after NSE market close.
        """
        end = datetime.now(timezone.utc)
        lookback = self._LATEST_LOOKBACK.get(timeframe, timedelta(days=4))
        req = HistoricalDataRequest(
            symbol=symbol,
            timeframe=timeframe,
            start_date=end - lookback,
            end_date=end,
        )
        res = await self.get_historical_data(req)
        return res.candles[-1] if res.candles else None

    async def search_instruments(self, query: str) -> List[InstrumentInfo]:
        """Search instruments using OpenChart with isolated segment lookup."""

        def _search(seg: str) -> pd.DataFrame:
            return self._client.search(query, segment=seg)

        try:
            df = await asyncio.to_thread(_search, "EQ")
            if df is None or df.empty:
                # Try index search if equity returned empty
                df = await asyncio.to_thread(_search, "IDX")
            if df is None or df.empty:
                return []

            results: List[InstrumentInfo] = []
            for _, row in df.iterrows():
                results.append(
                    InstrumentInfo(
                        symbol=str(row.get("symbol", "")),
                        name=str(row.get("description", row.get("symbol", ""))),
                        exchange=str(row.get("exchange", "NSE")),
                        instrument_type=str(row.get("type", "EQUITY")).upper(),
                    )
                )
            return results
        except (ValueError, KeyError, AttributeError, RuntimeError) as err:
            logger.warning("Failed to search instruments via OpenChart: %s", err)
            return []
        except Exception as err:  # noqa: BLE001
            logger.warning("Unexpected error searching instruments: %s", err)
            return []
