"""FastAPI WebSocket router for simulation real-time event streaming (Phase 10A).

Exposes /ws/simulations/{simulation_id} per Section 51 of PROJECT_SPECIFICATION.md.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import models
from app.database.session import async_session_factory
from app.trading.simulation.service import SimulationService, get_simulation_service
from app.websocket.manager import SimulationConnectionManager, get_connection_manager
from app.websocket.schemas import SimulationEventType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


async def _resolve_initial_state(
    simulation_id: str,
    service: SimulationService,
) -> Optional[Dict[str, Any]]:
    """Resolve initial snapshot for a simulation from active session or PostgreSQL.

    Does not hold a persistent database connection.
    """
    # 1. Check in-memory active session
    async with service._lock:
        session = service._sessions.get(simulation_id)

    if session is not None:
        clock_status = session.clock.get_status()
        port_state = session.portfolio.get_state()
        cur_time = clock_status.current_time.isoformat() if clock_status.current_time else None

        return {
            "simulation_id": simulation_id,
            "status": clock_status.state.value,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "step_index": clock_status.step_index,
            "total_candles": clock_status.total_candles,
            "progress_pct": clock_status.progress_pct,
            "current_time": cur_time,
            "portfolio": {
                "cash": float(port_state.cash),
                "portfolio_value": float(port_state.total_portfolio_value),
                "gross_pnl": float(port_state.gross_pnl),
                "net_pnl": float(port_state.net_pnl),
                "total_return_pct": float(port_state.total_return_pct),
                "exposure_pct": float(port_state.exposure_pct),
                "open_positions_count": port_state.open_positions_count,
            },
            "positions": [
                {
                    "symbol": pos.symbol,
                    "quantity": pos.quantity,
                    "average_entry_price": float(pos.average_entry_price),
                    "current_price": float(pos.current_price),
                    "unrealized_pnl": float(pos.unrealized_gross_pnl),
                    "stop_loss": float(pos.stop_loss) if pos.stop_loss is not None else None,
                    "take_profit": float(pos.take_profit) if pos.take_profit is not None else None,
                    "is_open": pos.is_open,
                }
                for pos in port_state.positions.values()
            ],
        }

    # 2. Check PostgreSQL in a short-lived session
    session_maker = getattr(service, "session_factory", None) or async_session_factory
    async with session_maker() as db:
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == simulation_id)
        res = await db.execute(stmt)
        sim_run = res.scalar_one_or_none()
        if sim_run is None:
            return None

        inst_stmt = select(models.Instrument.symbol).where(
            models.Instrument.id == sim_run.instrument_id
        )
        inst_res = await db.execute(inst_stmt)
        inst_symbol = inst_res.scalar_one_or_none() or "UNKNOWN"

        metrics = sim_run.metrics or {}
        step_idx = metrics.get("step_index", 0)
        tot_candles = metrics.get("total_candles", 0)
        prog = metrics.get("progress_pct", 0.0)
        cur_time_str = metrics.get("current_time")

        return {
            "simulation_id": simulation_id,
            "status": sim_run.status.value,
            "symbol": inst_symbol,
            "timeframe": sim_run.timeframe,
            "step_index": step_idx,
            "total_candles": tot_candles,
            "progress_pct": prog,
            "current_time": cur_time_str,
            "portfolio": {
                "cash": float(sim_run.final_portfolio_value or sim_run.initial_capital or 0.0),
                "portfolio_value": float(
                    sim_run.final_portfolio_value or sim_run.initial_capital or 0.0
                ),
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "total_return_pct": float(sim_run.total_return_pct or 0.0),
                "exposure_pct": 0.0,
                "open_positions_count": 0,
            },
            "positions": [],
        }


@router.websocket("/simulations/{simulation_id}")
async def simulation_websocket_endpoint(
    websocket: WebSocket,
    simulation_id: str,
    service: SimulationService = Depends(get_simulation_service),
    manager: SimulationConnectionManager = Depends(get_connection_manager),
) -> None:
    """FastAPI WebSocket endpoint for streaming simulation events."""

    # Verify simulation existence and resolve initial state
    initial_state = await _resolve_initial_state(simulation_id, service)
    if initial_state is None:
        await websocket.accept()
        err_event = manager.create_event(
            simulation_id=simulation_id,
            event_type=SimulationEventType.ERROR,
            payload={
                "code": "SIMULATION_NOT_FOUND",
                "message": f"Simulation with ID '{simulation_id}' not found.",
            },
        )
        await websocket.send_text(err_event.model_dump_json())
        await websocket.close(code=4404, reason="Simulation not found")
        return

    # Accept connection
    await websocket.accept()

    try:
        # 1. Emit initial state snapshot directly to this client FIRST.
        # This guarantees initial_state arrives before any live simulation events.
        init_event = manager.create_event(
            simulation_id=simulation_id,
            event_type=SimulationEventType.INITIAL_STATE,
            payload=initial_state,
            virtual_timestamp=initial_state.get("current_time"),
        )
        await websocket.send_text(init_event.model_dump_json())

        # 2. Register with connection manager for live broadcasts only after snapshot is delivered
        await manager.connect(simulation_id, websocket)

        # Keep listening for client heartbeats/pings
        while True:
            text_data = await websocket.receive_text()
            try:
                msg = json.loads(text_data)
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    pong_resp = {
                        "type": "pong",
                        "simulation_id": simulation_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    await websocket.send_text(json.dumps(pong_resp))
            except Exception:  # noqa: BLE001, S110
                # Discard malformed client messages safely
                pass

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected: %s", simulation_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Unexpected error in WebSocket connection for simulation '%s': %s",
            simulation_id,
            exc,
        )
    finally:
        await manager.disconnect(simulation_id, websocket)
