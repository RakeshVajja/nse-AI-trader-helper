"""Event-driven Gemini decision cycle engine (Phase 8C).

Orchestrates:
1. Completed-candle event recognition and idempotent dispatch.
2. Construction of bounded per-cycle prompt from authoritative simulation state at t (no lookahead).
3. Bounded Gemini ↔ Phase 7 tool interaction loop (max_turns).
4. Every tool call dispatched strictly through SafeToolExecutionHarness.
5. Extraction and validation of final structured AgentDecision.
6. Deterministic reconciliation between tool activity and AgentDecision.
7. Clean StrategyCallable adapter for ChronologicalReplayEngine integration.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Set, Tuple

if TYPE_CHECKING:
    from app.trading.agent.safety.handler import AgentFailureHandler

from app.trading.agent.cycle.prompts import build_cycle_prompt, build_system_instruction
from app.trading.agent.cycle.reconciliation import reconcile_decision_with_tools
from app.trading.agent.cycle.schemas import (
    CycleStatus,
    CycleToolExecution,
    DecisionCycleResult,
    DecisionReconciliation,
)
from app.trading.agent.gemini.client import GeminiClient
from app.trading.agent.gemini.schemas import (
    GeminiMessage,
    GeminiRequest,
    GeminiToolResponse,
)
from app.trading.agent.harness import SafeToolExecutionHarness
from app.trading.agent.mandate.schemas import AgentMandate
from app.trading.agent.memory import AgentMemory, AgentMemoryService
from app.trading.agent.schemas import AgentAction, AgentDecision
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderRequest
from app.trading.simulation.replay import ReplayContext, StrategyCallable

logger = logging.getLogger(__name__)


class AgentDecisionCycle:
    """Event-driven orchestrator managing the per-candle Gemini trading decision cycle."""

    def __init__(
        self,
        client: Optional[GeminiClient] = None,
        harness: Optional[SafeToolExecutionHarness] = None,
        max_turns: int = 5,
        memory_service: Optional[AgentMemoryService] = None,
    ) -> None:
        """Initialize the decision cycle orchestrator.

        Args:
            client: GeminiClient instance (uses default if None).
            harness: SafeToolExecutionHarness instance (uses default if None).
            max_turns: Maximum number of model interaction turns per cycle (default 5).
            memory_service: Optional AgentMemoryService for bounded historical context.
        """
        self.client = client or GeminiClient()
        self.harness = harness or SafeToolExecutionHarness()
        self.max_turns = max_turns
        self.memory_service = memory_service
        self._lock = threading.Lock()
        self._processed_events: Set[Tuple[Optional[str], str, datetime]] = set()

    def reset_idempotency_cache(self) -> None:
        """Reset the processed events cache (e.g. between independent simulation runs)."""
        with self._lock:
            self._processed_events.clear()

    def remove_processed_event(
        self,
        simulation_id: Optional[str],
        agent_id: str,
        candle_ts: datetime,
    ) -> None:
        """Remove an event key from processed events cache to permit controlled retry."""
        event_key = (simulation_id, agent_id, candle_ts)
        with self._lock:
            self._processed_events.discard(event_key)

    def run_cycle(
        self,
        context: ToolExecutionContext,
        mandate: AgentMandate,
        agent_id: str = "default-agent",
        simulation_id: Optional[str] = None,
        memory: Optional[AgentMemory] = None,
    ) -> DecisionCycleResult:
        """Execute a synchronous event-driven decision cycle on completed candle t."""
        cycle_id = str(uuid.uuid4())
        candle_ts = context.virtual_time
        event_key = (simulation_id, agent_id, candle_ts)

        # 1. Idempotency check: ensure an event at timestamp t never runs twice
        with self._lock:
            if event_key in self._processed_events:
                logger.warning(
                    "Duplicate event skipped for simulation '%s', agent '%s' at timestamp %s",
                    simulation_id,
                    agent_id,
                    candle_ts.isoformat(),
                )
                return DecisionCycleResult(
                    cycle_id=cycle_id,
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                    candle_timestamp=candle_ts,
                    status=CycleStatus.SKIPPED_DUPLICATE,
                    decision=None,
                    reconciliation=None,
                    tool_executions=[],
                    orders_staged=[],
                    error=f"Duplicate event at {candle_ts.isoformat()} already processed.",
                )
            self._processed_events.add(event_key)

        tool_executions: List[CycleToolExecution] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_latency_ms = 0.0
        turns_count = 0
        final_decision: Optional[AgentDecision] = None
        cycle_error: Optional[str] = None
        cycle_status: CycleStatus = CycleStatus.SUCCESS

        try:
            # 2. Build system instruction and per-cycle prompt (strictly data <= t)
            system_inst = build_system_instruction(mandate)

            # Resolve bounded historical memory if configured
            active_memory = memory
            if active_memory is None and self.memory_service is not None:
                active_memory = self.memory_service.get_memory_from_context(
                    context=context,
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                )

            cycle_prompt = build_cycle_prompt(context, mandate, memory=active_memory)

            messages: List[GeminiMessage] = [GeminiMessage(role="user", content=cycle_prompt)]

            # 3. Bounded Gemini ↔ tool-call loop
            for _ in range(self.max_turns):
                turns_count += 1
                req = GeminiRequest(
                    system_instruction=system_inst,
                    messages=messages,
                    tools_enabled=True,
                    structured_output=True,
                )

                res = self.client.generate(req)
                total_prompt_tokens += res.prompt_tokens
                total_completion_tokens += res.completion_tokens
                total_latency_ms += res.latency_ms

                if not res.success:
                    cycle_error = res.error or "Gemini API error during decision cycle"
                    cycle_status = CycleStatus.GEMINI_ERROR
                    break

                if res.decision is not None:
                    final_decision = res.decision
                    break

                if res.tool_calls:
                    tool_responses: List[GeminiToolResponse] = []
                    for tc in res.tool_calls:
                        t_start = time.perf_counter()
                        tool_res = self.harness.dispatch(
                            tool_name=tc.name,
                            raw_args=tc.args,
                            context=context,
                        )
                        t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

                        staged_id = (
                            tool_res.data.get("order_id")
                            if (tool_res.success and tool_res.data)
                            else None
                        )
                        tool_executions.append(
                            CycleToolExecution(
                                tool_name=tc.name,
                                arguments=tc.args,
                                success=tool_res.success,
                                data=tool_res.data,
                                error=tool_res.error,
                                error_type=str(tool_res.error_type)
                                if tool_res.error_type
                                else None,
                                execution_time_ms=t_elapsed_ms,
                                staged_order_id=staged_id,
                            )
                        )

                        resp_data = (
                            tool_res.data
                            if tool_res.success
                            else {
                                "error": tool_res.error,
                                "error_type": str(tool_res.error_type),
                            }
                        )
                        tool_responses.append(
                            GeminiToolResponse(name=tc.name, response=resp_data or {})
                        )

                    messages.append(GeminiMessage(role="model", tool_calls=res.tool_calls))
                    messages.append(GeminiMessage(role="tool", tool_responses=tool_responses))
                else:
                    cycle_error = "Model generated neither tool calls nor structured AgentDecision."
                    cycle_status = CycleStatus.GEMINI_ERROR
                    break

            # 4. Check for loop bound termination without decision
            if final_decision is None and cycle_status != CycleStatus.GEMINI_ERROR:
                cycle_status = CycleStatus.MAX_TURNS_EXCEEDED
                cycle_error = (
                    f"Agent interaction bound exceeded ({self.max_turns} turns) without decision."
                )

            # 5. Deterministic reconciliation between decision and tools
            reconciliation: Optional[DecisionReconciliation] = None
            if final_decision is not None:
                reconciliation = reconcile_decision_with_tools(
                    decision=final_decision,
                    tool_executions=tool_executions,
                    context=context,
                    mandate=mandate,
                    harness=self.harness,
                )
                if reconciliation.order_staged:
                    cycle_status = (
                        CycleStatus.TOOL_ORDER_STAGED
                        if reconciliation.order_source == "TOOL"
                        else CycleStatus.DECISION_ORDER_STAGED
                    )
                else:
                    cycle_status = (
                        CycleStatus.NO_ACTION
                        if final_decision.action == AgentAction.HOLD
                        else CycleStatus.SUCCESS
                    )

            # 6. Collect staged order IDs for this candle step
            staged_order_ids = [
                o.order_id for o in context.staged_orders if o.decision_time == context.virtual_time
            ]

            cycle_result = DecisionCycleResult(
                cycle_id=cycle_id,
                agent_id=agent_id,
                simulation_id=simulation_id,
                candle_timestamp=candle_ts,
                status=cycle_status,
                decision=final_decision,
                reconciliation=reconciliation,
                tool_executions=tool_executions,
                orders_staged=staged_order_ids,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                total_latency_ms=total_latency_ms,
                turns_count=turns_count,
                error=cycle_error,
            )

            if self.memory_service is not None:
                self.memory_service.record_decision(
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                    result=cycle_result,
                )

            return cycle_result
        except Exception as exc:
            logger.exception(
                "Unexpected exception during decision cycle for sim '%s', agent '%s'",
                simulation_id,
                agent_id,
            )
            return DecisionCycleResult(
                cycle_id=cycle_id,
                agent_id=agent_id,
                simulation_id=simulation_id,
                candle_timestamp=candle_ts,
                status=CycleStatus.GEMINI_ERROR,
                decision=None,
                reconciliation=None,
                tool_executions=tool_executions,
                orders_staged=[],
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                total_latency_ms=total_latency_ms,
                turns_count=turns_count,
                error=f"Unexpected exception in decision cycle: {exc}",
            )

    async def run_cycle_async(
        self,
        context: ToolExecutionContext,
        mandate: AgentMandate,
        agent_id: str = "default-agent",
        simulation_id: Optional[str] = None,
        memory: Optional[AgentMemory] = None,
    ) -> DecisionCycleResult:
        """Execute an asynchronous event-driven decision cycle on completed candle t."""
        cycle_id = str(uuid.uuid4())
        candle_ts = context.virtual_time
        event_key = (simulation_id, agent_id, candle_ts)

        with self._lock:
            if event_key in self._processed_events:
                logger.warning(
                    "Duplicate event skipped for simulation '%s', agent '%s' at timestamp %s",
                    simulation_id,
                    agent_id,
                    candle_ts.isoformat(),
                )
                return DecisionCycleResult(
                    cycle_id=cycle_id,
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                    candle_timestamp=candle_ts,
                    status=CycleStatus.SKIPPED_DUPLICATE,
                    decision=None,
                    reconciliation=None,
                    tool_executions=[],
                    orders_staged=[],
                    error=f"Duplicate event at {candle_ts.isoformat()} already processed.",
                )
            self._processed_events.add(event_key)

        tool_executions: List[CycleToolExecution] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_latency_ms = 0.0
        turns_count = 0
        final_decision: Optional[AgentDecision] = None
        cycle_error: Optional[str] = None
        cycle_status: CycleStatus = CycleStatus.SUCCESS

        try:
            system_inst = build_system_instruction(mandate)

            # Resolve bounded historical memory if configured
            active_memory = memory
            if active_memory is None and self.memory_service is not None:
                active_memory = self.memory_service.get_memory_from_context(
                    context=context,
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                )

            cycle_prompt = build_cycle_prompt(context, mandate, memory=active_memory)

            messages: List[GeminiMessage] = [GeminiMessage(role="user", content=cycle_prompt)]

            for _ in range(self.max_turns):
                turns_count += 1
                req = GeminiRequest(
                    system_instruction=system_inst,
                    messages=messages,
                    tools_enabled=True,
                    structured_output=True,
                )

                res = await self.client.generate_async(req)
                total_prompt_tokens += res.prompt_tokens
                total_completion_tokens += res.completion_tokens
                total_latency_ms += res.latency_ms

                if not res.success:
                    cycle_error = res.error or "Gemini API error during decision cycle"
                    cycle_status = CycleStatus.GEMINI_ERROR
                    break

                if res.decision is not None:
                    final_decision = res.decision
                    break

                if res.tool_calls:
                    tool_responses: List[GeminiToolResponse] = []
                    for tc in res.tool_calls:
                        t_start = time.perf_counter()
                        tool_res = self.harness.dispatch(
                            tool_name=tc.name,
                            raw_args=tc.args,
                            context=context,
                        )
                        t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

                        staged_id = (
                            tool_res.data.get("order_id")
                            if (tool_res.success and tool_res.data)
                            else None
                        )
                        tool_executions.append(
                            CycleToolExecution(
                                tool_name=tc.name,
                                arguments=tc.args,
                                success=tool_res.success,
                                data=tool_res.data,
                                error=tool_res.error,
                                error_type=str(tool_res.error_type)
                                if tool_res.error_type
                                else None,
                                execution_time_ms=t_elapsed_ms,
                                staged_order_id=staged_id,
                            )
                        )

                        resp_data = (
                            tool_res.data
                            if tool_res.success
                            else {
                                "error": tool_res.error,
                                "error_type": str(tool_res.error_type),
                            }
                        )
                        tool_responses.append(
                            GeminiToolResponse(name=tc.name, response=resp_data or {})
                        )

                    messages.append(GeminiMessage(role="model", tool_calls=res.tool_calls))
                    messages.append(GeminiMessage(role="tool", tool_responses=tool_responses))
                else:
                    cycle_error = "Model generated neither tool calls nor structured AgentDecision."
                    cycle_status = CycleStatus.GEMINI_ERROR
                    break

            if final_decision is None and cycle_status != CycleStatus.GEMINI_ERROR:
                cycle_status = CycleStatus.MAX_TURNS_EXCEEDED
                cycle_error = (
                    f"Agent interaction bound exceeded ({self.max_turns} turns) without decision."
                )

            reconciliation: Optional[DecisionReconciliation] = None
            if final_decision is not None:
                reconciliation = reconcile_decision_with_tools(
                    decision=final_decision,
                    tool_executions=tool_executions,
                    context=context,
                    mandate=mandate,
                    harness=self.harness,
                )
                if reconciliation.order_staged:
                    cycle_status = (
                        CycleStatus.TOOL_ORDER_STAGED
                        if reconciliation.order_source == "TOOL"
                        else CycleStatus.DECISION_ORDER_STAGED
                    )
                else:
                    cycle_status = (
                        CycleStatus.NO_ACTION
                        if final_decision.action == AgentAction.HOLD
                        else CycleStatus.SUCCESS
                    )

            staged_order_ids = [
                o.order_id for o in context.staged_orders if o.decision_time == context.virtual_time
            ]

            cycle_result = DecisionCycleResult(
                cycle_id=cycle_id,
                agent_id=agent_id,
                simulation_id=simulation_id,
                candle_timestamp=candle_ts,
                status=cycle_status,
                decision=final_decision,
                reconciliation=reconciliation,
                tool_executions=tool_executions,
                orders_staged=staged_order_ids,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                total_latency_ms=total_latency_ms,
                turns_count=turns_count,
                error=cycle_error,
            )

            if self.memory_service is not None:
                self.memory_service.record_decision(
                    agent_id=agent_id,
                    simulation_id=simulation_id,
                    result=cycle_result,
                )

            return cycle_result
        except Exception as exc:
            logger.exception(
                "Unexpected exception during async decision cycle for sim '%s', agent '%s'",
                simulation_id,
                agent_id,
            )
            return DecisionCycleResult(
                cycle_id=cycle_id,
                agent_id=agent_id,
                simulation_id=simulation_id,
                candle_timestamp=candle_ts,
                status=CycleStatus.GEMINI_ERROR,
                decision=None,
                reconciliation=None,
                tool_executions=tool_executions,
                orders_staged=[],
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                total_latency_ms=total_latency_ms,
                turns_count=turns_count,
                error=f"Unexpected exception in decision cycle: {exc}",
            )


def create_agent_strategy(
    cycle: AgentDecisionCycle,
    mandate: AgentMandate,
    portfolio: PortfolioTracker,
    risk_engine: RiskEngine,
    agent_id: str = "default-agent",
    simulation_id: Optional[str] = None,
    on_cycle_complete: Optional[Callable[[DecisionCycleResult], None]] = None,
    memory_service: Optional[AgentMemoryService] = None,
    failure_handler: Optional[AgentFailureHandler] = None,
) -> StrategyCallable:
    """Create a StrategyCallable adapter integrating AgentDecisionCycle into ChronologicalReplayEngine.

    At each completed candle t, ChronologicalReplayEngine invokes this adapter with ReplayContext.
    The adapter runs the agent decision cycle and returns the orders staged via the Phase 7C harness.
    If a failure_handler is configured and the agent is auto-paused, execution is halted immediately.
    """
    staged_orders_accumulator: List[OrderRequest] = []
    effective_memory_service = memory_service or cycle.memory_service

    def agent_strategy(replay_context: ReplayContext) -> Sequence[OrderRequest]:
        # Fast path check: if agent is auto-paused, skip execution immediately
        if failure_handler is not None and failure_handler.is_paused(
            agent_id=agent_id, simulation_id=simulation_id
        ):
            logger.warning(
                "Agent '%s' in simulation '%s' is auto-paused; skipping decision cycle at t = %s",
                agent_id,
                simulation_id,
                replay_context.virtual_time.isoformat(),
            )
            return []

        # Reset staged list for current candle step
        staged_for_step: List[OrderRequest] = []

        tool_ctx = ToolExecutionContext.from_replay(
            replay_context=replay_context,
            symbol=mandate.instrument,
            timeframe=mandate.timeframe,
            portfolio=portfolio,
            risk_engine=risk_engine,
            staged_orders=staged_for_step,
        )

        active_memory = None
        if effective_memory_service is not None:
            active_memory = effective_memory_service.get_memory_from_context(
                context=tool_ctx,
                agent_id=agent_id,
                simulation_id=simulation_id,
            )

        if failure_handler is not None:
            res = failure_handler.execute_cycle(
                cycle=cycle,
                context=tool_ctx,
                mandate=mandate,
                agent_id=agent_id,
                simulation_id=simulation_id,
                memory=active_memory,
            )
        else:
            res = cycle.run_cycle(
                context=tool_ctx,
                mandate=mandate,
                agent_id=agent_id,
                simulation_id=simulation_id,
                memory=active_memory,
            )

        if on_cycle_complete:
            try:
                on_cycle_complete(res)
            except Exception:
                logger.exception("Error in on_cycle_complete callback")

        # If cycle failed (e.g. GEMINI_ERROR, MAX_TURNS_EXCEEDED) or triggered an auto-pause,
        # ensure no intermediate orders proceed
        is_cycle_failed = res.status in (
            CycleStatus.GEMINI_ERROR,
            CycleStatus.MAX_TURNS_EXCEEDED,
        )
        is_agent_paused = failure_handler is not None and failure_handler.is_paused(
            agent_id=agent_id, simulation_id=simulation_id
        )
        if is_cycle_failed or is_agent_paused:
            staged_for_step.clear()

        staged_orders_accumulator.extend(staged_for_step)
        return staged_for_step

    return agent_strategy
