"""FastAPI Main Application Entrypoint."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifespan management."""
    settings = get_settings()
    logger.info(
        "starting_application",
        app_name=settings.PROJECT_NAME,
        environment=settings.ENVIRONMENT,
        debug=settings.DEBUG,
    )
    yield
    logger.info("stopping_application")


def create_app() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()

    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="Authoritative Backend & Simulation Core for NSE AI Trading Platform",
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS configuration
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include central API v1 routes
    application.include_router(api_v1_router, prefix=settings.API_V1_STR)

    # Include WebSocket real-time routes (Phase 10A)
    from app.websocket import websocket_router

    application.include_router(websocket_router)

    return application


app = create_app()


@app.get("/")
async def root_redirect():
    """Root metadata response."""
    settings = get_settings()
    return {
        "name": settings.PROJECT_NAME,
        "version": "0.1.0",
        "docs": "/docs" if settings.DEBUG else "disabled",
        "status": "online",
    }
