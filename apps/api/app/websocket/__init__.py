"""Phase 10A: WebSocket real-time event streaming server module."""

from app.websocket.manager import (
    SimulationConnectionManager,
    get_connection_manager,
)
from app.websocket.router import router as websocket_router
from app.websocket.schemas import (
    SimulationEvent,
    SimulationEventType,
)

__all__ = [
    "SimulationConnectionManager",
    "SimulationEvent",
    "SimulationEventType",
    "get_connection_manager",
    "websocket_router",
]
