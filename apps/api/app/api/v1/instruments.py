"""Instruments API endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.market_data.schema import InstrumentListResponse, InstrumentResponse
from app.market_data.service import MarketDataService, get_market_data_service

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get(
    "",
    response_model=InstrumentListResponse,
    summary="List or search instruments",
    description="Retrieve supported NSE instruments with optional search and pagination.",
)
async def list_instruments(
    query: Optional[str] = Query(None, description="Search query matching symbol or company name"),
    instrument_type: Optional[str] = Query(
        None, description="Filter by instrument type ('EQUITY' or 'INDEX')"
    ),
    limit: int = Query(50, ge=1, le=100, description="Number of results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db_session),
    service: MarketDataService = Depends(get_market_data_service),
) -> InstrumentListResponse:
    """List or search NSE instruments."""
    instruments, total = await service.list_instruments(
        db=db,
        query=query,
        instrument_type=instrument_type,
        limit=limit,
        offset=offset,
    )
    return InstrumentListResponse(
        instruments=[InstrumentResponse.model_validate(i) for i in instruments],
        total=total,
        count=len(instruments),
    )


@router.post(
    "/seed",
    response_model=InstrumentListResponse,
    summary="Seed default supported instruments",
    description="Explicitly seed the default supported NSE equities and indices into the database.",
)
async def seed_instruments(
    db: AsyncSession = Depends(get_db_session),
    service: MarketDataService = Depends(get_market_data_service),
) -> InstrumentListResponse:
    """Seed default supported NSE equities and indices."""
    seeded = await service.seed_default_instruments(db)
    return InstrumentListResponse(
        instruments=[InstrumentResponse.model_validate(i) for i in seeded],
        total=len(seeded),
        count=len(seeded),
    )


@router.get(
    "/{symbol}",
    response_model=InstrumentResponse,
    summary="Get instrument details",
    description="Retrieve metadata for a specific NSE instrument by its symbol.",
)
async def get_instrument(
    symbol: str,
    db: AsyncSession = Depends(get_db_session),
    service: MarketDataService = Depends(get_market_data_service),
) -> InstrumentResponse:
    """Get single instrument metadata by symbol."""
    inst = await service.get_instrument_by_symbol(db, symbol)
    if inst is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instrument '{symbol.strip().upper()}' not found",
        )
    return InstrumentResponse.model_validate(inst)
