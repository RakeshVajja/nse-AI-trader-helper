"""Central API v1 router combining sub-routers."""

from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.health import router as health_router
from app.api.v1.indicators import router as indicators_router
from app.api.v1.instruments import router as instruments_router
from app.api.v1.market_data import router as market_data_router
from app.api.v1.simulations import router as simulations_router

api_v1_router = APIRouter()

# Register sub-routers
api_v1_router.include_router(health_router)
api_v1_router.include_router(instruments_router)
api_v1_router.include_router(market_data_router)
api_v1_router.include_router(indicators_router)
api_v1_router.include_router(simulations_router)
api_v1_router.include_router(agents_router)
