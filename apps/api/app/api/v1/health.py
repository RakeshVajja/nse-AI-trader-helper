"""Health check endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.database.session import check_db_connection

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: str
    environment: str
    version: str


@router.get("", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    """Return application and database health status."""
    settings = get_settings()
    db_ok = await check_db_connection()
    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        database="connected" if db_ok else "disconnected",
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment=settings.ENVIRONMENT,
        version="0.1.0",
    )
