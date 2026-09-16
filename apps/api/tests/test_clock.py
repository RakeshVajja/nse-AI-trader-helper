"""Unit and integration tests for Simulation Clock & Playback Controller (Phase 6B).

Verifies all frozen Phase 6B requirements:
1. Lifecycle transitions (CREATED -> RUNNING -> PAUSED -> RUNNING -> COMPLETED, STOPPED terminal).
2. Idempotent control operations (START on RUNNING, RESUME on RUNNING, PAUSE on PAUSED).
3. Rejection of invalid operations on terminal states (STOPPED, COMPLETED).
4. STEP valid only while PAUSED; advances exactly one candle and remains PAUSED.
5. Continuous playback reaches COMPLETED when series is exhausted.
6. PAUSE prevents further advancement cleanly.
7. RESUME continues from the exact next chronological candle.
8. STOP cleanly terminates playback and prevents future advancement.
9. No duplicate background tasks created by concurrent or repeated START/RESUME.
10. Playback speed alters pacing delay only, never simulation state or results.
11. Continuous vs stepped execution produces bit-for-bit identical results.
12. Different playback speeds produce bit-for-bit identical results.
13. Virtual simulation timestamps derive strictly from candle stream (never datetime.now()).
14. Control interleaving never causes duplicate candle processing or state corruption.
15. Final-candle handling transitions cleanly to COMPLETED.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import List

import pytest

from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.schemas import (
    ExecutionConfig,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from app.trading.simulation.clock import (
    VALID_PLAYBACK_SPEEDS,
    InvalidStateTransitionError,
    SimulationClock,
    SimulationClockStatus,
    SimulationLifecycleState,
)
from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    ReplayContext,
)


def _make_candle(
    timestamp: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float = 1000.0,
    symbol: str = "RELIANCE",
) -> CandleData:
    """Helper to construct a CandleData instance."""
    candle = CandleData(
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
    )
    object.__setattr__(candle, "symbol", symbol)
    return candle


def _build_test_candles(
    count: int = 5, start_hour: int = 9, symbol: str = "RELIANCE"
) -> List[CandleData]:
    """Helper to generate a sequence of valid 15-minute test candles."""
    candles: List[CandleData] = []
    base_price = 2000.0
    for i in range(count):
        minute = (i * 15) % 60
        hour = start_hour + (i * 15) // 60
        ts = datetime(2026, 1, 15, hour, minute, tzinfo=timezone.utc)
        c = _make_candle(
            timestamp=ts,
            open_price=base_price + (i * 10.0),
            high_price=base_price + (i * 10.0) + 15.0,
            low_price=base_price + (i * 10.0) - 5.0,
            close_price=base_price + (i * 10.0) + 8.0,
            volume=1500.0,
            symbol=symbol,
        )
        candles.append(c)
    return candles


# ==============================================================================
# 1. Lifecycle Transitions & State Reporting
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_initial_state_and_status_reporting():
    """Verify initial state is CREATED with correct status snapshot."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.01)

    assert clock.state == SimulationLifecycleState.CREATED
    assert clock.speed == 1.0
    assert clock.total_candles == 3
    assert clock.current_step == 0
    assert clock.current_time is None
    assert clock.progress_pct == 0.0
    assert not clock.is_running
    assert not clock.is_paused
    assert not clock.is_stopped
    assert not clock.is_completed
    assert not clock.is_terminal

    status = clock.get_status()
    assert isinstance(status, SimulationClockStatus)
    assert status.state == SimulationLifecycleState.CREATED
    assert status.total_candles == 3
    assert status.step_index == 0


@pytest.mark.asyncio
async def test_clock_full_lifecycle_created_running_paused_running_completed():
    """Verify standard lifecycle transitions: CREATED -> RUNNING -> PAUSED -> RUNNING -> COMPLETED."""
    candles = _build_test_candles(count=4)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    # Use 0.05s delay so we can cleanly pause mid-run
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.05)

    assert clock.state == SimulationLifecycleState.CREATED

    # 1. CREATED -> RUNNING
    await clock.start()
    assert clock.state == SimulationLifecycleState.RUNNING
    assert clock.is_running

    # Let it process at least 1 candle
    await asyncio.sleep(0.06)

    # 2. RUNNING -> PAUSED
    await clock.pause()
    assert clock.state == SimulationLifecycleState.PAUSED
    assert clock.is_paused
    assert not clock.is_running
    paused_step = clock.current_step
    assert 1 <= paused_step < 4

    # 3. PAUSED -> RUNNING
    await clock.resume()
    assert clock.state == SimulationLifecycleState.RUNNING

    # 4. RUNNING -> COMPLETED
    summary = await clock.wait_until_complete(timeout=2.0)
    assert clock.state == SimulationLifecycleState.COMPLETED
    assert clock.is_completed
    assert clock.is_terminal
    assert summary.total_steps == 4
    assert clock.progress_pct == 100.0


@pytest.mark.asyncio
async def test_clock_running_or_paused_to_stopped():
    """Verify STOPPED transition from both RUNNING and PAUSED, and verify it is terminal."""
    # From RUNNING to STOPPED
    candles = _build_test_candles(count=4)
    engine1 = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock1 = SimulationClock(engine1, speed=1.0, base_delay=0.05)

    await clock1.start()
    assert clock1.state == SimulationLifecycleState.RUNNING
    summary1 = await clock1.stop()
    assert clock1.state == SimulationLifecycleState.STOPPED
    assert clock1.is_stopped
    assert clock1.is_terminal
    assert summary1 is not None

    # From PAUSED to STOPPED
    engine2 = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock2 = SimulationClock(engine2, speed=1.0, base_delay=0.05)

    await clock2.start()
    await clock2.pause()
    assert clock2.state == SimulationLifecycleState.PAUSED
    summary2 = await clock2.stop()
    assert clock2.state == SimulationLifecycleState.STOPPED
    assert clock2.is_stopped
    assert clock2.is_terminal
    assert summary2 is not None


# ==============================================================================
# 2. Control Idempotency & Safety
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_idempotent_controls():
    """Verify START on RUNNING, RESUME on RUNNING, PAUSE on PAUSED, and STOP on STOPPED are no-ops."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.05)

    await clock.start()
    initial_task = clock._task
    assert initial_task is not None

    # START on RUNNING is idempotent
    await clock.start()
    assert clock.state == SimulationLifecycleState.RUNNING
    assert clock._task is initial_task  # No duplicate task

    # RESUME on RUNNING is idempotent
    await clock.resume()
    assert clock.state == SimulationLifecycleState.RUNNING
    assert clock._task is initial_task

    # PAUSE -> PAUSED
    await clock.pause()
    assert clock.state == SimulationLifecycleState.PAUSED

    # PAUSE on PAUSED is idempotent
    await clock.pause()
    assert clock.state == SimulationLifecycleState.PAUSED

    # STOP -> STOPPED
    await clock.stop()
    assert clock.state == SimulationLifecycleState.STOPPED

    # STOP on STOPPED is idempotent
    summary = await clock.stop()
    assert clock.state == SimulationLifecycleState.STOPPED
    assert summary is not None


# ==============================================================================
# 3. Invalid Operations on Terminal & Incompatible States
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_terminal_state_operations_rejected():
    """Verify START, RESUME, PAUSE, STEP on terminal states (STOPPED, COMPLETED) raise InvalidStateTransitionError."""
    candles = _build_test_candles(count=2)

    # 1. Terminal state: STOPPED
    engine1 = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock1 = SimulationClock(engine1, speed=1.0, base_delay=0.01)
    await clock1.start()
    await clock1.stop()
    assert clock1.state == SimulationLifecycleState.STOPPED

    with pytest.raises(InvalidStateTransitionError, match="terminal state STOPPED"):
        await clock1.start()

    with pytest.raises(InvalidStateTransitionError, match="terminal state STOPPED"):
        await clock1.resume()

    with pytest.raises(InvalidStateTransitionError, match="terminal state STOPPED"):
        await clock1.pause()

    with pytest.raises(InvalidStateTransitionError, match="STEP is valid only while PAUSED"):
        await clock1.step()

    # 2. Terminal state: COMPLETED
    engine2 = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock2 = SimulationClock(engine2, speed=1.0, base_delay=0.0)
    await clock2.start()
    await clock2.wait_until_complete()
    assert clock2.state == SimulationLifecycleState.COMPLETED

    with pytest.raises(InvalidStateTransitionError, match="terminal state COMPLETED"):
        await clock2.start()

    with pytest.raises(InvalidStateTransitionError, match="terminal state COMPLETED"):
        await clock2.resume()

    with pytest.raises(InvalidStateTransitionError, match="terminal state COMPLETED"):
        await clock2.pause()

    with pytest.raises(InvalidStateTransitionError, match="STEP is valid only while PAUSED"):
        await clock2.step()


@pytest.mark.asyncio
async def test_clock_incompatible_created_and_paused_transitions():
    """Verify RESUME and PAUSE on CREATED, and START on PAUSED, raise InvalidStateTransitionError."""
    candles = _build_test_candles(count=2)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.05)

    # On CREATED:
    with pytest.raises(
        InvalidStateTransitionError, match="Cannot pause simulation in CREATED state"
    ):
        await clock.pause()

    with pytest.raises(
        InvalidStateTransitionError, match="Cannot resume simulation in CREATED state"
    ):
        await clock.resume()

    with pytest.raises(InvalidStateTransitionError, match="STEP is valid only while PAUSED"):
        await clock.step()

    # Move to PAUSED via start -> pause
    await clock.start()
    await clock.pause()
    assert clock.state == SimulationLifecycleState.PAUSED

    # On PAUSED: start() is rejected (must use resume())
    with pytest.raises(InvalidStateTransitionError, match="Simulation is paused. Use resume()"):
        await clock.start()


# ==============================================================================
# 4. STEP Control Invariants
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_step_only_while_paused():
    """Verify STEP is strictly forbidden while RUNNING or CREATED."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.05)

    # In CREATED
    with pytest.raises(InvalidStateTransitionError, match="STEP is valid only while PAUSED"):
        await clock.step()

    # In RUNNING
    await clock.start()
    with pytest.raises(InvalidStateTransitionError, match="STEP is valid only while PAUSED"):
        await clock.step()

    # Pause -> now STEP is valid
    await clock.pause()
    assert clock.state == SimulationLifecycleState.PAUSED
    res = await clock.step()
    assert res is not None
    assert clock.state == SimulationLifecycleState.PAUSED  # Still PAUSED


@pytest.mark.asyncio
async def test_clock_step_advances_exactly_one_candle_and_remains_paused():
    """Verify STEP advances exactly one candle cycle per call and remains PAUSED."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.0)

    # Start and immediately pause
    await clock.start()
    await clock.pause()

    initial_step = clock.current_step

    # Step 1
    res1 = await clock.step()
    assert res1 is not None
    assert clock.current_step == initial_step + 1
    assert clock.state == SimulationLifecycleState.PAUSED

    # Step 2
    res2 = await clock.step()
    assert res2 is not None
    assert clock.current_step == initial_step + 2
    # If this was the final candle, it transitions to COMPLETED
    if clock.current_step == clock.total_candles:
        assert clock.state == SimulationLifecycleState.COMPLETED
    else:
        assert clock.state == SimulationLifecycleState.PAUSED


# ==============================================================================
# 5. Continuous Playback & Task Lifecycle
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_continuous_playback_reaches_completed_and_cleans_up_task():
    """Verify continuous playback processes all candles, reaches COMPLETED, and cleans up the background task."""
    candles = _build_test_candles(count=5)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=5.0, base_delay=0.01)

    step_events: List[int] = []

    def on_step(res):
        step_events.append(res.step_index)

    clock.on_step = on_step

    await clock.start()
    assert clock.is_running
    assert clock._task is not None

    summary = await clock.wait_until_complete(timeout=2.0)
    assert clock.state == SimulationLifecycleState.COMPLETED
    assert clock.is_completed
    assert clock._task is None  # Cleaned up in finally block
    assert clock.current_step == 5
    assert len(step_events) == 5
    assert summary.total_steps == 5


@pytest.mark.asyncio
async def test_clock_no_duplicate_background_tasks():
    """Verify concurrent or rapid start/resume calls never create duplicate tasks."""
    candles = _build_test_candles(count=5)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.05)

    # Call start multiple times concurrently
    await asyncio.gather(
        clock.start(),
        clock.start(),
        clock.start(),
    )
    task1 = clock._task
    assert task1 is not None
    assert clock.is_running

    await asyncio.sleep(0.02)
    # Call resume concurrently while running
    await asyncio.gather(
        clock.resume(),
        clock.resume(),
    )
    assert clock._task is task1  # Exact same task

    await clock.stop()


# ==============================================================================
# 6. Pause & Resume Semantics
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_pause_actually_halts_advancement():
    """Verify that after pause(), no further candles are processed."""
    candles = _build_test_candles(count=10)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.04)

    await clock.start()
    await asyncio.sleep(0.09)  # Process ~2 candles
    await clock.pause()

    step_after_pause = clock.current_step
    # Wait additional time: step count must NOT advance
    await asyncio.sleep(0.1)
    assert clock.current_step == step_after_pause
    assert clock.state == SimulationLifecycleState.PAUSED


@pytest.mark.asyncio
async def test_clock_resume_continues_from_exact_next_candle():
    """Verify resume picks up with the exact next chronological candle without skipping or duplicating."""
    candles = _build_test_candles(count=6)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=2.0, base_delay=0.02)

    processed_timestamps: List[datetime] = []

    def on_step(res):
        processed_timestamps.append(res.timestamp)

    clock.on_step = on_step

    await clock.start()
    await asyncio.sleep(0.03)  # Run partially
    await clock.pause()

    steps_before_resume = len(processed_timestamps)
    assert 1 <= steps_before_resume < 6

    # Resume to completion
    await clock.resume()
    await clock.wait_until_complete(timeout=2.0)

    assert len(processed_timestamps) == 6
    # Verify strict chronological progression without duplicates
    for i in range(len(processed_timestamps) - 1):
        assert processed_timestamps[i] < processed_timestamps[i + 1]
    assert processed_timestamps == [c.timestamp for c in candles]


# ==============================================================================
# 7. Playback Speed & Pacing Independence
# ==============================================================================


def test_clock_speed_configuration_and_validation():
    """Verify supported speeds and rejection of invalid speeds."""
    candles = _build_test_candles(count=2)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=1.0)

    for spd in VALID_PLAYBACK_SPEEDS:
        clock.set_speed(spd)
        assert clock.speed == spd
        assert clock.current_delay == 1.0 / spd

    # Unsupported speeds
    with pytest.raises(ValueError, match="Unsupported playback speed"):
        clock.set_speed(0.0)

    with pytest.raises(ValueError, match="Unsupported playback speed"):
        clock.set_speed(3.0)

    with pytest.raises(ValueError, match="Unsupported playback speed"):
        clock.set_speed(-1.0)


@pytest.mark.asyncio
async def test_clock_speed_regulates_wall_clock_pacing_delay():
    """Verify 2x speed runs approximately twice as fast as 1x speed in wall-clock time."""
    candles = _build_test_candles(count=3)

    # Run at 1.0x with 0.04s delay per candle -> ~0.08s
    engine1 = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock1 = SimulationClock(engine1, speed=1.0, base_delay=0.04)

    t0 = time.perf_counter()
    await clock1.start()
    await clock1.wait_until_complete(timeout=2.0)
    dur1 = time.perf_counter() - t0

    # Run at 2.0x with 0.04s delay per candle (0.02s per candle) -> ~0.04s
    engine2 = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock2 = SimulationClock(engine2, speed=2.0, base_delay=0.04)

    t1 = time.perf_counter()
    await clock2.start()
    await clock2.wait_until_complete(timeout=2.0)
    dur2 = time.perf_counter() - t1

    # 1x should take longer than 2x
    assert dur1 > dur2
    # But simulation states and timestamps must be identical
    assert clock1.total_candles == clock2.total_candles == 3
    assert clock1.current_time == clock2.current_time == candles[-1].timestamp


# ==============================================================================
# 8. Deterministic Equivalence: Continuous vs Stepped vs Speeds
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_continuous_vs_stepped_execution_produces_identical_results():
    """Verify continuous playback vs step-by-step execution produces bit-for-bit identical results."""
    candles = _build_test_candles(count=5)

    def simple_strategy(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 0:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=10,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                    stop_loss=1950.0,
                    take_profit=2050.0,
                )
            ]
        return []

    # Run 1: Continuous asynchronous playback
    exec_config = ExecutionConfig(slippage_pct=0.0005, brokerage_rate=0.0003)
    engine_cont = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        execution_engine=ExecutionEngine(config=exec_config),
        initial_capital=100000.0,
    )
    clock_cont = SimulationClock(engine_cont, strategy=simple_strategy, speed=5.0, base_delay=0.0)
    await clock_cont.start()
    summary_cont = await clock_cont.wait_until_complete(timeout=2.0)

    # Run 2: Step-by-step manual execution while paused
    engine_step = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        execution_engine=ExecutionEngine(config=exec_config),
        initial_capital=100000.0,
    )
    clock_step = SimulationClock(engine_step, strategy=simple_strategy, speed=1.0, base_delay=0.0)
    await clock_step.start()
    await clock_step.pause()  # Move to PAUSED

    while clock_step.state == SimulationLifecycleState.PAUSED:
        await clock_step.step()

    summary_step = engine_step.get_summary()

    # Bit-for-bit equivalence
    assert summary_cont.total_steps == summary_step.total_steps == 5
    assert summary_cont.final_portfolio_state.cash == summary_step.final_portfolio_state.cash
    assert (
        summary_cont.final_portfolio_state.total_portfolio_value
        == summary_step.final_portfolio_state.total_portfolio_value
    )
    assert summary_cont.final_portfolio_state.net_pnl == summary_step.final_portfolio_state.net_pnl
    assert len(summary_cont.executions) == len(summary_step.executions)

    for e1, e2 in zip(summary_cont.executions, summary_step.executions):
        assert e1.status == e2.status
        assert e1.execution_price == e2.execution_price
        assert e1.transaction_cost == e2.transaction_cost
        assert e1.executed_at == e2.executed_at


@pytest.mark.asyncio
async def test_clock_different_speeds_produce_identical_results():
    """Verify runs at 0.5x, 1x, 2x, 5x, 10x produce bit-for-bit identical results."""
    candles = _build_test_candles(count=4)

    def simple_strategy(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 0:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=5,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                )
            ]
        return []

    summaries = []
    for spd in VALID_PLAYBACK_SPEEDS:
        engine = ChronologicalReplayEngine(
            candles=candles,
            symbol="RELIANCE",
            initial_capital=50000.0,
        )
        clock = SimulationClock(engine, strategy=simple_strategy, speed=spd, base_delay=0.0)
        await clock.start()
        summ = await clock.wait_until_complete(timeout=2.0)
        summaries.append(summ)

    base_summary = summaries[0]
    for other in summaries[1:]:
        assert other.total_steps == base_summary.total_steps
        assert other.final_portfolio_state.cash == base_summary.final_portfolio_state.cash
        assert (
            other.final_portfolio_state.total_portfolio_value
            == base_summary.final_portfolio_state.total_portfolio_value
        )
        assert len(other.executions) == len(base_summary.executions)


# ==============================================================================
# 9. Virtual Simulation Clock Authority
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_virtual_simulation_timestamps_remain_candle_derived():
    """Verify clock.current_time reflects historical candle timestamps, never wall-clock time."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.0)

    timestamps_observed: List[datetime] = []

    def on_step(res):
        timestamps_observed.append(clock.current_time)

    clock.on_step = on_step

    await clock.start()
    await clock.wait_until_complete(timeout=1.0)

    assert timestamps_observed == [c.timestamp for c in candles]
    # Timestamp is Jan 15 2026, completely independent of current system time
    assert clock.current_time == candles[-1].timestamp


# ==============================================================================
# 10. Interleaved Control Operations & Idempotency Invariants
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_interleaved_controls_no_duplicate_candle_processing():
    """Verify interleaving start, pause, step, speed changes, resume never processes a candle twice."""
    candles = _build_test_candles(count=12)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.03)

    await clock.start()  # Running
    await asyncio.sleep(0.04)  # ~1 step

    await clock.pause()  # Paused
    p_step1 = clock.current_step
    assert p_step1 < 12

    await clock.step()  # Exactly 1 step while paused
    assert clock.current_step == p_step1 + 1

    clock.set_speed(2.0)  # Change speed while paused
    assert clock.speed == 2.0

    await clock.resume()  # Resume running
    await asyncio.sleep(0.02)

    await clock.pause()  # Pause again while running
    p_step2 = clock.current_step
    assert p_step2 < 12

    await clock.step()  # Step again while paused
    assert clock.current_step == p_step2 + 1

    await clock.resume()  # Resume to completion
    summary = await clock.wait_until_complete(timeout=2.0)

    assert summary.total_steps == 12
    assert clock.state == SimulationLifecycleState.COMPLETED
    # Verify exactly 12 unique completed candles in the engine
    assert len(engine.get_visible_candles()) == 12


# ==============================================================================
# 11. Final Candle Handling & Empty Dataset
# ==============================================================================


@pytest.mark.asyncio
async def test_clock_empty_dataset_handling():
    """Verify empty dataset transitions immediately to COMPLETED without error."""
    engine = ChronologicalReplayEngine(candles=[], symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.0)

    assert clock.total_candles == 0
    await clock.start()
    assert clock.state == SimulationLifecycleState.COMPLETED
    assert clock.is_completed


@pytest.mark.asyncio
async def test_clock_final_candle_completion_behavior():
    """Verify that processing the final candle transitions cleanly to COMPLETED, marks positions, and rejects pending orders."""
    candles = _build_test_candles(count=2)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")

    # Strategy emits BUY on candle 1 (the final candle)
    def strat(ctx: ReplayContext) -> List[OrderRequest]:
        if ctx.step_index == 1:
            return [
                OrderRequest(
                    symbol="RELIANCE",
                    side=OrderSide.BUY,
                    quantity=5,
                    decision_time=ctx.virtual_time,
                    decision_price=ctx.current_candle.close,
                )
            ]
        return []

    clock = SimulationClock(engine=engine, strategy=strat, speed=1.0, base_delay=0.0)

    # Open a position on candle 0
    engine.portfolio.open_or_increase_position(
        "RELIANCE", quantity=10, price=2000.0, stop_loss=1900.0
    )

    await clock.start()
    summary = await clock.wait_until_complete(timeout=2.0)

    assert clock.state == SimulationLifecycleState.COMPLETED
    assert summary.total_steps == 2
    # Open position remains open and marked to market at final candle close
    pos = engine.portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10
    assert pos.current_price == candles[1].close
    # Final candle queued strategy order was rejected because no t+2 candle exists
    assert len(summary.rejected_orders) == 1
    assert summary.rejected_orders[0].status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_clock_reset_behavior():
    """Verify reset() restores clock and engine to initial state."""
    candles = _build_test_candles(count=3)
    engine = ChronologicalReplayEngine(candles=candles, symbol="RELIANCE")
    clock = SimulationClock(engine=engine, speed=1.0, base_delay=0.0)

    await clock.start()
    await clock.wait_until_complete(timeout=1.0)
    assert clock.state == SimulationLifecycleState.COMPLETED

    # Reset clock
    clock.reset()
    assert clock.state == SimulationLifecycleState.CREATED
    assert clock.current_step == 0
    assert clock.current_time is None
    assert not clock.is_completed

    # Can start again
    await clock.start()
    assert clock.is_running
    summary = await clock.wait_until_complete(timeout=1.0)
    assert summary.total_steps == 3
