"""Agent failure handling and auto-pause policy controller (Phase 8E).

Coordinates:
- Bounded retry execution for transient failures
- Failure classification and sanitization
- Scoped failure counters per (simulation_id, agent_id)
- Idempotent duplicate event protection
- Authoritative auto-pause dispatching preventing unguided trading
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple, Union

from app.trading.agent.cycle.engine import AgentDecisionCycle
from app.trading.agent.cycle.schemas import CycleStatus, DecisionCycleResult
from app.trading.agent.mandate.schemas import AgentMandate
from app.trading.agent.memory.schemas import AgentMemory
from app.trading.agent.safety.classifier import classify_cycle_result
from app.trading.agent.safety.schemas import (
    AgentFailureState,
    FailureCategory,
    FailurePolicyConfig,
)
from app.trading.agent.tools import ToolExecutionContext

logger = logging.getLogger(__name__)

PauseCallback = Callable[[Optional[str], str], Union[None, Awaitable[Any]]]


class AgentFailureHandler:
    """Manages failure classification, retry execution, failure state, and auto-pause dispatch."""

    def __init__(
        self,
        config: Optional[FailurePolicyConfig] = None,
        pause_callback: Optional[PauseCallback] = None,
    ) -> None:
        self.config = config or FailurePolicyConfig()
        self.pause_callback = pause_callback
        self._lock = threading.Lock()
        # Tracked failure state keyed by (simulation_id, agent_id)
        self._states: Dict[Tuple[Optional[str], str], AgentFailureState] = {}
        # Idempotency guard: prevents duplicate failure events from incrementing twice
        self._processed_failure_events: Set[Tuple[Optional[str], str, datetime]] = set()

    def get_state(self, agent_id: str, simulation_id: Optional[str] = None) -> AgentFailureState:
        """Retrieve the current immutable failure state for a given agent and simulation."""
        key = (simulation_id, agent_id)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return AgentFailureState(agent_id=agent_id, simulation_id=simulation_id)
            return state

    def is_paused(self, agent_id: str, simulation_id: Optional[str] = None) -> bool:
        """Check whether an agent in a given simulation is currently auto-paused."""
        return self.get_state(agent_id, simulation_id).is_paused

    def resume(self, agent_id: str, simulation_id: Optional[str] = None) -> AgentFailureState:
        """Explicitly resume a paused agent and reset consecutive failure counters."""
        key = (simulation_id, agent_id)
        with self._lock:
            current = self._states.get(key)
            new_state = AgentFailureState(
                agent_id=agent_id,
                simulation_id=simulation_id,
                consecutive_failures=0,
                total_failures=current.total_failures if current else 0,
                last_failure_time=current.last_failure_time if current else None,
                last_failure_category=current.last_failure_category if current else None,
                last_failure_error=current.last_failure_error if current else None,
                is_paused=False,
                pause_reason=None,
                paused_at=None,
            )
            self._states[key] = new_state
            logger.info(
                "Agent '%s' in simulation '%s' resumed successfully.", agent_id, simulation_id
            )
            return new_state

    def reset(
        self,
        agent_id: Optional[str] = None,
        simulation_id: Optional[str] = None,
    ) -> None:
        """Reset failure states and idempotency caches (e.g. between independent test runs)."""
        with self._lock:
            if agent_id is None and simulation_id is None:
                self._states.clear()
                self._processed_failure_events.clear()
            elif agent_id is not None and simulation_id is not None:
                self._states.pop((simulation_id, agent_id), None)
            elif simulation_id is not None:
                keys_to_remove = [k for k in self._states if k[0] == simulation_id]
                for k in keys_to_remove:
                    self._states.pop(k, None)
            elif agent_id is not None:
                keys_to_remove = [k for k in self._states if k[1] == agent_id]
                for k in keys_to_remove:
                    self._states.pop(k, None)

    def record_cycle_result(
        self,
        result: DecisionCycleResult,
        agent_id: Optional[str] = None,
        simulation_id: Optional[str] = None,
    ) -> AgentFailureState:
        """Evaluate a cycle result, update failure counters, and trigger auto-pause if threshold reached."""
        eff_agent_id = agent_id or result.agent_id
        eff_sim_id = simulation_id or result.simulation_id
        category, _, err_msg = classify_cycle_result(result)
        key = (eff_sim_id, eff_agent_id)
        event_key = (eff_sim_id, eff_agent_id, result.candle_timestamp)

        with self._lock:
            current = self._states.get(key)
            tot_fails = current.total_failures if current else 0
            is_paused = current.is_paused if current else False
            pause_reason = current.pause_reason if current else None
            paused_at = current.paused_at if current else None

            # Non-failure outcome: reset consecutive failure count to 0
            if category is None or category == FailureCategory.NONE:
                new_state = AgentFailureState(
                    agent_id=eff_agent_id,
                    simulation_id=eff_sim_id,
                    consecutive_failures=0,
                    total_failures=tot_fails,
                    last_failure_time=current.last_failure_time if current else None,
                    last_failure_category=current.last_failure_category if current else None,
                    last_failure_error=current.last_failure_error if current else None,
                    is_paused=is_paused,
                    pause_reason=pause_reason,
                    paused_at=paused_at,
                )
                self._states[key] = new_state
                return new_state

            # Failure outcome: check duplicate event idempotency
            if event_key in self._processed_failure_events:
                logger.warning(
                    "Duplicate failure event skipped for simulation '%s', agent '%s' at %s",
                    eff_sim_id,
                    eff_agent_id,
                    result.candle_timestamp.isoformat(),
                )
                return current or AgentFailureState(agent_id=eff_agent_id, simulation_id=eff_sim_id)
            self._processed_failure_events.add(event_key)

            new_consec = (current.consecutive_failures if current else 0) + 1
            new_tot = tot_fails + 1
            trigger_pause = False

            if new_consec >= self.config.max_consecutive_failures and not is_paused:
                is_paused = True
                cat_name = category.value if hasattr(category, "value") else str(category)
                pause_reason = (
                    f"Agent paused: consecutive failures reached threshold ({cat_name}: {err_msg})"
                )
                paused_at = result.candle_timestamp
                trigger_pause = True

            new_state = AgentFailureState(
                agent_id=eff_agent_id,
                simulation_id=eff_sim_id,
                consecutive_failures=new_consec,
                total_failures=new_tot,
                last_failure_time=result.candle_timestamp,
                last_failure_category=category,
                last_failure_error=err_msg,
                is_paused=is_paused,
                pause_reason=pause_reason,
                paused_at=paused_at,
            )
            self._states[key] = new_state

        if trigger_pause:
            logger.error(
                "Auto-pause triggered for agent '%s' in simulation '%s': %s",
                eff_agent_id,
                eff_sim_id,
                pause_reason,
            )
            self._dispatch_pause(eff_sim_id, eff_agent_id, pause_reason or "Agent paused")

        return new_state

    def _dispatch_pause(self, simulation_id: Optional[str], agent_id: str, reason: str) -> None:
        """Invoke configured pause callback or simulation pause hook safely without corrupting state."""
        if self.pause_callback is None:
            return
        try:
            try:
                call_res = self.pause_callback(simulation_id, agent_id, reason)
            except TypeError:
                call_res = self.pause_callback(simulation_id, reason)

            if asyncio.iscoroutine(call_res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(call_res)
                except RuntimeError:
                    asyncio.run(call_res)
        except Exception:
            logger.exception(
                "Error executing auto-pause callback for simulation '%s'", simulation_id
            )

    def execute_cycle(
        self,
        cycle: AgentDecisionCycle,
        context: ToolExecutionContext,
        mandate: AgentMandate,
        agent_id: str = "default-agent",
        simulation_id: Optional[str] = None,
        memory: Optional[AgentMemory] = None,
    ) -> DecisionCycleResult:
        """Execute decision cycle through the safety failure handler.

        Flow:
        1. Fast-path check: if agent is auto-paused, immediately return empty/no-action envelope.
        2. Run decision cycle on Phase 8C engine.
        3. Classify cycle outcome.
        4. If failure is transient and retry budget remains, perform bounded backoff retry.
        5. Record final result (increments failure counter, triggers auto-pause if threshold met,
           or resets consecutive failures on success).
        """
        # 1. Fast-path check for paused status
        if self.is_paused(agent_id=agent_id, simulation_id=simulation_id):
            logger.warning(
                "Agent '%s' in simulation '%s' is auto-paused; refusing cycle execution.",
                agent_id,
                simulation_id,
            )
            return DecisionCycleResult(
                cycle_id=f"paused-{int(time.time() * 1000)}",
                agent_id=agent_id,
                simulation_id=simulation_id,
                candle_timestamp=context.virtual_time,
                status=CycleStatus.NO_ACTION,
                orders_staged=[],
                error=f"Agent '{agent_id}' is auto-paused due to prior safety threshold violation.",
            )

        # 2. Primary execution attempt
        res = cycle.run_cycle(
            context=context,
            mandate=mandate,
            agent_id=agent_id,
            simulation_id=simulation_id,
            memory=memory,
        )

        # 3. Classify outcome
        category, is_retryable, _ = classify_cycle_result(res)

        # 4. Perform bounded retry loop if failure is transient
        attempt = 0
        while is_retryable and attempt < self.config.max_retries:
            attempt += 1
            if self.config.initial_backoff_seconds > 0.0:
                backoff = self.config.initial_backoff_seconds * (
                    self.config.backoff_factor ** (attempt - 1)
                )
                time.sleep(backoff)

            # Clear any partial orders staged during the aborted attempt
            if context.staged_orders:
                context.staged_orders.clear()

            # Permit retry by discarding the failed event from cycle's idempotency set
            cycle.remove_processed_event(
                simulation_id=simulation_id,
                agent_id=agent_id,
                candle_ts=context.virtual_time,
            )

            logger.info(
                "Retrying decision cycle for agent '%s' (attempt %d/%d) after %s failure",
                agent_id,
                attempt,
                self.config.max_retries,
                category.value,
            )
            res = cycle.run_cycle(
                context=context,
                mandate=mandate,
                agent_id=agent_id,
                simulation_id=simulation_id,
                memory=memory,
            )
            category, is_retryable, _ = classify_cycle_result(res)
            if category is None or category == FailureCategory.NONE:
                break

        # 5. Record final result (updates consecutive counter and triggers auto-pause if threshold reached)
        self.record_cycle_result(res, agent_id=agent_id, simulation_id=simulation_id)
        return res

    async def execute_cycle_async(
        self,
        cycle: AgentDecisionCycle,
        context: ToolExecutionContext,
        mandate: AgentMandate,
        agent_id: str = "default-agent",
        simulation_id: Optional[str] = None,
        memory: Optional[AgentMemory] = None,
    ) -> DecisionCycleResult:
        """Asynchronous execution parity for safety-governed decision cycles."""
        # 1. Check if agent is currently auto-paused
        if self.is_paused(agent_id, simulation_id):
            state = self.get_state(agent_id, simulation_id)
            logger.warning(
                "Agent '%s' in simulation '%s' is PAUSED; async decision cycle skipped at %s",
                agent_id,
                simulation_id,
                context.virtual_time.isoformat(),
            )
            return DecisionCycleResult(
                cycle_id=str(uuid.uuid4()),
                agent_id=agent_id,
                simulation_id=simulation_id,
                candle_timestamp=context.virtual_time,
                status=CycleStatus.NO_ACTION,
                decision=None,
                reconciliation=None,
                tool_executions=[],
                orders_staged=[],
                error=state.pause_reason or "Agent paused: Gemini decision unavailable.",
            )

        # 2. Run initial async cycle via 8C engine
        res = await cycle.run_cycle_async(
            context=context,
            mandate=mandate,
            agent_id=agent_id,
            simulation_id=simulation_id,
            memory=memory,
        )

        # 3. Classify outcome
        category, is_retryable, _ = classify_cycle_result(res)

        # 4. Perform bounded async retry loop if failure is transient
        attempt = 0
        while is_retryable and attempt < self.config.max_retries:
            attempt += 1
            if self.config.initial_backoff_seconds > 0.0:
                backoff = self.config.initial_backoff_seconds * (
                    self.config.backoff_factor ** (attempt - 1)
                )
                await asyncio.sleep(backoff)

            # Clear any partial orders staged during the aborted attempt
            if context.staged_orders:
                context.staged_orders.clear()

            cycle.remove_processed_event(
                simulation_id=simulation_id,
                agent_id=agent_id,
                candle_ts=context.virtual_time,
            )

            logger.info(
                "Async retrying decision cycle for agent '%s' (attempt %d/%d) after %s failure",
                agent_id,
                attempt,
                self.config.max_retries,
                category.value,
            )
            res = await cycle.run_cycle_async(
                context=context,
                mandate=mandate,
                agent_id=agent_id,
                simulation_id=simulation_id,
                memory=memory,
            )
            category, is_retryable, _ = classify_cycle_result(res)
            if category is None or category == FailureCategory.NONE:
                break

        # 5. Record final result
        self.record_cycle_result(res, agent_id=agent_id, simulation_id=simulation_id)
        return res
