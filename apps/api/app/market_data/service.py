"""Market Data Service with on-demand PostgreSQL caching and missing range detection."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import models
from app.market_data.base import MarketDataProvider
from app.market_data.openchart_adapter import NSEPublicProvider
from app.market_data.schema import (
    CandleData,
    HistoricalDataRequest,
    HistoricalDataResponse,
)
from app.market_data.validator import validate_and_clean_candles

logger = logging.getLogger(__name__)

DEFAULT_SUPPORTED_INSTRUMENTS = [
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "instrument_type": "EQUITY"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Ltd", "instrument_type": "EQUITY"},
    {"symbol": "INFY", "name": "Infosys Ltd", "instrument_type": "EQUITY"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "instrument_type": "EQUITY"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "instrument_type": "EQUITY"},
    {"symbol": "SBIN", "name": "State Bank of India", "instrument_type": "EQUITY"},
    {"symbol": "ITC", "name": "ITC Ltd", "instrument_type": "EQUITY"},
    {"symbol": "NIFTY 50", "name": "Nifty 50 Index", "instrument_type": "INDEX"},
    {"symbol": "BANK NIFTY", "name": "Nifty Bank Index", "instrument_type": "INDEX"},
    {"symbol": "NIFTY IT", "name": "Nifty IT Index", "instrument_type": "INDEX"},
]


def calculate_missing_ranges(
    existing_range: Optional[models.MarketDataRange],
    req_start: datetime,
    req_end: datetime,
) -> List[Tuple[datetime, datetime]]:
    """Determine sub-intervals of [req_start, req_end] not covered by existing_range.

    Ensures that contiguous cache boundaries are maintained so non-contiguous
    requests cannot create un-fetched intermediate gaps.
    """
    # Ensure UTC timezone
    if req_start.tzinfo is None:
        req_start = req_start.replace(tzinfo=timezone.utc)
    if req_end.tzinfo is None:
        req_end = req_end.replace(tzinfo=timezone.utc)

    if req_start > req_end:
        return []

    if existing_range is None:
        return [(req_start, req_end)]

    earliest = existing_range.earliest_timestamp
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)

    latest = existing_range.latest_timestamp
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)

    missing: List[Tuple[datetime, datetime]] = []

    # Left-hand missing window: [req_start, earliest)
    # If req_end < earliest, fetch [req_start, earliest - 1s] to bridge to existing cache
    if req_start < earliest:
        left_end = earliest - timedelta(seconds=1)
        missing.append((req_start, left_end))

    # Right-hand missing window: (latest, req_end]
    # If req_start > latest, fetch [latest + 1s, req_end] to bridge from existing cache
    if req_end > latest:
        right_start = latest + timedelta(seconds=1)
        missing.append((right_start, req_end))

    return missing


class MarketDataService:
    """Coordinates on-demand market data retrieval, validation, and PostgreSQL persistence."""

    def __init__(self, provider: Optional[MarketDataProvider] = None) -> None:
        self.provider = provider if provider is not None else NSEPublicProvider()

    async def get_or_create_instrument(
        self,
        db: AsyncSession,
        symbol: str,
        name: Optional[str] = None,
        instrument_type: str = "EQUITY",
    ) -> models.Instrument:
        """Fetch instrument by symbol or create if it does not exist."""
        clean_symbol = symbol.strip().upper()
        stmt = select(models.Instrument).where(models.Instrument.symbol == clean_symbol)
        result = await db.execute(stmt)
        inst = result.scalar_one_or_none()

        if inst is None:
            inst_type = (
                models.InstrumentType.INDEX
                if instrument_type.upper() in ("INDEX", "IDX") or clean_symbol.startswith("NIFTY")
                else models.InstrumentType.EQUITY
            )
            inst = models.Instrument(
                symbol=clean_symbol,
                name=name or clean_symbol,
                exchange="NSE",
                instrument_type=inst_type,
                is_active=True,
            )
            db.add(inst)
            await db.flush()
            await db.refresh(inst)

        return inst

    async def seed_default_instruments(self, db: AsyncSession) -> List[models.Instrument]:
        """Seed default supported NSE equities and indices into the database."""
        seeded: List[models.Instrument] = []
        for item in DEFAULT_SUPPORTED_INSTRUMENTS:
            inst = await self.get_or_create_instrument(
                db=db,
                symbol=item["symbol"],
                name=item["name"],
                instrument_type=item["instrument_type"],
            )
            seeded.append(inst)
        await db.flush()
        return seeded

    async def list_instruments(
        self,
        db: AsyncSession,
        query: Optional[str] = None,
        instrument_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[models.Instrument], int]:
        """List instruments with optional search and pagination. Auto-seeds defaults if DB is empty."""
        # Check total count in DB
        total_in_db = (await db.execute(select(func.count(models.Instrument.id)))).scalar() or 0
        if total_in_db == 0:
            await self.seed_default_instruments(db)

        stmt = select(models.Instrument)
        count_stmt = select(func.count(models.Instrument.id))

        filters = []
        if query:
            clean_q = f"%{query.strip().upper()}%"
            filters.append(
                or_(
                    models.Instrument.symbol.ilike(clean_q),
                    models.Instrument.name.ilike(clean_q),
                )
            )

        if instrument_type:
            clean_type = instrument_type.strip().upper()
            if clean_type in ("EQUITY", "INDEX"):
                filters.append(
                    models.Instrument.instrument_type == models.InstrumentType(clean_type)
                )

        if filters:
            stmt = stmt.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total_res = (await db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(models.Instrument.symbol.asc()).limit(limit).offset(offset)
        result = await db.execute(stmt)
        instruments = list(result.scalars().all())

        return instruments, total_res

    async def get_instrument_by_symbol(
        self, db: AsyncSession, symbol: str
    ) -> Optional[models.Instrument]:
        """Look up an instrument by uppercase symbol."""
        clean_symbol = symbol.strip().upper()
        stmt = select(models.Instrument).where(models.Instrument.symbol == clean_symbol)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_candle(
        self, db: AsyncSession, symbol: str, timeframe: str = "15m"
    ) -> Optional[CandleData]:
        """Fetch the most recent single candle for a symbol, persisting if retrieved from provider."""
        clean_symbol = symbol.strip().upper()
        inst = await self.get_or_create_instrument(db, clean_symbol)

        try:
            latest = await self.provider.get_latest_data(clean_symbol, timeframe=timeframe)
            if latest:
                await self.persist_candles(
                    db=db,
                    instrument_id=inst.id,
                    timeframe=timeframe,
                    candles=[latest],
                )
                return latest

        except Exception as err:  # noqa: BLE001
            logger.warning(
                "Error fetching latest candle for %s from provider: %s", clean_symbol, err
            )

        # Fallback to latest candle stored in DB
        stmt = (
            select(models.Candle)
            .where(
                models.Candle.instrument_id == inst.id,
                models.Candle.timeframe == timeframe,
            )
            .order_by(models.Candle.timestamp.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        candle = res.scalar_one_or_none()
        if candle:
            ts = (
                candle.timestamp.replace(tzinfo=timezone.utc)
                if candle.timestamp.tzinfo is None
                else candle.timestamp
            )
            return CandleData(
                timestamp=ts,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )

        return None

    async def get_market_data_range(
        self, db: AsyncSession, instrument_id: int, timeframe: str
    ) -> Optional[models.MarketDataRange]:
        """Fetch cached data range tracking metadata for instrument and timeframe."""
        stmt = select(models.MarketDataRange).where(
            models.MarketDataRange.instrument_id == instrument_id,
            models.MarketDataRange.timeframe == timeframe,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def persist_candles(
        self,
        db: AsyncSession,
        instrument_id: int,
        timeframe: str,
        candles: Sequence[CandleData],
    ) -> int:
        """Persist new validated candles and update MarketDataRange tracking."""
        if not candles:
            return 0

        cleaned_candles = validate_and_clean_candles(candles, deduplicate=True)
        if not cleaned_candles:
            return 0

        # Query existing timestamps in this window to avoid duplicates
        min_ts = cleaned_candles[0].timestamp
        max_ts = cleaned_candles[-1].timestamp

        existing_stmt = select(models.Candle.timestamp).where(
            models.Candle.instrument_id == instrument_id,
            models.Candle.timeframe == timeframe,
            models.Candle.timestamp >= min_ts,
            models.Candle.timestamp <= max_ts,
        )
        existing_res = await db.execute(existing_stmt)
        existing_timestamps = {
            t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
            for t in existing_res.scalars().all()
        }

        new_candle_models: List[models.Candle] = []
        for c in cleaned_candles:
            ts = (
                c.timestamp.replace(tzinfo=timezone.utc)
                if c.timestamp.tzinfo is None
                else c.timestamp
            )
            if ts not in existing_timestamps:
                new_candle_models.append(
                    models.Candle(
                        instrument_id=instrument_id,
                        timeframe=timeframe,
                        timestamp=ts,
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        volume=c.volume,
                    )
                )

        if new_candle_models:
            db.add_all(new_candle_models)
            await db.flush()

        # Update or create MarketDataRange metadata
        count_stmt = select(
            func.count(models.Candle.id),
            func.min(models.Candle.timestamp),
            func.max(models.Candle.timestamp),
        ).where(
            models.Candle.instrument_id == instrument_id,
            models.Candle.timeframe == timeframe,
        )
        agg_res = (await db.execute(count_stmt)).one()
        total_count, earliest_ts, latest_ts = agg_res

        if (
            earliest_ts is not None
            and isinstance(earliest_ts, datetime)
            and earliest_ts.tzinfo is None
        ):
            earliest_ts = earliest_ts.replace(tzinfo=timezone.utc)
        if latest_ts is not None and isinstance(latest_ts, datetime) and latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)

        data_range = await self.get_market_data_range(db, instrument_id, timeframe)
        now_utc = datetime.now(timezone.utc)

        if data_range is None and earliest_ts and latest_ts:
            data_range = models.MarketDataRange(
                instrument_id=instrument_id,
                timeframe=timeframe,
                earliest_timestamp=earliest_ts,
                latest_timestamp=latest_ts,
                total_candles=total_count,
                last_updated=now_utc,
            )
            db.add(data_range)
        elif data_range is not None and earliest_ts and latest_ts:
            data_range.earliest_timestamp = earliest_ts
            data_range.latest_timestamp = latest_ts
            data_range.total_candles = total_count
            data_range.last_updated = now_utc

        await db.flush()
        return len(new_candle_models)

    async def get_historical_candles(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str = "15m",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        instrument_type: str = "EQUITY",
    ) -> HistoricalDataResponse:
        """Fetch historical candles, querying PostgreSQL cache first and fetching missing ranges on demand."""
        now = datetime.now(timezone.utc)
        req_end = end_date or now
        if start_date is None:
            raise ValueError("start_date is required for historical candle queries")
        req_start = start_date

        if req_start.tzinfo is None:
            req_start = req_start.replace(tzinfo=timezone.utc)
        if req_end.tzinfo is None:
            req_end = req_end.replace(tzinfo=timezone.utc)

        inst = await self.get_or_create_instrument(
            db=db,
            symbol=symbol,
            instrument_type=instrument_type,
        )

        # Check existing range
        existing_range = await self.get_market_data_range(db, inst.id, timeframe)
        missing_ranges = calculate_missing_ranges(existing_range, req_start, req_end)

        # Fetch and persist missing ranges from provider
        for m_start, m_end in missing_ranges:
            try:
                fetch_req = HistoricalDataRequest(
                    symbol=inst.symbol,
                    timeframe=timeframe,
                    start_date=m_start,
                    end_date=m_end,
                    instrument_type=inst.instrument_type.value,
                )
                provider_resp = await self.provider.get_historical_data(fetch_req)
                if provider_resp.candles:
                    await self.persist_candles(
                        db=db,
                        instrument_id=inst.id,
                        timeframe=timeframe,
                        candles=provider_resp.candles,
                    )
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    "Error fetching missing range [%s, %s] for %s: %s",
                    m_start,
                    m_end,
                    inst.symbol,
                    err,
                )

        # Query all candles from PostgreSQL cache in requested window
        stmt = (
            select(models.Candle)
            .where(
                models.Candle.instrument_id == inst.id,
                models.Candle.timeframe == timeframe,
                models.Candle.timestamp >= req_start,
                models.Candle.timestamp <= req_end,
            )
            .order_by(models.Candle.timestamp.asc())
        )
        res = await db.execute(stmt)
        db_candles = list(res.scalars().all())

        # Fallback safety: If DB returned 0 candles for a window spanning potential trading days
        # (e.g. legacy gap in DB), perform a direct on-demand fetch to guarantee no false misses.
        if not db_candles and (req_end - req_start).total_seconds() >= 86400 * 3:
            try:
                fallback_req = HistoricalDataRequest(
                    symbol=inst.symbol,
                    timeframe=timeframe,
                    start_date=req_start,
                    end_date=req_end,
                    instrument_type=inst.instrument_type.value,
                )
                fallback_resp = await self.provider.get_historical_data(fallback_req)
                if fallback_resp.candles:
                    await self.persist_candles(
                        db=db,
                        instrument_id=inst.id,
                        timeframe=timeframe,
                        candles=fallback_resp.candles,
                    )
                    res = await db.execute(stmt)
                    db_candles = list(res.scalars().all())
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    "Fallback fetch failed for %s [%s, %s]: %s",
                    inst.symbol,
                    req_start,
                    req_end,
                    err,
                )

        candle_models: List[CandleData] = [
            CandleData(
                timestamp=c.timestamp.replace(tzinfo=timezone.utc)
                if c.timestamp.tzinfo is None
                else c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in db_candles
        ]

        return HistoricalDataResponse(
            symbol=inst.symbol,
            timeframe=timeframe,
            candles=candle_models,
            count=len(candle_models),
        )


_market_data_service_instance: Optional[MarketDataService] = None


def get_market_data_service() -> MarketDataService:
    """Dependency provider returning singleton MarketDataService instance."""
    global _market_data_service_instance
    if _market_data_service_instance is None:
        _market_data_service_instance = MarketDataService()
    return _market_data_service_instance
