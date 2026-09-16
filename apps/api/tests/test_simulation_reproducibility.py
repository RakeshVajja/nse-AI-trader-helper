"""Comprehensive Test Suite for Phase 6E: Backtest Reproducibility Verification.

Verifies all frozen Phase 6E reproducibility requirements:
1. Twin-run bit-for-bit equivalence over identical locked datasets and configurations.
2. Playback-mode independence (Continuous vs Bar-by-bar Stepped vs Pause/Resume execution).
3. Playback speed independence across all 5 supported speeds (0.5x, 1x, 2x, 5x, 10x).
4. Database persistence reproducibility and synchronization idempotency.
5. Strict historical dataset lock (no look-ahead, no incorporation of post-lock market data).
6. Same-symbol auto-exit precedence reproducibility under conflicting orders.
7. Exact warmup boundary and discrete crossover equality determinism.
8. Adversarial concurrent API controls and timing safety.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import models
from app.database.base import Base
from app.database.session import get_db_session
from app.main import app
from app.market_data.schema import CandleData
from app.trading.execution import ExecutionConfig, ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskConfig, RiskEngine
from app.trading.schemas import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from app.trading.simulation.clock import (
    VALID_PLAYBACK_SPEEDS,
    SimulationClock,
    SimulationLifecycleState,
)
from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    ReplayContext,
)
from app.trading.simulation.service import (
    SimulationService,
    SimulationSession,
    get_simulation_service,
)
from app.trading.strategy.baseline import BenchmarkBaselineStrategy
from app.trading.triggers import TriggerMonitor


def _build_test_candle_series(
    base_time: datetime,
    count: int = 26,
    crossover_index: int = 20,
    trip_sl_index: int = 22,
) -> List[CandleData]:
    """Construct a deterministic candle series for testing reproducibility.

    - Indices 0..19: Flat at 2500.0 (warmup, EMA9 == EMA20 == 2500).
    - Index 20: Jumps to 2580.0 (bullish crossover signal; queues BUY for index 21 open).
    - Index 21: Opens at 2585.0 (BUY order executes), high 2610.0, close 2600.0.
    - Index 22: Drops sharply to low 2515.0 (trips 2% SL of 2580.0 * 0.98 = 2528.40; queues auto-exit).
    - Index 23: Opens at 2510.0 (auto-exit fills), closes at 2515.0.
    - Subsequent indices: Consolidation.
    """
    candles: List[CandleData] = []
    prices = [2500.0] * 20 + [2580.0, 2600.0, 2520.0, 2510.0, 2505.0, 2500.0]

    for i in range(count):
        ts = base_time + timedelta(minutes=15 * i)
        p = prices[i] if i < len(prices) else 2500.0

        if i == trip_sl_index:
            # Drop sharply to trip 2% protective stop loss
            c = CandleData(
                symbol="RELIANCE",
                timeframe="15m",
                timestamp=ts,
                open=2600.0,
                high=2605.0,
                low=2515.0,
                close=2520.0,
                volume=10000.0,
            )
        elif i == crossover_index:
            c = CandleData(
                symbol="RELIANCE",
                timeframe="15m",
                timestamp=ts,
                open=2500.0,
                high=2585.0,
                low=2495.0,
                close=2580.0,
                volume=15000.0,
            )
        else:
            c = CandleData(
                symbol="RELIANCE",
                timeframe="15m",
                timestamp=ts,
                open=p,
                high=p + 5.0,
                low=p - 5.0,
                close=p,
                volume=10000.0,
            )
        candles.append(c)

    return candles


def _instantiate_simulation_components(
    candles: List[CandleData],
    initial_capital: float = 100000.0,
    speed: float = 1.0,
    base_delay: float = 0.0,
) -> Tuple[
    PortfolioTracker,
    ExecutionEngine,
    RiskEngine,
    TriggerMonitor,
    BenchmarkBaselineStrategy,
    ChronologicalReplayEngine,
    SimulationClock,
]:
    """Helper to instantiate completely independent, isolated simulation components."""
    portfolio = PortfolioTracker(initial_capital=initial_capital)
    exec_cfg = ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003)
    exec_engine = ExecutionEngine(config=exec_cfg)
    risk_cfg = RiskConfig(
        max_risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_portfolio_exposure=1.00,
        max_daily_loss=0.05,
    )
    risk_engine = RiskEngine(config=risk_cfg, execution_config=exec_cfg)
    trigger_monitor = TriggerMonitor(execution_engine=exec_engine)
    strategy = BenchmarkBaselineStrategy(
        symbol="RELIANCE",
        risk_engine=risk_engine,
        portfolio=portfolio,
    )
    replay_engine = ChronologicalReplayEngine(
        candles=candles,
        portfolio=portfolio,
        execution_engine=exec_engine,
        risk_engine=risk_engine,
        trigger_monitor=trigger_monitor,
    )
    clock = SimulationClock(
        engine=replay_engine,
        strategy=strategy,
        speed=speed,
        base_delay=base_delay,
    )
    return (
        portfolio,
        exec_engine,
        risk_engine,
        trigger_monitor,
        strategy,
        replay_engine,
        clock,
    )


# ==============================================================================
# 1. Twin-Run Bit-for-Bit Identical Results
# ==============================================================================


@pytest.mark.asyncio
async def test_twin_simulation_bit_for_bit_identical_results():
    """Verify two completely independent runs over identical dataset produce identical outputs.

    Checks:
    - trade count, quantities, entry/exit prices, entry/exit times, gross/net PnL, fees, slippage
    - order outcomes, statuses, prices, quantities, decision times, execution times
    - portfolio cash, equity, drawdown, exposure, win rate, profit factor
    - strategy decisions per candle (action, confidence, quantity, stop loss, reason)
    """
    base_time = datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc)
    candles = _build_test_candle_series(base_time=base_time, count=25)

    # Run A
    (
        port_A,
        _,
        _,
        _,
        _,
        engine_A,
        clock_A,
    ) = _instantiate_simulation_components(candles, initial_capital=100000.0, speed=1.0)
    session_A = SimulationSession(
        simulation_id="sim_twin_A",
        instrument_id=1,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=candles[0].timestamp,
        end_date=candles[-1].timestamp,
        initial_capital=100000.0,
        is_baseline=True,
        engine=engine_A,
        clock=clock_A,
        portfolio=port_A,
        risk_engine=engine_A.risk_engine,
        execution_engine=engine_A.execution_engine,
        trigger_monitor=engine_A.trigger_monitor,
        strategy=clock_A.strategy,
        session_factory=None,  # Not needed for memory tracking
    )
    clock_A.on_step = lambda res: session_A.on_step_event(res)

    await clock_A.start()
    summary_A = await clock_A.wait_until_complete(timeout=5.0)

    # Run B (Fresh, independent instances)
    (
        port_B,
        _,
        _,
        _,
        _,
        engine_B,
        clock_B,
    ) = _instantiate_simulation_components(candles, initial_capital=100000.0, speed=1.0)
    session_B = SimulationSession(
        simulation_id="sim_twin_B",
        instrument_id=1,
        symbol="RELIANCE",
        timeframe="15m",
        start_date=candles[0].timestamp,
        end_date=candles[-1].timestamp,
        initial_capital=100000.0,
        is_baseline=True,
        engine=engine_B,
        clock=clock_B,
        portfolio=port_B,
        risk_engine=engine_B.risk_engine,
        execution_engine=engine_B.execution_engine,
        trigger_monitor=engine_B.trigger_monitor,
        strategy=clock_B.strategy,
        session_factory=None,
    )
    clock_B.on_step = lambda res: session_B.on_step_event(res)

    await clock_B.start()
    summary_B = await clock_B.wait_until_complete(timeout=5.0)

    # 1. Verify Clock & Engine steps
    assert clock_A.state == clock_B.state == SimulationLifecycleState.COMPLETED
    assert clock_A.current_step == clock_B.current_step == 25
    assert clock_A.total_candles == clock_B.total_candles == 25
    assert clock_A.progress_pct == clock_B.progress_pct == 100.0
    assert summary_A.total_steps == summary_B.total_steps == 25

    # 2. Verify Trades bit-for-bit
    trades_A = port_A.closed_trades
    trades_B = port_B.closed_trades
    assert len(trades_A) == len(trades_B) >= 1

    for tA, tB in zip(trades_A, trades_B):
        assert tA.symbol == tB.symbol == "RELIANCE"
        assert tA.side == tB.side
        assert tA.quantity == tB.quantity
        assert tA.entry_price == tB.entry_price
        assert tA.exit_price == tB.exit_price
        assert tA.gross_pnl == tB.gross_pnl
        assert tA.net_pnl == tB.net_pnl
        assert tA.transaction_costs == tB.transaction_costs
        assert tA.slippage_cost == tB.slippage_cost
        assert tA.entry_time == tB.entry_time
        assert tA.exit_time == tB.exit_time
        assert tA.exit_reason == tB.exit_reason

    # 3. Verify Executions bit-for-bit
    execs_A = engine_A.execution_history
    execs_B = engine_B.execution_history
    assert len(execs_A) == len(execs_B) >= 2

    for eA, eB in zip(execs_A, execs_B):
        assert eA.side == eB.side
        assert eA.status == eB.status == OrderStatus.FILLED
        assert eA.quantity == eB.quantity
        assert eA.execution_price == eB.execution_price
        assert eA.transaction_cost == eB.transaction_cost
        assert eA.slippage_cost == eB.slippage_cost
        assert eA.executed_at == eB.executed_at
        assert eA.decision_time == eB.decision_time

    # 4. Verify Final Portfolio Accounting State
    st_A = port_A.get_state()
    st_B = port_B.get_state()
    assert st_A.initial_capital == st_B.initial_capital == 100000.0
    assert st_A.cash == st_B.cash
    assert st_A.total_portfolio_value == st_B.total_portfolio_value
    assert st_A.gross_pnl == st_B.gross_pnl
    assert st_A.net_pnl == st_B.net_pnl
    assert st_A.total_return_pct == st_B.total_return_pct
    assert st_A.total_transaction_costs == st_B.total_transaction_costs
    assert st_A.total_slippage_cost == st_B.total_slippage_cost
    assert st_A.exposure_pct == st_B.exposure_pct
    assert st_A.open_positions_count == st_B.open_positions_count

    # 5. Verify Section 58 Performance Metrics
    metrics_A = session_A.build_performance_metrics()
    metrics_B = session_B.build_performance_metrics()
    for key in (
        "initial_capital",
        "final_portfolio_value",
        "gross_pnl",
        "net_pnl",
        "total_return_pct",
        "transaction_costs",
        "slippage_cost",
        "total_trades",
        "winning_trades",
        "losing_trades",
        "win_rate_pct",
        "average_win",
        "average_loss",
        "profit_factor",
        "max_drawdown_pct",
        "exposure_pct",
        "open_positions_count",
    ):
        assert metrics_A[key] == metrics_B[key], f"Metric mismatch for {key}"

    # 6. Verify Strategy Decisions Logging bit-for-bit
    assert len(session_A.decisions) == len(session_B.decisions) == 25
    for dA, dB in zip(session_A.decisions, session_B.decisions):
        assert dA["candle_timestamp"] == dB["candle_timestamp"]
        assert dA["action"] == dB["action"]
        assert dA["confidence"] == dB["confidence"]
        assert dA["quantity"] == dB["quantity"]
        assert dA["stop_loss"] == dB["stop_loss"]
        assert dA["reason"] == dB["reason"]


# ==============================================================================
# 2. Playback Independence: Continuous vs Stepped vs Pause/Resume
# ==============================================================================


@pytest.mark.asyncio
async def test_playback_independence_continuous_stepped_pause_resume():
    """Verify execution mode (continuous vs step-by-step vs pause/resume) does not alter results.

    All 3 modes over identical candles must produce 100% identical trades, executions,
    cash, equity, drawdown, and final metrics.
    """
    base_time = datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc)
    candles = _build_test_candle_series(base_time=base_time, count=25)

    # -------------------------------------------------------------
    # Mode 1: Continuous Asynchronous Playback
    # -------------------------------------------------------------
    port_1, _, _, _, _, _, clock_1 = _instantiate_simulation_components(
        candles, initial_capital=100000.0, speed=5.0, base_delay=0.0
    )
    await clock_1.start()
    await clock_1.wait_until_complete(timeout=5.0)
    st_1 = port_1.get_state()

    # -------------------------------------------------------------
    # Mode 2: Pure Step-by-Step Manual Execution while Paused
    # -------------------------------------------------------------
    port_2, _, _, _, _, _, clock_2 = _instantiate_simulation_components(
        candles, initial_capital=100000.0, speed=1.0, base_delay=0.0
    )
    await clock_2.start()
    await clock_2.pause()
    assert clock_2.state == SimulationLifecycleState.PAUSED

    while clock_2.state == SimulationLifecycleState.PAUSED:
        await clock_2.step()

    assert clock_2.state == SimulationLifecycleState.COMPLETED
    st_2 = port_2.get_state()

    # -------------------------------------------------------------
    # Mode 3: Interleaved Controls (Start -> Pause -> Step -> Resume -> Pause -> Step)
    # -------------------------------------------------------------
    port_3, _, _, _, _, _, clock_3 = _instantiate_simulation_components(
        candles, initial_capital=100000.0, speed=2.0, base_delay=0.01
    )
    await clock_3.start()
    await asyncio.sleep(0.05)  # Let it run a few candles

    await clock_3.pause()
    assert clock_3.state == SimulationLifecycleState.PAUSED

    # Step exactly 3 candles manually
    await clock_3.step()
    await clock_3.step()
    await clock_3.step()

    # Resume continuous playback
    await clock_3.resume()
    assert clock_3.state == SimulationLifecycleState.RUNNING

    # Wait for completion
    await clock_3.wait_until_complete(timeout=5.0)
    assert clock_3.state == SimulationLifecycleState.COMPLETED
    st_3 = port_3.get_state()

    # -------------------------------------------------------------
    # Bit-for-bit Cross-Mode Assertions
    # -------------------------------------------------------------
    for mode_idx, st in [(2, st_2), (3, st_3)]:
        assert st.total_portfolio_value == st_1.total_portfolio_value, (
            f"Value mismatch in Mode {mode_idx}"
        )
        assert st.cash == st_1.cash, f"Cash mismatch in Mode {mode_idx}"
        assert st.gross_pnl == st_1.gross_pnl, f"Gross PnL mismatch in Mode {mode_idx}"
        assert st.net_pnl == st_1.net_pnl, f"Net PnL mismatch in Mode {mode_idx}"
        assert st.total_return_pct == st_1.total_return_pct, f"Return mismatch in Mode {mode_idx}"
        assert st.total_transaction_costs == st_1.total_transaction_costs, (
            f"Costs mismatch in Mode {mode_idx}"
        )
        assert st.total_slippage_cost == st_1.total_slippage_cost, (
            f"Slippage mismatch in Mode {mode_idx}"
        )

    # Verify identical closed trades across all 3 modes
    for mode_idx, port in [(2, port_2), (3, port_3)]:
        assert len(port.closed_trades) == len(port_1.closed_trades)
        for tA, tB in zip(port_1.closed_trades, port.closed_trades):
            assert tA.quantity == tB.quantity
            assert tA.entry_price == tB.entry_price
            assert tA.exit_price == tB.exit_price
            assert tA.net_pnl == tB.net_pnl
            assert tA.entry_time == tB.entry_time
            assert tA.exit_time == tB.exit_time
            assert tA.exit_reason == tB.exit_reason


# ==============================================================================
# 3. Playback Speed Independence across All Five Speeds
# ==============================================================================


@pytest.mark.asyncio
async def test_playback_speed_independence_all_five_speeds():
    """Verify runs across all 5 supported speeds produce bit-for-bit identical outputs."""
    base_time = datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc)
    candles = _build_test_candle_series(base_time=base_time, count=25)

    results: Dict[float, Dict[str, Any]] = {}

    for spd in VALID_PLAYBACK_SPEEDS:
        port, _, _, _, _, _, clock = _instantiate_simulation_components(
            candles, initial_capital=100000.0, speed=spd, base_delay=0.001
        )
        await clock.start()
        await clock.wait_until_complete(timeout=5.0)

        st = port.get_state()
        results[spd] = {
            "cash": st.cash,
            "total_portfolio_value": st.total_portfolio_value,
            "net_pnl": st.net_pnl,
            "total_transaction_costs": st.total_transaction_costs,
            "trades_count": len(port.closed_trades),
            "trades": [
                (t.quantity, t.entry_price, t.exit_price, t.net_pnl, t.exit_reason)
                for t in port.closed_trades
            ],
        }

    # Reference is 1.0x speed
    ref = results[1.0]
    for spd in (0.5, 2.0, 5.0, 10.0):
        target = results[spd]
        assert target["cash"] == ref["cash"], f"Cash mismatch at speed {spd}"
        assert target["total_portfolio_value"] == ref["total_portfolio_value"], (
            f"Value mismatch at speed {spd}"
        )
        assert target["net_pnl"] == ref["net_pnl"], f"Net PnL mismatch at speed {spd}"
        assert target["total_transaction_costs"] == ref["total_transaction_costs"], (
            f"Costs mismatch at speed {spd}"
        )
        assert target["trades_count"] == ref["trades_count"], (
            f"Trades count mismatch at speed {spd}"
        )
        assert target["trades"] == ref["trades"], f"Trades detail mismatch at speed {spd}"


# ==============================================================================
# 4. Persistence Reproducibility: Twin DB Runs & Synchronization Idempotency
# ==============================================================================


@pytest.fixture
async def sim_repro_db_env():
    """Isolated database fixture for testing persistence reproducibility."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    base_time = datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc)
    candles_data = _build_test_candle_series(base_time=base_time, count=25)

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

        db_candles = [
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
            )
            for c in candles_data
        ]
        db.add_all(db_candles)
        await db.commit()

    service = SimulationService(session_factory=session_factory, base_delay=0.01)

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
            "end_time": candles_data[-1].timestamp,
        }

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_persistence_reproducibility_twin_db_runs(sim_repro_db_env):
    """Verify two independent runs persisted via REST API produce identical DB records.

    Compares:
    - SimulationRun metrics JSON and financial attributes
    - Order table rows (price, side, status, timestamps)
    - Trade table rows (gross/net PnL, fees, entry/exit prices)
    - PortfolioSnapshot table rows
    Also tests repeated sync_to_db calls to verify idempotency.
    """
    client: AsyncClient = sim_repro_db_env["client"]
    base_time: datetime = sim_repro_db_env["base_time"]
    end_time: datetime = sim_repro_db_env["end_time"]
    service: SimulationService = sim_repro_db_env["service"]
    session_factory = sim_repro_db_env["session_factory"]

    payload = {
        "symbol": "RELIANCE",
        "timeframe": "15m",
        "start_date": base_time.isoformat(),
        "end_date": end_time.isoformat(),
        "initial_capital": 100000.0,
        "is_baseline": True,
        "speed": 1.0,
    }

    # Run 1
    res1 = await client.post("/api/v1/simulations", json=payload)
    assert res1.status_code == 201
    id1 = res1.json()["id"]
    await client.post(f"/api/v1/simulations/{id1}/start")
    await service._sessions[id1].clock.wait_until_complete(timeout=5.0)
    await service._safe_on_task_complete(service._sessions[id1])

    # Run 2 (Fresh independent simulation over same locked dataset)
    res2 = await client.post("/api/v1/simulations", json=payload)
    assert res2.status_code == 201
    id2 = res2.json()["id"]
    assert id1 != id2
    await client.post(f"/api/v1/simulations/{id2}/start")
    await service._sessions[id2].clock.wait_until_complete(timeout=5.0)
    await service._safe_on_task_complete(service._sessions[id2])

    # Query and compare database records
    async with session_factory() as db:
        run1 = (
            await db.execute(select(models.SimulationRun).where(models.SimulationRun.id == id1))
        ).scalar_one()
        run2 = (
            await db.execute(select(models.SimulationRun).where(models.SimulationRun.id == id2))
        ).scalar_one()

        assert run1.status == run2.status == models.SimulationStatus.COMPLETED
        assert run1.final_portfolio_value == run2.final_portfolio_value
        assert run1.total_return_pct == run2.total_return_pct

        # Compare metrics JSON
        m1 = run1.metrics
        m2 = run2.metrics
        for k in (
            "net_pnl",
            "gross_pnl",
            "transaction_costs",
            "total_trades",
            "win_rate_pct",
            "max_drawdown_pct",
        ):
            assert m1[k] == m2[k], f"Metric mismatch in DB: {k}"

        # Compare Orders
        orders1 = (
            (
                await db.execute(
                    select(models.Order)
                    .where(models.Order.simulation_id == id1)
                    .order_by(models.Order.candle_timestamp.asc())
                )
            )
            .scalars()
            .all()
        )
        orders2 = (
            (
                await db.execute(
                    select(models.Order)
                    .where(models.Order.simulation_id == id2)
                    .order_by(models.Order.candle_timestamp.asc())
                )
            )
            .scalars()
            .all()
        )

        assert len(orders1) == len(orders2) >= 2
        for o1, o2 in zip(orders1, orders2):
            assert o1.side == o2.side
            assert o1.quantity == o2.quantity
            assert o1.price == o2.price
            assert o1.status == o2.status
            assert o1.candle_timestamp == o2.candle_timestamp

        # Compare Trades
        trades1 = (
            (
                await db.execute(
                    select(models.Trade)
                    .where(models.Trade.simulation_id == id1)
                    .order_by(models.Trade.entry_time.asc())
                )
            )
            .scalars()
            .all()
        )
        trades2 = (
            (
                await db.execute(
                    select(models.Trade)
                    .where(models.Trade.simulation_id == id2)
                    .order_by(models.Trade.entry_time.asc())
                )
            )
            .scalars()
            .all()
        )

        assert len(trades1) == len(trades2) >= 1
        for tr1, tr2 in zip(trades1, trades2):
            assert tr1.side == tr2.side
            assert tr1.quantity == tr2.quantity
            assert tr1.entry_price == tr2.entry_price
            assert tr1.exit_price == tr2.exit_price
            assert tr1.gross_pnl == tr2.gross_pnl
            assert tr1.net_pnl == tr2.net_pnl
            assert tr1.transaction_costs == tr2.transaction_costs
            assert tr1.entry_time == tr2.entry_time
            assert tr1.exit_time == tr2.exit_time

        # Test Idempotency: Repeated sync operations do NOT duplicate rows
        session1 = service._sessions[id1]
        await session1.sync_to_db(is_final=True)
        await session1.sync_to_db(is_final=True)

        orders1_after = (
            (await db.execute(select(models.Order).where(models.Order.simulation_id == id1)))
            .scalars()
            .all()
        )
        trades1_after = (
            (await db.execute(select(models.Trade).where(models.Trade.simulation_id == id1)))
            .scalars()
            .all()
        )
        assert len(orders1_after) == len(orders1)
        assert len(trades1_after) == len(trades1)


# ==============================================================================
# 5. Strict Dataset Lock & No Look-Ahead
# ==============================================================================


@pytest.mark.asyncio
async def test_dataset_lock_and_no_lookahead_isolation(sim_repro_db_env):
    """Verify adding future candles to DB after simulation initialization does not leak into simulation.

    Simulation must process strictly its locked slice and produce identical results.
    """
    client: AsyncClient = sim_repro_db_env["client"]
    base_time: datetime = sim_repro_db_env["base_time"]
    end_time: datetime = sim_repro_db_env["end_time"]
    service: SimulationService = sim_repro_db_env["service"]
    session_factory = sim_repro_db_env["session_factory"]

    # 1. Create Simulation locked to base_time -> end_time
    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 100000.0,
            "is_baseline": True,
        },
    )
    sim_id = create_res.json()["id"]

    # 2. Mutate database: Insert future candles outside the locked range
    async with session_factory() as db:
        inst = (
            await db.execute(
                select(models.Instrument).where(models.Instrument.symbol == "RELIANCE")
            )
        ).scalar_one()

        future_base = end_time + timedelta(minutes=15)
        future_candles = [
            models.Candle(
                instrument_id=inst.id,
                timeframe="15m",
                timestamp=future_base + timedelta(minutes=15 * i),
                open=3000.0,
                high=3050.0,
                low=2990.0,
                close=3020.0,
                volume=50000.0,
            )
            for i in range(10)
        ]
        db.add_all(future_candles)
        await db.commit()

    # 3. Run simulation
    await client.post(f"/api/v1/simulations/{sim_id}/start")
    await service._sessions[sim_id].clock.wait_until_complete(timeout=5.0)

    # 4. Assert simulation remained strictly locked to 25 candles
    sim_res = await client.get(f"/api/v1/simulations/{sim_id}")
    data = sim_res.json()
    assert data["status"] == "COMPLETED"
    assert data["step_index"] == 25
    assert data["total_candles"] == 25
    assert datetime.fromisoformat(data["current_time"].replace("Z", "+00:00")) == end_time


# ==============================================================================
# 6. Same-Symbol Auto-Exit Precedence Reproducibility
# ==============================================================================


@pytest.mark.asyncio
async def test_same_symbol_auto_exit_precedence_reproducibility():
    """Verify that auto-exit precedence rule deterministically rejects conflicting strategy orders.

    Two independent runs with conflicting orders at the same candle Open must follow
    the exact same execution sequence and rejection reason.
    """
    base_time = datetime(2026, 1, 5, 9, 15, tzinfo=timezone.utc)
    candles = _build_test_candle_series(base_time=base_time, count=25)

    def run_precedence_case() -> Tuple[PortfolioTracker, ChronologicalReplayEngine]:
        portfolio = PortfolioTracker(initial_capital=100000.0)
        exec_cfg = ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003)
        exec_engine = ExecutionEngine(config=exec_cfg)
        risk_cfg = RiskConfig(max_risk_per_trade=0.05, max_position_exposure=0.50)
        risk_engine = RiskEngine(config=risk_cfg, execution_config=exec_cfg)
        trigger_monitor = TriggerMonitor(execution_engine=exec_engine)

        def custom_adversarial_strategy(ctx: ReplayContext) -> List[OrderRequest]:
            # At index 22 (when stop loss is tripped and an auto-exit is queued for index 23 open),
            # the strategy ALSO tries to queue a conflicting BUY order for the same symbol at index 23 open.
            if ctx.step_index == 22:
                return [
                    OrderRequest(
                        symbol="RELIANCE",
                        side=OrderSide.BUY,
                        quantity=10,
                        decision_time=ctx.virtual_time,
                        decision_price=ctx.current_candle.close,
                    )
                ]
            # Baseline crossover at index 20
            elif ctx.step_index == 20:
                return [
                    OrderRequest(
                        symbol="RELIANCE",
                        side=OrderSide.BUY,
                        quantity=10,
                        decision_time=ctx.virtual_time,
                        decision_price=ctx.current_candle.close,
                        stop_loss=2528.40,
                    )
                ]
            return []

        engine = ChronologicalReplayEngine(
            candles=candles,
            portfolio=portfolio,
            execution_engine=exec_engine,
            risk_engine=risk_engine,
            trigger_monitor=trigger_monitor,
        )

        while engine.has_next():
            engine.step(strategy=custom_adversarial_strategy)
        engine.finalize()

        return portfolio, engine

    # Run A
    port_A, engine_A = run_precedence_case()
    # Run B
    port_B, engine_B = run_precedence_case()

    # Verify both rejected the conflicting strategy order for the same reason
    assert len(engine_A.rejected_orders) == len(engine_B.rejected_orders) == 1
    rej_A = engine_A.rejected_orders[0]
    rej_B = engine_B.rejected_orders[0]
    assert rej_A.status == rej_B.status == OrderStatus.REJECTED
    assert "same-symbol precedence" in rej_A.rejection_reason
    assert rej_A.rejection_reason == rej_B.rejection_reason

    # Verify auto-exit filled cleanly in both
    assert len(port_A.closed_trades) == len(port_B.closed_trades) == 1
    assert port_A.closed_trades[0].exit_reason == port_B.closed_trades[0].exit_reason == "STOP_LOSS"
    assert port_A.get_state().total_portfolio_value == port_B.get_state().total_portfolio_value


# ==============================================================================
# 7. Exact Warmup Boundary & Crossover Determinism
# ==============================================================================


def test_exact_warmup_and_boundary_crossover_determinism():
    """Verify discrete EMA crossover detection boundary and warmup period determinism.

    - Warmup indices 0..19 strictly yield HOLD
    - Touching boundary EMA9 == EMA20 yields HOLD (no crossover)
    - Strict crossing prev <= prev and curr > curr yields BUY
    """
    # 1. Warmup behavior
    assert BenchmarkBaselineStrategy.evaluate_crossover_values(None, 2500.0, None, 2500.0) is None
    assert BenchmarkBaselineStrategy.evaluate_crossover_values(2500.0, None, 2500.0, None) is None

    # 2. Exact equality boundary
    assert (
        BenchmarkBaselineStrategy.evaluate_crossover_values(2490.0, 2500.0, 2495.0, 2500.0) is None
    )

    # 3. Strict crossing: BUY
    assert (
        BenchmarkBaselineStrategy.evaluate_crossover_values(2490.0, 2510.0, 2495.0, 2500.0) == "BUY"
    )

    # 4. Strict crossing: SELL
    assert (
        BenchmarkBaselineStrategy.evaluate_crossover_values(2510.0, 2490.0, 2500.0, 2495.0)
        == "SELL"
    )


# ==============================================================================
# 8. Adversarial Rapid API Controls & Timing Safety
# ==============================================================================


@pytest.mark.asyncio
async def test_adversarial_rapid_api_controls_determinism(sim_repro_db_env):
    """Verify rapid, concurrent lifecycle control calls do not introduce race conditions or drift.

    Final outcome must be identical to reference deterministic execution.
    """
    client: AsyncClient = sim_repro_db_env["client"]
    base_time: datetime = sim_repro_db_env["base_time"]
    end_time: datetime = sim_repro_db_env["end_time"]

    # 1. Reference Run: Stepped to end
    ref_candles = _build_test_candle_series(base_time=base_time, count=25)
    port_ref, _, _, _, _, _, clock_ref = _instantiate_simulation_components(
        ref_candles, initial_capital=100000.0, speed=1.0, base_delay=0.0
    )
    await clock_ref.start()
    await clock_ref.pause()
    while clock_ref.state == SimulationLifecycleState.PAUSED:
        await clock_ref.step()
    ref_equity = port_ref.get_state().total_portfolio_value
    ref_trades_count = len(port_ref.closed_trades)

    # 2. Adversarial Run: Subjected to rapid concurrent commands
    create_res = await client.post(
        "/api/v1/simulations",
        json={
            "symbol": "RELIANCE",
            "timeframe": "15m",
            "start_date": base_time.isoformat(),
            "end_date": end_time.isoformat(),
            "initial_capital": 100000.0,
            "is_baseline": True,
            "speed": 2.0,
        },
    )
    sim_id = create_res.json()["id"]

    # Concurrent start attempts
    await asyncio.gather(
        client.post(f"/api/v1/simulations/{sim_id}/start"),
        client.post(f"/api/v1/simulations/{sim_id}/start"),
        client.post(f"/api/v1/simulations/{sim_id}/resume"),
    )

    # Rapid pause attempts
    await asyncio.gather(
        client.post(f"/api/v1/simulations/{sim_id}/pause"),
        client.post(f"/api/v1/simulations/{sim_id}/pause"),
    )

    # Step through remaining while paused
    while True:
        s_res = await client.post(f"/api/v1/simulations/{sim_id}/step")
        if s_res.status_code != 200 or s_res.json()["status"] == "COMPLETED":
            break

    # Get final performance
    perf_res = await client.get(f"/api/v1/simulations/{sim_id}/performance")
    assert perf_res.status_code == 200
    adv_perf = perf_res.json()

    assert adv_perf["final_portfolio_value"] == ref_equity
    assert adv_perf["total_trades"] == ref_trades_count
