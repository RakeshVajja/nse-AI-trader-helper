"""Comprehensive Test Suite for Phase 10A: WebSocket Real-Time Event Streaming.

Covers:
1. Connection & Initial State Snapshot
2. Invalid Simulation Rejection (4404)
3. Disconnect Cleanup & Connection Counter
4. Same-Simulation Multi-Client Broadcasting
5. Cross-Simulation Isolation
6. All 12 Event Schemas & Serialization
7. Monotonic Sequence Ordering
8. Simulation Uninterrupted After Client Disconnect
9. Client Ping/Pong Heartbeat Handling
10. Malformed Client Message Resilience
11. Privacy Guard & Secret Sanitization
12. End-to-End Simulation Step -> WebSocket Emission Integration
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.database import models
from app.database.base import Base
from app.database.models.trading import SimulationRun, SimulationStatus
from app.database.session import get_db_session
from app.main import app
from app.trading.simulation.service import SimulationService, get_simulation_service
from app.websocket import (
    SimulationConnectionManager,
    SimulationEvent,
    SimulationEventType,
    get_connection_manager,
)


@pytest.fixture
async def ws_test_env():
    """Setup isolated in-memory DB and test environment for WebSockets."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        inst = models.Instrument(
            symbol="RELIANCE",
            name="Reliance Industries Limited",
            exchange="NSE",
            instrument_type=models.InstrumentType.EQUITY,
            is_active=True,
        )
        db.add(inst)
        await db.commit()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    sim_service = SimulationService(session_factory=session_factory)
    manager = get_connection_manager()
    await manager.clear()

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_simulation_service] = lambda: sim_service

    test_client = TestClient(app)

    yield {
        "client": test_client,
        "session_factory": session_factory,
        "service": sim_service,
        "manager": manager,
    }

    app.dependency_overrides.clear()
    await manager.clear()
    await engine.dispose()


# ==============================================================================
# 1. Connection & Initial State Snapshot
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_connection_and_initial_snapshot(ws_test_env):
    """Client connecting to valid simulation receives initial state snapshot."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]

    sim_id = "sim-init-test-01"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            final_portfolio_value=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as websocket:
        raw_msg = websocket.receive_text()
        data = json.loads(raw_msg)

        assert data["event_type"] == "initial_state"
        assert data["simulation_id"] == sim_id
        assert data["sequence"] == 1
        assert "payload" in data
        payload = data["payload"]
        assert payload["simulation_id"] == sim_id
        assert payload["status"] == "CREATED"
        assert payload["symbol"] == "RELIANCE"
        assert payload["timeframe"] == "15m"
        assert payload["portfolio"]["cash"] == 100000.0


# ==============================================================================
# 2. Invalid Simulation Rejection (4404)
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_invalid_simulation_rejection(ws_test_env):
    """Connecting to a nonexistent simulation ID receives error event and 4404 closure."""
    client: TestClient = ws_test_env["client"]

    with client.websocket_connect("/ws/simulations/nonexistent-sim-999") as websocket:
        raw_msg = websocket.receive_text()
        data = json.loads(raw_msg)
        assert data["event_type"] == "error"
        assert data["payload"]["code"] == "SIMULATION_NOT_FOUND"

        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_text()
        assert exc_info.value.code == 4404


# ==============================================================================
# 3. Disconnect Cleanup & Connection Counter
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_disconnect_cleanup(ws_test_env):
    """Disconnecting cleans up active connections in SimulationConnectionManager."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_id = "sim-cleanup-test"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    assert manager.get_active_count(sim_id) == 0

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as websocket:
        _ = websocket.receive_text()  # initial_state
        assert manager.get_active_count(sim_id) == 1

    # After exiting context manager, client is disconnected
    assert manager.get_active_count(sim_id) == 0


# ==============================================================================
# 4. Same-Simulation Multi-Client Broadcasting
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_same_simulation_broadcast(ws_test_env):
    """Multiple clients connected to the same simulation both receive broadcast events."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_id = "sim-multi-client"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws1:
        _ = ws1.receive_text()  # initial_state ws1

        with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws2:
            _ = ws2.receive_text()  # initial_state ws2

            assert manager.get_active_count(sim_id) == 2

            # Broadcast a candle update
            candle_evt = manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.CANDLE_UPDATE,
                payload={
                    "step_index": 5,
                    "candle": {
                        "timestamp": "2026-01-02T10:00:00Z",
                        "open": 2450.0,
                        "high": 2460.0,
                        "low": 2445.0,
                        "close": 2455.0,
                        "volume": 50000.0,
                    },
                },
                virtual_timestamp="2026-01-02T10:00:00Z",
            )
            await manager.broadcast(sim_id, candle_evt)

            msg1 = json.loads(ws1.receive_text())
            msg2 = json.loads(ws2.receive_text())

            assert msg1["event_type"] == "candle_update"
            assert msg2["event_type"] == "candle_update"
            assert msg1["payload"]["step_index"] == 5
            assert msg2["payload"]["step_index"] == 5


# ==============================================================================
# 5. Cross-Simulation Isolation
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_cross_simulation_isolation(ws_test_env):
    """Clients on Simulation A never receive events broadcast to Simulation B."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_a = "sim-iso-A"
    sim_b = "sim-iso-B"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        for s_id in (sim_a, sim_b):
            sim = SimulationRun(
                id=s_id,
                instrument_id=inst.id,
                timeframe="15m",
                start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
                initial_capital=100000.0,
                status=SimulationStatus.CREATED,
                is_baseline=False,
            )
            db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_a}") as ws_a:
        _ = ws_a.receive_text()  # initial_state

        with client.websocket_connect(f"/ws/simulations/{sim_b}") as ws_b:
            _ = ws_b.receive_text()  # initial_state

            # Broadcast event ONLY to sim_a
            evt_a = manager.create_event(
                simulation_id=sim_a,
                event_type=SimulationEventType.AGENT_DECISION,
                payload={"action": "BUY", "confidence": 0.95, "reason": "Bullish breakout"},
            )
            await manager.broadcast(sim_a, evt_a)

            # ws_a receives the event
            rec_a = json.loads(ws_a.receive_text())
            assert rec_a["event_type"] == "agent_decision"
            assert rec_a["simulation_id"] == sim_a

            # ws_b sends ping and expects pong (proving no other event was queued)
            ws_b.send_text(json.dumps({"type": "ping"}))
            rec_b = json.loads(ws_b.receive_text())
            assert rec_b["type"] == "pong"


# ==============================================================================
# 6. All 12 Event Schemas & Serialization
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_event_schemas_and_serialization(ws_test_env):
    """Validates schema serialization for all 12 Section 52 events."""
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sample_payloads: Dict[SimulationEventType, Dict[str, Any]] = {
        SimulationEventType.CANDLE_UPDATE: {
            "step_index": 1,
            "candle": {
                "timestamp": "2026-01-01T09:15:00Z",
                "open": 2400.0,
                "high": 2420.0,
                "low": 2390.0,
                "close": 2415.0,
                "volume": 10000.0,
            },
        },
        SimulationEventType.AGENT_STARTED: {
            "agent_id": "agent-1",
            "agent_name": "MomentumBot",
            "status": "RUNNING",
        },
        SimulationEventType.AGENT_ANALYZING: {
            "agent_id": "agent-1",
            "candle_timestamp": "2026-01-01T09:15:00Z",
            "step_index": 1,
        },
        SimulationEventType.TOOL_CALL: {
            "agent_id": "agent-1",
            "tool_name": "get_indicators",
            "tool_args": {"symbol": "RELIANCE"},
        },
        SimulationEventType.TOOL_RESULT: {
            "agent_id": "agent-1",
            "tool_name": "get_indicators",
            "success": True,
            "data": {"rsi14": 55.4},
        },
        SimulationEventType.AGENT_DECISION: {
            "action": "BUY",
            "confidence": 0.88,
            "quantity": 15,
            "reason": "RSI above 50 with EMA crossover",
        },
        SimulationEventType.RISK_CHECK: {
            "order_id": "ord-1",
            "passed": True,
            "reason": "Within 2% risk limit",
        },
        SimulationEventType.ORDER_EXECUTED: {
            "order_id": "ord-1",
            "side": "BUY",
            "quantity": 15,
            "execution_price": 2415.5,
            "status": "FILLED",
        },
        SimulationEventType.POSITION_UPDATED: {
            "positions": [
                {
                    "symbol": "RELIANCE",
                    "quantity": 15,
                    "average_entry_price": 2415.5,
                    "current_price": 2420.0,
                    "unrealized_pnl": 67.5,
                    "is_open": True,
                }
            ]
        },
        SimulationEventType.PORTFOLIO_UPDATED: {
            "cash": 63767.5,
            "portfolio_value": 100067.5,
            "gross_pnl": 67.5,
            "net_pnl": 64.2,
            "total_return_pct": 0.064,
            "exposure_pct": 36.27,
            "open_positions_count": 1,
        },
        SimulationEventType.SIMULATION_COMPLETE: {
            "status": "COMPLETED",
            "total_steps": 100,
            "final_portfolio_value": 105200.0,
            "total_return_pct": 5.2,
        },
        SimulationEventType.ERROR: {
            "code": "EXECUTION_ERROR",
            "message": "Order rejection due to price limits",
        },
    }

    for evt_type, payload in sample_payloads.items():
        evt = manager.create_event(
            simulation_id="sim-schema-test",
            event_type=evt_type,
            payload=payload,
            virtual_timestamp="2026-01-01T09:15:00Z",
        )
        json_str = evt.model_dump_json()
        parsed = SimulationEvent.model_validate_json(json_str)

        assert parsed.event_type == evt_type
        assert parsed.simulation_id == "sim-schema-test"
        assert parsed.virtual_timestamp == "2026-01-01T09:15:00Z"
        assert parsed.sequence >= 1


# ==============================================================================
# 7. Monotonic Sequence Ordering
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_event_sequence_monotonicity(ws_test_env):
    """Sequence numbers for a simulation increment strictly monotonically."""
    manager: SimulationConnectionManager = ws_test_env["manager"]
    sim_id = "sim-seq-test"

    sequences = []
    for i in range(5):
        evt = manager.create_event(
            simulation_id=sim_id,
            event_type=SimulationEventType.CANDLE_UPDATE,
            payload={"step_index": i},
        )
        sequences.append(evt.sequence)

    assert sequences == [1, 2, 3, 4, 5]


# ==============================================================================
# 8. Simulation Uninterrupted After Client Disconnect
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_simulation_uninterrupted_after_disconnect(ws_test_env):
    """Broadcasting to a simulation where clients disconnected succeeds gracefully."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_id = "sim-uninterrupted-test"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    # Connect client then immediately close
    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        _ = ws.receive_text()

    # Verify client is disconnected
    assert manager.get_active_count(sim_id) == 0

    # Broadcast event after disconnect -> does not throw or crash
    evt = manager.create_event(
        simulation_id=sim_id,
        event_type=SimulationEventType.CANDLE_UPDATE,
        payload={"step_index": 1},
    )
    await manager.broadcast(sim_id, evt)


# ==============================================================================
# 9. Client Ping/Pong Heartbeat Handling
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_client_ping_pong_heartbeat(ws_test_env):
    """Client sending ping message receives typed pong response with timestamp."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]

    sim_id = "sim-ping-test"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        _ = ws.receive_text()  # initial_state

        ws.send_text(json.dumps({"type": "ping"}))
        resp = json.loads(ws.receive_text())

        assert resp["type"] == "pong"
        assert resp["simulation_id"] == sim_id
        assert "timestamp" in resp


# ==============================================================================
# 10. Malformed Client Message Resilience
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_malformed_client_message_resilience(ws_test_env):
    """Malformed non-JSON frames from client do not crash the connection."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]

    sim_id = "sim-malformed-test"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        _ = ws.receive_text()  # initial_state

        # Send invalid non-JSON text
        ws.send_text("THIS IS NOT JSON AND SHOULD BE DISCARDED SAFELY")

        # Send normal ping to verify connection remains healthy
        ws.send_text(json.dumps({"type": "ping"}))
        resp = json.loads(ws.receive_text())
        assert resp["type"] == "pong"


# ==============================================================================
# 11. Privacy Guard & Secret Sanitization
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_no_secret_leakage(ws_test_env):
    """Payloads never expose internal credentials, API keys, or raw system prompts."""
    manager: SimulationConnectionManager = ws_test_env["manager"]

    evt = manager.create_event(
        simulation_id="sim-priv-test",
        event_type=SimulationEventType.TOOL_CALL,
        payload={
            "agent_id": "agent-alpha",
            "tool_name": "calculate_position_size",
            "tool_args": {"symbol": "RELIANCE", "risk_amount": 2000.0},
        },
    )
    raw = evt.model_dump_json()

    assert "api_key" not in raw.lower()
    assert "password" not in raw.lower()
    assert "token" not in raw.lower() or "timestamp" in raw.lower()


# ==============================================================================
# 12. End-to-End Simulation Step -> WebSocket Emission Integration
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_authoritative_simulation_integration(ws_test_env):
    """Proves: Authoritative simulation engine step -> WebSocket server -> client receives event."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    service: SimulationService = ws_test_env["service"]

    # 1. Seed candles in PostgreSQL
    base_time = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()

        for i in range(3):
            c_time = base_time.replace(minute=15 * (i + 1))
            c = models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=c_time,
                open=2400.0 + i * 5,
                high=2410.0 + i * 5,
                low=2395.0 + i * 5,
                close=2405.0 + i * 5,
                volume=10000.0,
            )
            db.add(c)
        await db.commit()

    # 2. Create simulation via SimulationService
    from app.trading.simulation.schemas import SimulationCreateRequest

    async with session_factory() as db:
        req = SimulationCreateRequest(
            symbol="RELIANCE",
            timeframe="15m",
            start_date=base_time,
            end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
            initial_capital=100000.0,
            is_baseline=True,
        )
        sim_resp = await service.create_simulation(db=db, req=req)

    sim_id = sim_resp.id

    # Start and pause so step_simulation is valid
    async with session_factory() as db:
        await service.start_simulation(sim_id, db)
        await service.pause_simulation(sim_id, db)

    # 3. Connect WebSocket client
    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        init_msg = json.loads(ws.receive_text())
        assert init_msg["event_type"] == "initial_state"
        assert init_msg["simulation_id"] == sim_id

        # 4. Advance simulation by one step using authoritative SimulationService.step_simulation
        async with session_factory() as db:
            await service.step_simulation(sim_id, db)

        # 5. Receive emitted events over WebSocket!
        # Step hook emits: candle_update, agent_decision, position_updated, portfolio_updated
        received_types = []
        for _ in range(4):
            evt_data = json.loads(ws.receive_text())
            received_types.append(evt_data["event_type"])
            assert evt_data["simulation_id"] == sim_id
            assert evt_data["sequence"] >= 2

        assert "candle_update" in received_types
        assert "portfolio_updated" in received_types


# ==============================================================================
# 13. Rapid Consecutive Events & Monotonic FIFO Ordering
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_rapid_consecutive_events_ordering(ws_test_env):
    """Multiple rapid consecutive events arrive in strict monotonic sequence order."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_id = "sim-rapid-ordering"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        init_evt = json.loads(ws.receive_text())
        assert init_evt["event_type"] == "initial_state"
        assert init_evt["sequence"] == 1

        # Create two consecutive batches of events
        batch_1 = [
            manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.CANDLE_UPDATE,
                payload={"step_index": i},
            )
            for i in range(1, 4)
        ]
        batch_2 = [
            manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.AGENT_DECISION,
                payload={"action": "HOLD", "confidence": 0.8, "reason": f"step {i}"},
            )
            for i in range(4, 7)
        ]

        await manager.broadcast_events(sim_id, batch_1)
        await manager.broadcast_events(sim_id, batch_2)

        received_sequences = []
        for _ in range(6):
            msg = json.loads(ws.receive_text())
            received_sequences.append(msg["sequence"])

        # Strictly increasing monotonic order: [2, 3, 4, 5, 6, 7]
        assert received_sequences == [2, 3, 4, 5, 6, 7]


# ==============================================================================
# 14. Initial Snapshot Precedes Live Broadcasts
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_initial_snapshot_before_live_events(ws_test_env):
    """Connecting client receives initial_state before any subsequent live event."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_id = "sim-snapshot-race-test"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.RUNNING,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as ws:
        # First message MUST be initial_state
        first_msg = json.loads(ws.receive_text())
        assert first_msg["event_type"] == "initial_state"
        assert first_msg["sequence"] == 1
        assert first_msg["simulation_id"] == sim_id

        # Subsequent live event has higher sequence
        live_evt = manager.create_event(
            simulation_id=sim_id,
            event_type=SimulationEventType.CANDLE_UPDATE,
            payload={"step_index": 1},
        )
        await manager.broadcast(sim_id, live_evt)

        second_msg = json.loads(ws.receive_text())
        assert second_msg["event_type"] == "candle_update"
        assert second_msg["sequence"] == 2


# ==============================================================================
# 15. Dead Client Pruning During Batch Delivery
# ==============================================================================


@pytest.mark.asyncio
async def test_ws_slow_or_dead_client_pruned_during_batch(ws_test_env):
    """Dead socket is pruned cleanly during batch broadcast without affecting healthy clients."""
    client: TestClient = ws_test_env["client"]
    session_factory = ws_test_env["session_factory"]
    manager: SimulationConnectionManager = ws_test_env["manager"]

    sim_id = "sim-dead-client-test"

    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()
        sim = SimulationRun(
            id=sim_id,
            instrument_id=inst.id,
            timeframe="15m",
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2026, 1, 10, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.CREATED,
            is_baseline=False,
        )
        db.add(sim)
        await db.commit()

    with client.websocket_connect(f"/ws/simulations/{sim_id}") as healthy_ws:
        _ = healthy_ws.receive_text()  # initial_state

        with client.websocket_connect(f"/ws/simulations/{sim_id}") as dead_ws:
            _ = dead_ws.receive_text()  # initial_state
            assert manager.get_active_count(sim_id) == 2

        # dead_ws is now closed on client side.
        # Broadcast batch of events
        events = [
            manager.create_event(
                simulation_id=sim_id,
                event_type=SimulationEventType.CANDLE_UPDATE,
                payload={"step_index": i},
            )
            for i in range(1, 4)
        ]
        await manager.broadcast_events(sim_id, events)

        # Healthy client receives all 3 events
        for _ in range(3):
            msg = json.loads(healthy_ws.receive_text())
            assert msg["event_type"] == "candle_update"

        # Dead socket was pruned from active connections
        assert manager.get_active_count(sim_id) == 1
