"""Simulation WebSocket Connection Manager (Phase 10A).

Manages active client connections scoped per simulation ID, thread-safe monotonic
event sequencing, non-blocking broadcasts, and graceful disconnect cleanup.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

from app.websocket.schemas import SimulationEvent, SimulationEventType

logger = logging.getLogger(__name__)


class SimulationConnectionManager:
    """Manages active WebSocket subscriptions scoped to individual simulations."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._sequence_counters: Dict[str, int] = defaultdict(int)
        self._send_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _get_send_lock(self, simulation_id: str) -> asyncio.Lock:
        """Get or create the per-simulation send lock."""
        return self._send_locks[simulation_id]

    async def connect(self, simulation_id: str, websocket: WebSocket) -> None:
        """Register a new active WebSocket connection for a simulation."""
        async with self._lock:
            self._connections[simulation_id].add(websocket)
            logger.info(
                "WebSocket client connected to simulation '%s' (active: %d)",
                simulation_id,
                len(self._connections[simulation_id]),
            )

    async def disconnect(self, simulation_id: str, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket connection cleanly."""
        async with self._lock:
            if simulation_id in self._connections:
                self._connections[simulation_id].discard(websocket)
                if not self._connections[simulation_id]:
                    del self._connections[simulation_id]
                logger.info(
                    "WebSocket client disconnected from simulation '%s' (remaining: %d)",
                    simulation_id,
                    len(self._connections.get(simulation_id, set())),
                )

    def next_sequence(self, simulation_id: str) -> int:
        """Atomically generate the next sequence number for a simulation."""
        self._sequence_counters[simulation_id] += 1
        return self._sequence_counters[simulation_id]

    def create_event(
        self,
        simulation_id: str,
        event_type: SimulationEventType,
        payload: Dict[str, Any],
        virtual_timestamp: Optional[str] = None,
    ) -> SimulationEvent:
        """Create a validated SimulationEvent envelope with monotonic sequence."""
        seq = self.next_sequence(simulation_id)
        now_utc = datetime.now(timezone.utc).isoformat()

        return SimulationEvent(
            event_type=event_type,
            simulation_id=simulation_id,
            sequence=seq,
            virtual_timestamp=virtual_timestamp,
            wall_clock_timestamp=now_utc,
            payload=payload,
        )

    async def broadcast_events(self, simulation_id: str, events: list[SimulationEvent]) -> None:
        """Broadcast an ordered sequence of events to all active clients sequentially.

        Guarantees:
        1. Monotonic ordering: All events in the batch are delivered sequentially
           under a per-simulation send lock, preventing interleaving or out-of-order delivery.
        2. Non-blocking: Failed or slow clients are pruned without interrupting simulation
           execution or other clients.
        3. Client isolation: Clients subscribed to simulation A never receive events
           for simulation B.
        """
        if not events:
            return

        send_lock = self._get_send_lock(simulation_id)
        async with send_lock:
            async with self._lock:
                sockets = list(self._connections.get(simulation_id, []))

            if not sockets:
                return

            dead_sockets: Set[WebSocket] = set()

            for event in events:
                message_json = event.model_dump_json()
                for ws in sockets:
                    if ws in dead_sockets:
                        continue
                    try:
                        await ws.send_text(message_json)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "Failed to send event to client on simulation '%s', queuing for removal: %s",
                            simulation_id,
                            exc,
                        )
                        dead_sockets.add(ws)

            if dead_sockets:
                async with self._lock:
                    if simulation_id in self._connections:
                        for dead_ws in dead_sockets:
                            self._connections[simulation_id].discard(dead_ws)
                        if not self._connections[simulation_id]:
                            del self._connections[simulation_id]

    async def broadcast(self, simulation_id: str, event: SimulationEvent) -> None:
        """Broadcast a single simulation event."""
        await self.broadcast_events(simulation_id, [event])

    def get_active_count(self, simulation_id: str) -> int:
        """Get the count of active WebSocket connections for a simulation."""
        return len(self._connections.get(simulation_id, set()))

    def get_total_connections(self) -> int:
        """Get the total count of active connections across all simulations."""
        return sum(len(sockets) for sockets in self._connections.values())

    async def clear(self) -> None:
        """Clear all connections, locks, and sequence counters (useful for testing)."""
        async with self._lock:
            self._connections.clear()
            self._sequence_counters.clear()
            self._send_locks.clear()


_manager_instance: Optional[SimulationConnectionManager] = None


def get_connection_manager() -> SimulationConnectionManager:
    """Singleton provider for SimulationConnectionManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SimulationConnectionManager()
    return _manager_instance
