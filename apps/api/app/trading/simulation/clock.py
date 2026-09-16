"""Simulation Clock & Playback Controller (Phase 6B).

Manages the asynchronous execution lifecycle and wall-clock pacing of historical
simulations on top of the ChronologicalReplayEngine.

Frozen Lifecycle:
- CREATED -> RUNNING (via START)
- RUNNING -> PAUSED (via PAUSE)
- PAUSED -> RUNNING (via RESUME)
- RUNNING or PAUSED -> STOPPED (via STOP)
- RUNNING -> COMPLETED (automatically when historical series is exhausted)
- STOPPED is strictly terminal
- COMPLETED is strictly terminal

Key Invariants:
1. Single Replay Engine: ChronologicalReplayEngine remains the sole authority for
   chronological candle stepping, order execution, and portfolio accounting.
2. Single Managed Background Task: Continuous playback uses exactly one asyncio.Task;
   duplicate tasks are strictly prevented.
3. Pacing Independence: Playback speeds (0.5x, 1x, 2x, 5x, 10x) regulate only wall-clock
   asyncio.sleep delays; simulation timestamps, execution prices, and trading results
   are bit-for-bit identical regardless of speed or stepping mode.
4. Idempotency & Safety: START/RESUME on RUNNING is an idempotent no-op; PAUSE on PAUSED
   is an idempotent no-op; STEP is permitted strictly while PAUSED.
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Tuple, Union

from app.trading.simulation.replay import (
    ChronologicalReplayEngine,
    ReplayStepResult,
    ReplaySummary,
    StrategyCallable,
)

logger = logging.getLogger(__name__)


class SimulationLifecycleState(str, enum.Enum):
    """Lifecycle state of a simulation playback session."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


# Supported playback speeds (speed multiplier over base delay)
VALID_PLAYBACK_SPEEDS: Tuple[float, ...] = (0.5, 1.0, 2.0, 5.0, 10.0)


class SimulationClockError(Exception):
    """Base exception for simulation clock and playback controller errors."""


class InvalidStateTransitionError(SimulationClockError, ValueError):
    """Raised when an invalid lifecycle state transition or control command is attempted."""


@dataclass(frozen=True)
class SimulationClockStatus:
    """Read-only snapshot of active simulation clock state for APIs and monitoring."""

    state: SimulationLifecycleState
    current_time: Optional[datetime]
    step_index: int
    total_candles: int
    progress_pct: float
    speed: float
    is_running: bool
    is_paused: bool
    is_completed: bool
    is_terminal: bool


StepCallback = Callable[[ReplayStepResult], Union[None, Awaitable[Any]]]


class SimulationClock:
    """Simulation clock and playback controller (Phase 6B).

    Wraps a ChronologicalReplayEngine to provide asynchronous playback execution,
    lifecycle state machine transitions, wall-clock pacing regulation, and
    step-by-step control.
    """

    def __init__(
        self,
        engine: ChronologicalReplayEngine,
        strategy: Optional[StrategyCallable] = None,
        speed: float = 1.0,
        base_delay: float = 1.0,
        on_step: Optional[StepCallback] = None,
    ) -> None:
        """Initialize the simulation clock controller.

        Args:
            engine: Pre-configured ChronologicalReplayEngine instance.
            strategy: Optional StrategyCallable for trading signal generation.
            speed: Initial playback speed multiplier (default 1.0x).
            base_delay: Wall-clock delay in seconds for 1.0x speed (default 1.0s).
                        For testing, set to 0.0 or a small fraction.
            on_step: Optional callback invoked after each candle step.
        """
        self.engine = engine
        self.strategy = strategy
        self.on_step = on_step

        self._state: SimulationLifecycleState = SimulationLifecycleState.CREATED
        self._speed: float = 1.0
        self.set_speed(speed)

        self._base_delay: float = max(0.0, float(base_delay))
        self._task: Optional[asyncio.Task[None]] = None
        self._control_lock: asyncio.Lock = asyncio.Lock()
        self._step_lock: asyncio.Lock = asyncio.Lock()
        self._last_error: Optional[Exception] = None

    @property
    def state(self) -> SimulationLifecycleState:
        """Current lifecycle state of the simulation."""
        return self._state

    @property
    def speed(self) -> float:
        """Current playback speed multiplier."""
        return self._speed

    @property
    def base_delay(self) -> float:
        """Base wall-clock delay in seconds (for 1.0x speed)."""
        return self._base_delay

    @property
    def current_delay(self) -> float:
        """Wall-clock delay in seconds for the next step based on current speed."""
        if self._base_delay <= 0.0:
            return 0.0
        return self._base_delay / self._speed

    @property
    def current_time(self) -> Optional[datetime]:
        """Current virtual simulation timestamp (derived strictly from candle stream)."""
        return self.engine.current_time

    @property
    def current_step(self) -> int:
        """Number of completed simulation candle steps."""
        return self.engine.current_step

    @property
    def total_candles(self) -> int:
        """Total number of candles loaded in the historical replay series."""
        return self.engine.total_candles

    @property
    def progress_pct(self) -> float:
        """Simulation completion progress as a percentage (0.0 to 100.0)."""
        total = self.total_candles
        if total == 0:
            return 100.0
        return round((self.current_step / total) * 100.0, 2)

    @property
    def is_running(self) -> bool:
        """True if the simulation is actively running in background playback."""
        return self._state == SimulationLifecycleState.RUNNING

    @property
    def is_paused(self) -> bool:
        """True if the simulation is currently paused."""
        return self._state == SimulationLifecycleState.PAUSED

    @property
    def is_stopped(self) -> bool:
        """True if the simulation has been stopped (terminal)."""
        return self._state == SimulationLifecycleState.STOPPED

    @property
    def is_completed(self) -> bool:
        """True if the simulation has completed all candles (terminal)."""
        return self._state == SimulationLifecycleState.COMPLETED

    @property
    def is_terminal(self) -> bool:
        """True if the simulation has reached a terminal state (STOPPED or COMPLETED)."""
        return self._state in (
            SimulationLifecycleState.STOPPED,
            SimulationLifecycleState.COMPLETED,
        )

    def set_speed(self, speed: float) -> None:
        """Set the playback speed multiplier.

        Args:
            speed: Supported multiplier (0.5, 1.0, 2.0, 5.0, 10.0).

        Raises:
            ValueError: If the speed multiplier is not supported.
        """
        speed_f = float(speed)
        if speed_f not in VALID_PLAYBACK_SPEEDS:
            raise ValueError(
                f"Unsupported playback speed: {speed}. Supported speeds are: {VALID_PLAYBACK_SPEEDS}"
            )
        self._speed = speed_f

    def get_status(self) -> SimulationClockStatus:
        """Return a typed snapshot of the current clock and playback state."""
        return SimulationClockStatus(
            state=self._state,
            current_time=self.current_time,
            step_index=self.current_step,
            total_candles=self.total_candles,
            progress_pct=self.progress_pct,
            speed=self._speed,
            is_running=self.is_running,
            is_paused=self.is_paused,
            is_completed=self.is_completed,
            is_terminal=self.is_terminal,
        )

    async def start(self) -> None:
        """Start simulation playback from CREATED state.

        Idempotency:
        - If already RUNNING, performs a no-op without creating duplicate tasks.

        Raises:
            InvalidStateTransitionError: If the simulation is in a terminal state
            (STOPPED, COMPLETED) or is currently PAUSED (use resume() instead).
        """
        async with self._control_lock:
            if self._state == SimulationLifecycleState.RUNNING:
                # Idempotent no-op
                return

            if self._state in (
                SimulationLifecycleState.STOPPED,
                SimulationLifecycleState.COMPLETED,
            ):
                raise InvalidStateTransitionError(
                    f"Cannot start simulation in terminal state {self._state.value}."
                )

            if self._state == SimulationLifecycleState.PAUSED:
                raise InvalidStateTransitionError(
                    "Simulation is paused. Use resume() to continue playback."
                )

            # State is CREATED
            if not self.engine.has_next():
                self.engine.finalize()
                self._state = SimulationLifecycleState.COMPLETED
                return

            self._state = SimulationLifecycleState.RUNNING
            self._task = asyncio.create_task(self._playback_loop())

    async def pause(self) -> None:
        """Pause active simulation playback (RUNNING -> PAUSED).

        Idempotency:
        - If already PAUSED, performs a no-op.

        Raises:
            InvalidStateTransitionError: If called on CREATED or a terminal state.
        """
        async with self._control_lock:
            if self._state == SimulationLifecycleState.PAUSED:
                # Idempotent no-op
                return

            if self._state in (
                SimulationLifecycleState.STOPPED,
                SimulationLifecycleState.COMPLETED,
            ):
                raise InvalidStateTransitionError(
                    f"Cannot pause simulation in terminal state {self._state.value}."
                )

            if self._state == SimulationLifecycleState.CREATED:
                raise InvalidStateTransitionError(
                    "Cannot pause simulation in CREATED state; start simulation first."
                )

            # State is RUNNING: transition to PAUSED and cancel active runner task
            self._state = SimulationLifecycleState.PAUSED
            task = self._task
            self._task = None

            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def resume(self) -> None:
        """Resume playback from PAUSED state (PAUSED -> RUNNING).

        Idempotency:
        - If already RUNNING, performs a no-op.

        Raises:
            InvalidStateTransitionError: If called on CREATED (use start()) or
            a terminal state (STOPPED, COMPLETED).
        """
        async with self._control_lock:
            if self._state == SimulationLifecycleState.RUNNING:
                # Idempotent no-op
                return

            if self._state in (
                SimulationLifecycleState.STOPPED,
                SimulationLifecycleState.COMPLETED,
            ):
                raise InvalidStateTransitionError(
                    f"Cannot resume simulation in terminal state {self._state.value}."
                )

            if self._state == SimulationLifecycleState.CREATED:
                raise InvalidStateTransitionError(
                    "Cannot resume simulation in CREATED state; call start() first."
                )

            # State is PAUSED
            if not self.engine.has_next():
                self.engine.finalize()
                self._state = SimulationLifecycleState.COMPLETED
                return

            self._state = SimulationLifecycleState.RUNNING
            self._task = asyncio.create_task(self._playback_loop())

    async def step(self) -> Optional[ReplayStepResult]:
        """Advance the simulation by exactly one candle cycle while PAUSED.

        The controller advances exactly one candle, invokes callbacks, and
        remains in the PAUSED state (or transitions to COMPLETED if the final
        candle was just processed).

        Raises:
            InvalidStateTransitionError: If called when not in the PAUSED state.
        """
        async with self._control_lock:
            if self._state != SimulationLifecycleState.PAUSED:
                raise InvalidStateTransitionError(
                    f"STEP is valid only while PAUSED. Current state is {self._state.value}."
                )

            async with self._step_lock:
                if not self.engine.has_next():
                    self.engine.finalize()
                    self._state = SimulationLifecycleState.COMPLETED
                    return None

                step_res = self.engine.step(strategy=self.strategy)

                if self.on_step is not None and step_res is not None:
                    cb_res = self.on_step(step_res)
                    if inspect.isawaitable(cb_res):
                        await cb_res

                if not self.engine.has_next():
                    self.engine.finalize()
                    self._state = SimulationLifecycleState.COMPLETED

                return step_res

    async def stop(self) -> ReplaySummary:
        """Stop playback and transition to terminal STOPPED state.

        Terminates the background playback task cleanly, finalizes the underlying
        replay engine (rejecting any in-flight orders), and returns the summary.

        Idempotency:
        - If already STOPPED or COMPLETED, returns the existing summary.
        """
        async with self._control_lock:
            if self._state in (
                SimulationLifecycleState.STOPPED,
                SimulationLifecycleState.COMPLETED,
            ):
                return self.engine.get_summary()

            self._state = SimulationLifecycleState.STOPPED
            task = self._task
            self._task = None

            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            return self.engine.finalize()

    def reset(self) -> None:
        """Reset the clock and underlying replay engine back to initial state.

        Raises:
            SimulationClockError: If called while playback is actively RUNNING.
        """
        if self._state == SimulationLifecycleState.RUNNING:
            raise SimulationClockError(
                "Cannot reset simulation while it is actively RUNNING. Pause or stop first."
            )

        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None

        self.engine.reset()
        self._state = SimulationLifecycleState.CREATED
        self._last_error = None

    async def wait_until_complete(self, timeout: Optional[float] = None) -> ReplaySummary:
        """Wait until the simulation reaches a terminal state (COMPLETED or STOPPED).

        Args:
            timeout: Maximum wall-clock seconds to wait before raising TimeoutError.

        Returns:
            ReplaySummary upon completion or stopping.
        """
        if self.is_terminal:
            return self.engine.get_summary()

        task = self._task
        if task is not None and not task.done():
            if timeout is not None:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            else:
                await task

        return self.engine.get_summary()

    async def _playback_loop(self) -> None:
        """Continuous asynchronous playback loop executing on the event loop."""
        try:
            while self._state == SimulationLifecycleState.RUNNING:
                step_res: Optional[ReplayStepResult] = None

                async with self._step_lock:
                    if self._state != SimulationLifecycleState.RUNNING:
                        break

                    if not self.engine.has_next():
                        self.engine.finalize()
                        self._state = SimulationLifecycleState.COMPLETED
                        break

                    step_res = self.engine.step(strategy=self.strategy)

                    if not self.engine.has_next():
                        self.engine.finalize()
                        self._state = SimulationLifecycleState.COMPLETED

                # Invoke step callback outside of _step_lock
                if self.on_step is not None and step_res is not None:
                    cb_res = self.on_step(step_res)
                    if inspect.isawaitable(cb_res):
                        await cb_res

                if self._state != SimulationLifecycleState.RUNNING:
                    break

                # Wall-clock pacing delay
                delay = self.current_delay
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(0)  # Yield control to event loop

        except asyncio.CancelledError:
            # Expected when paused or stopped
            pass
        except Exception as exc:
            logger.exception("Unexpected error in simulation playback loop.")
            self._last_error = exc
            self._state = SimulationLifecycleState.STOPPED
            raise
        finally:
            if asyncio.current_task() == self._task:
                self._task = None
