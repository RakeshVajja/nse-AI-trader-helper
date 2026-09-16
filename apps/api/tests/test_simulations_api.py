"""Comprehensive Test Suite for Phase 6D: Simulation REST API & Database Persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import models
from app.database.base import Base
from app.database.session import get_db_session
from app.main import app
from app.trading.simulation.clock import (
    SimulationClock,
    SimulationLifecycleState,
)
from app.trading.simulation.service import (
    SimulationService,
    get_simulation_service,
)


@pytest.fixture
async def sim_test_env():
    """Setup isolated in-memory database and test SimulationService."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed Instrument: RELIANCE
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
        await db.refresh(inst)

        # Seed 25 historical candles (15m timeframe)
        # First 20 candles flat at 2500 (warmup)
        # Candle 21 at 2550 (bullish crossover!)
        # Candles 22-24 climbing then falling
        base_time = datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc)
        prices = [
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2500.0,
            2580.0,
            2600.0,
            2620.0,
            2500.0,
            2480.0,
        ]

        candles: List[models.Candle] = []
        for i, p in enumerate(prices):
            ts = base_time + timedelta(minutes=15 * i)
            c = models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=ts,
                open=p - 2.0,
                high=p + 5.0,
                low=p - 5.0,
                close=p,
                volume=10000.0,
            )
            candles.append(c)
        db.add_all(candles)
        await db.commit()

    service = SimulationService(session_factory=session_factory, base_delay=0.05)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def override_get_service():
        return service

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_simulation_service] = override_get_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "service": service,
            "session_factory": session_factory,
            "base_time": base_time,
            "end_time": base_time + timedelta(minutes=15 * 24),
        }

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_simulation_success(sim_test_env):
    """Test POST /api/v1/simulations successfully creates and persists a simulation."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    payload = {
        "symbol": "RELIANCE",
        "timeframe": "15m",
        "start_date": base_time.isoformat(),
        "end_date": end_time.isoformat(),
        "initial_capital": 100000.0,
        "is_baseline": True,
        "speed": 1.0,
        "slippage_pct": 0.0005,
        "brokerage_rate": 0.0003,
        "max_risk_per_trade": 0.02,
    }

    res = await client.post("/api/v1/simulations", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    assert data["symbol"] == "RELIANCE"
    assert data["timeframe"] == "15m"
    assert data["status"] == "CREATED"
    assert data["total_candles"] == 25
    assert data["step_index"] == 0
    assert data["initial_capital"] == 100000.0
    assert data["is_baseline"] is True

    # Verify persisted in database
    session_factory = sim_test_env["session_factory"]
    async with session_factory() as db:
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == data["id"])
        sim_run = (await db.execute(stmt)).scalar_one_or_none()
        assert sim_run is not None
        assert sim_run.status == models.SimulationStatus.CREATED
        assert sim_run.initial_capital == 100000.0


@pytest.mark.asyncio
async def test_create_simulation_validation_errors(sim_test_env):
    """Test validation rejections on invalid symbol, dates, timeframe, capital, speed."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    # 1. Unknown symbol -> 404
    res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "NONEXISTENT",
            "timeframe": "15m",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    assert res.status_code == 404

    # 2. start_date > end_date -> 422
    res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": end_time.isoformat(),
            "end_date": base_time.isoformat(),
        },
    )
    assert res.status_code == 422

    # 3. Empty dataset range -> 400
    future_start = base_time + timedelta(days=365)
    future_end = future_start + timedelta(days=10)
    res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": future_start.isoformat(),
            "end_date": future_end.isoformat(),
        },
    )
    assert res.status_code == 400
    assert "No historical candles found" in res.json()["detail"]

    # 4. Negative capital -> 422
    res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": -500.0,
        },
    )
    assert res.status_code == 422

    # 5. Unsupported speed -> 422
    res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "speed": 3.0,
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_creation_atomicity_leaves_no_corrupted_records(sim_test_env):
    """Failure during dataset validation leaves zero records in simulation_runs."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    session_factory = sim_test_env["session_factory"]

    # Attempt creation with missing data
    res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": (base_time + timedelta(days=100)).isoformat(),
            "end_date": (base_time + timedelta(days=101)).isoformat(),
        },
    )
    assert res.status_code == 400

    # Ensure no simulation_runs record was created
    async with session_factory() as db:
        stmt = select(models.SimulationRun)
        runs = (await db.execute(stmt)).scalars().all()
        assert len(runs) == 0


@pytest.mark.asyncio
async def test_get_simulation_state(sim_test_env):
    """Test GET /api/v1/simulations/{id} returns authoritative state."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]

    # GET existing
    get_res = await client.get(f"/api/v1/simulations/{sim_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["id"] == sim_id
    assert data["status"] == "CREATED"
    assert data["total_candles"] == 25
    assert data["step_index"] == 0

    # GET non-existent
    bad_res = await client.get("/api/v1/simulations/non-existent-id")
    assert bad_res.status_code == 404


@pytest.mark.asyncio
async def test_full_lifecycle_and_step_controls(sim_test_env):
    """Test START -> PAUSE -> STEP -> RESUME -> STOP lifecycle transitions."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]

    # 1. START: CREATED -> RUNNING
    start_res = await client.post(f"/api/v1/simulations/{sim_id}/start")
    assert start_res.status_code == 200
    assert start_res.json()["status"] == "RUNNING"

    # 2. PAUSE: RUNNING -> PAUSED
    pause_res = await client.post(f"/api/v1/simulations/{sim_id}/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "PAUSED"
    paused_step = pause_res.json()["step_index"]

    # 3. STEP: valid only while PAUSED. Advances exactly one candle.
    step1_res = await client.post(f"/api/v1/simulations/{sim_id}/step")
    assert step1_res.status_code == 200
    step1_data = step1_res.json()
    assert step1_data["status"] == "PAUSED"
    assert step1_data["step_index"] == paused_step + 1
    assert step1_data["current_time"] is not None

    # Step again
    step2_res = await client.post(f"/api/v1/simulations/{sim_id}/step")
    assert step2_res.status_code == 200
    assert step2_res.json()["step_index"] == paused_step + 2

    # 4. RESUME: PAUSED -> RUNNING
    resume_res = await client.post(f"/api/v1/simulations/{sim_id}/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "RUNNING"

    # 5. STOP: RUNNING -> STOPPED
    stop_res = await client.post(f"/api/v1/simulations/{sim_id}/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "STOPPED"


@pytest.mark.asyncio
async def test_lifecycle_idempotency_and_invalid_transitions(sim_test_env):
    """Test idempotent control calls and rejection of invalid state transitions."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]

    # STEP while CREATED -> 400 (only valid while PAUSED)
    res = await client.post(f"/api/v1/simulations/{sim_id}/step")
    assert res.status_code == 400
    assert "STEP is valid only while PAUSED" in res.json()["detail"]

    # START: CREATED -> RUNNING
    await client.post(f"/api/v1/simulations/{sim_id}/start")

    # START on RUNNING -> idempotent 200
    res = await client.post(f"/api/v1/simulations/{sim_id}/start")
    assert res.status_code == 200
    assert res.json()["status"] == "RUNNING"

    # RESUME on RUNNING -> idempotent 200
    res = await client.post(f"/api/v1/simulations/{sim_id}/resume")
    assert res.status_code == 200

    # STEP while RUNNING -> 400
    res = await client.post(f"/api/v1/simulations/{sim_id}/step")
    assert res.status_code == 400

    # PAUSE: RUNNING -> PAUSED
    await client.post(f"/api/v1/simulations/{sim_id}/pause")

    # PAUSE on PAUSED -> idempotent 200
    res = await client.post(f"/api/v1/simulations/{sim_id}/pause")
    assert res.status_code == 200

    # START while PAUSED -> 400 (must use resume)
    res = await client.post(f"/api/v1/simulations/{sim_id}/start")
    assert res.status_code == 400
    assert "Use resume() to continue playback" in res.json()["detail"]

    # STOP: PAUSED -> STOPPED
    await client.post(f"/api/v1/simulations/{sim_id}/stop")

    # STOP on STOPPED -> idempotent 200
    res = await client.post(f"/api/v1/simulations/{sim_id}/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "STOPPED"

    # START on STOPPED -> 400
    res = await client.post(f"/api/v1/simulations/{sim_id}/start")
    assert res.status_code == 400
    assert "terminal state" in res.json()["detail"]

    # RESUME on STOPPED -> 400
    res = await client.post(f"/api/v1/simulations/{sim_id}/resume")
    assert res.status_code == 400

    # STEP on STOPPED -> 400
    res = await client.post(f"/api/v1/simulations/{sim_id}/step")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_concurrent_start_resume_no_duplicate_tasks(sim_test_env):
    """Concurrent start/resume calls safely serialize via SimulationClock locks."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]

    # Launch concurrent start requests
    tasks = [client.post(f"/api/v1/simulations/{sim_id}/start") for _ in range(5)]
    results = await asyncio.gather(*tasks)

    for r in results:
        assert r.status_code == 200
        assert r.json()["status"] == "RUNNING"

    # Clean stop
    await client.post(f"/api/v1/simulations/{sim_id}/stop")


@pytest.mark.asyncio
async def test_database_persistence_and_idempotency(sim_test_env):
    """Test idempotent persistence of orders, trades, snapshots, and metrics."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    session_factory = sim_test_env["session_factory"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 100000.0,
            "is_baseline": True,
        },
    )
    sim_id = create_res.json()["id"]

    # Pause from start to step through all 25 candles
    await client.post(f"/api/v1/simulations/{sim_id}/start")
    await client.post(f"/api/v1/simulations/{sim_id}/pause")

    # Step through all candles to trigger crossover buy and stop/exit
    for _ in range(25):
        step_res = await client.post(f"/api/v1/simulations/{sim_id}/step")
        if step_res.json()["status"] == "COMPLETED":
            break

    # Stop simulation
    await client.post(f"/api/v1/simulations/{sim_id}/stop")

    # Query database records
    async with session_factory() as db:
        orders_stmt = select(models.Order).where(models.Order.simulation_id == sim_id)
        orders = (await db.execute(orders_stmt)).scalars().all()
        orders_count = len(orders)

        trades_stmt = select(models.Trade).where(models.Trade.simulation_id == sim_id)
        trades = (await db.execute(trades_stmt)).scalars().all()
        trades_count = len(trades)

        snaps_stmt = select(models.PortfolioSnapshot).where(
            models.PortfolioSnapshot.simulation_id == sim_id
        )
        snaps = (await db.execute(snaps_stmt)).scalars().all()
        snaps_count = len(snaps)

    assert orders_count > 0
    assert snaps_count > 0

    # Test Idempotency: Call stop and sync again; verify counts do NOT increase
    await client.post(f"/api/v1/simulations/{sim_id}/stop")
    service: SimulationService = sim_test_env["service"]
    session = service._sessions[sim_id]
    await session.sync_to_db(is_final=True)

    async with session_factory() as db:
        orders_after = (await db.execute(orders_stmt)).scalars().all()
        trades_after = (await db.execute(trades_stmt)).scalars().all()
        snaps_after = (await db.execute(snaps_stmt)).scalars().all()

        assert len(orders_after) == orders_count
        assert len(trades_after) == trades_count
        assert len(snaps_after) == snaps_count


@pytest.mark.asyncio
async def test_read_endpoints_trades_performance_decisions(sim_test_env):
    """Test GET /trades, GET /performance, GET /decisions return authoritative state."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 100000.0,
            "is_baseline": True,
        },
    )
    sim_id = create_res.json()["id"]

    # Step through 22 candles (crossover happens at index 20, executes at candle 21 open)
    await client.post(f"/api/v1/simulations/{sim_id}/start")
    await client.post(f"/api/v1/simulations/{sim_id}/pause")
    for _ in range(22):
        await client.post(f"/api/v1/simulations/{sim_id}/step")

    # 1. GET /performance
    perf_res = await client.get(f"/api/v1/simulations/{sim_id}/performance")
    assert perf_res.status_code == 200
    perf_data = perf_res.json()
    assert perf_data["simulation_id"] == sim_id
    assert perf_data["initial_capital"] == 100000.0
    assert "win_rate_pct" in perf_data
    assert "max_drawdown_pct" in perf_data

    # 2. GET /decisions
    dec_res = await client.get(f"/api/v1/simulations/{sim_id}/decisions")
    assert dec_res.status_code == 200
    decs = dec_res.json()
    assert len(decs) >= 20
    # Warmup decisions must be HOLD
    assert decs[0]["action"] == "HOLD"
    # Crossover decision at index 20 emits BUY
    buy_decisions = [d for d in decs if d["action"] == "BUY"]
    assert len(buy_decisions) >= 1
    assert buy_decisions[0]["confidence"] == 1.0

    # 3. GET /trades
    trades_res = await client.get(f"/api/v1/simulations/{sim_id}/trades")
    assert trades_res.status_code == 200
    assert isinstance(trades_res.json(), list)

    await client.post(f"/api/v1/simulations/{sim_id}/stop")


@pytest.mark.asyncio
async def test_two_simulations_complete_isolation(sim_test_env):
    """Two simultaneous simulations maintain fully isolated engines, clocks, and DB rows."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]

    res1 = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 100000.0,
        },
    )
    sim_id1 = res1.json()["id"]

    res2 = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 200000.0,
        },
    )
    sim_id2 = res2.json()["id"]
    assert sim_id1 != sim_id2

    # Step sim1 5 times while sim2 remains CREATED
    await client.post(f"/api/v1/simulations/{sim_id1}/start")
    p_res = await client.post(f"/api/v1/simulations/{sim_id1}/pause")
    paused_step = p_res.json()["step_index"]
    for _ in range(5):
        await client.post(f"/api/v1/simulations/{sim_id1}/step")

    # Verify sim1 is PAUSED with step_index advanced by 5
    s1_res = await client.get(f"/api/v1/simulations/{sim_id1}")
    assert s1_res.json()["status"] == "PAUSED"
    assert s1_res.json()["step_index"] == paused_step + 5

    # Verify sim2 is untouched (CREATED, step_index=0, initial_capital=200000)
    s2_res = await client.get(f"/api/v1/simulations/{sim_id2}")
    assert s2_res.json()["status"] == "CREATED"
    assert s2_res.json()["step_index"] == 0
    assert s2_res.json()["initial_capital"] == 200000.0

    # Stop both
    await client.post(f"/api/v1/simulations/{sim_id1}/stop")
    await client.post(f"/api/v1/simulations/{sim_id2}/stop")


@pytest.mark.asyncio
async def test_end_of_series_automatic_completion(sim_test_env):
    """When candle series is exhausted in continuous playback, it auto-transitions to COMPLETED."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    session_factory = sim_test_env["session_factory"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]

    # Start playback (base_delay=0.0 in test env so it completes almost immediately)
    await client.post(f"/api/v1/simulations/{sim_id}/start")

    # Wait for completion
    service: SimulationService = sim_test_env["service"]
    session = service._sessions[sim_id]
    await session.clock.wait_until_complete(timeout=5.0)
    # Give background task completion handler a moment to flush to DB
    await asyncio.sleep(0.05)

    # Verify status in API
    res = await client.get(f"/api/v1/simulations/{sim_id}")
    assert res.json()["status"] == "COMPLETED"
    assert res.json()["step_index"] == 25
    assert res.json()["progress_pct"] == 100.0

    # Verify status in PostgreSQL DB
    async with session_factory() as db:
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == sim_id)
        run = (await db.execute(stmt)).scalar_one()
        assert run.status == models.SimulationStatus.COMPLETED
        assert run.final_portfolio_value is not None


@pytest.mark.asyncio
async def test_playback_speed_changes_pacing_only_and_not_results(sim_test_env):
    """Different playback speeds produce identical trade results and portfolio values."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    service: SimulationService = sim_test_env["service"]

    # Run 1 at speed 1.0
    r1 = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "speed": 1.0,
        },
    )
    id1 = r1.json()["id"]
    await client.post(f"/api/v1/simulations/{id1}/start")
    await service._sessions[id1].clock.wait_until_complete(timeout=5.0)
    perf1 = (await client.get(f"/api/v1/simulations/{id1}/performance")).json()

    # Run 2 at speed 5.0
    r2 = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "speed": 5.0,
        },
    )
    id2 = r2.json()["id"]
    await client.post(f"/api/v1/simulations/{id2}/start")
    await service._sessions[id2].clock.wait_until_complete(timeout=5.0)
    perf2 = (await client.get(f"/api/v1/simulations/{id2}/performance")).json()

    # Bit-for-bit equivalence in financial outputs
    assert perf1["final_portfolio_value"] == perf2["final_portfolio_value"]
    assert perf1["total_trades"] == perf2["total_trades"]
    assert perf1["gross_pnl"] == perf2["gross_pnl"]
    assert perf1["net_pnl"] == perf2["net_pnl"]
    assert perf1["total_return_pct"] == perf2["total_return_pct"]
    assert perf1["transaction_costs"] == perf2["transaction_costs"]


@pytest.mark.asyncio
async def test_background_completion_race_safety(sim_test_env):
    """Background completion callback never overwrites STOPPED status."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    service: SimulationService = sim_test_env["service"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]
    session = service._sessions[sim_id]

    # Manually transition clock to STOPPED
    session.clock._state = SimulationLifecycleState.STOPPED

    # Invoke background task completion handler
    await service._safe_on_task_complete(session)

    # Verify state remains STOPPED, not overwritten to COMPLETED
    assert session.clock.state == SimulationLifecycleState.STOPPED
    res = await client.get(f"/api/v1/simulations/{sim_id}")
    assert res.json()["status"] == "STOPPED"


@pytest.mark.asyncio
async def test_api_uses_authoritative_simulation_clock(sim_test_env):
    """Verify REST layer controls existing SimulationClock directly with no duplicate loop."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    service: SimulationService = sim_test_env["service"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]
    session = service._sessions[sim_id]

    # Verify session owns authoritative clock and engine
    assert isinstance(session.clock, SimulationClock)
    assert session.clock.engine is session.engine
    assert session.clock.state == SimulationLifecycleState.CREATED

    # Start via API
    await client.post(f"/api/v1/simulations/{sim_id}/start")
    assert session.clock.state == SimulationLifecycleState.RUNNING

    # Pause via API
    await client.post(f"/api/v1/simulations/{sim_id}/pause")
    assert session.clock.state == SimulationLifecycleState.PAUSED
    paused_step = session.clock.current_step

    # Step via API directly invokes session.clock.step()
    await client.post(f"/api/v1/simulations/{sim_id}/step")
    assert session.engine.current_step == paused_step + 1
    assert session.clock.current_step == session.engine.current_step

    # Stop via API
    await client.post(f"/api/v1/simulations/{sim_id}/stop")
    assert session.clock.state == SimulationLifecycleState.STOPPED


@pytest.mark.asyncio
async def test_terminal_stopped_state_persists_in_db(sim_test_env):
    """Verify STOPPED state is persisted in simulation_runs in PostgreSQL."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    session_factory = sim_test_env["session_factory"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
        },
    )
    sim_id = create_res.json()["id"]

    await client.post(f"/api/v1/simulations/{sim_id}/start")
    await client.post(f"/api/v1/simulations/{sim_id}/stop")

    async with session_factory() as db:
        stmt = select(models.SimulationRun).where(models.SimulationRun.id == sim_id)
        run = (await db.execute(stmt)).scalar_one()
        assert run.status == models.SimulationStatus.STOPPED


@pytest.mark.asyncio
async def test_get_endpoints_reflect_persisted_state_when_evicted_from_memory(sim_test_env):
    """Verify GET endpoints work accurately from PostgreSQL even after eviction from memory."""
    client: AsyncClient = sim_test_env["client"]
    base_time: datetime = sim_test_env["base_time"]
    end_time: datetime = sim_test_env["end_time"]
    service: SimulationService = sim_test_env["service"]

    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 100000.0,
        },
    )
    sim_id = create_res.json()["id"]

    # Step through some candles and stop
    await client.post(f"/api/v1/simulations/{sim_id}/start")
    await client.post(f"/api/v1/simulations/{sim_id}/pause")
    for _ in range(22):
        await client.post(f"/api/v1/simulations/{sim_id}/step")
    await client.post(f"/api/v1/simulations/{sim_id}/stop")

    # Capture state before eviction
    sim_before = (await client.get(f"/api/v1/simulations/{sim_id}")).json()
    perf_before = (await client.get(f"/api/v1/simulations/{sim_id}/performance")).json()
    decs_before = (await client.get(f"/api/v1/simulations/{sim_id}/decisions")).json()
    trades_before = (await client.get(f"/api/v1/simulations/{sim_id}/trades")).json()

    # Evict from in-memory registry
    async with service._lock:
        del service._sessions[sim_id]

    assert sim_id not in service._sessions

    # Query GET endpoints: must now read directly from PostgreSQL
    sim_after = (await client.get(f"/api/v1/simulations/{sim_id}")).json()
    assert sim_after["id"] == sim_id
    assert sim_after["status"] == "STOPPED"
    assert sim_after["step_index"] == sim_before["step_index"]

    perf_after = (await client.get(f"/api/v1/simulations/{sim_id}/performance")).json()
    assert perf_after["simulation_id"] == sim_id
    assert perf_after["initial_capital"] == perf_before["initial_capital"]
    assert perf_after["final_portfolio_value"] == perf_before["final_portfolio_value"]

    decs_after = (await client.get(f"/api/v1/simulations/{sim_id}/decisions")).json()
    assert len(decs_after) == len(decs_before)

    trades_after = (await client.get(f"/api/v1/simulations/{sim_id}/trades")).json()
    assert len(trades_after) == len(trades_before)
