"""Unit and integration tests for Phase 8C: Event-Driven Gemini Decision Cycle."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import AgentToolCall as DBAgentToolCall
from app.database.models import AgentUsage as DBAgentUsage
from app.market_data.schema import CandleData
from app.trading.agent.cycle import (
    AgentDecisionCycle,
    CycleStatus,
    CycleToolExecution,
    DecisionCycleResult,
    build_cycle_prompt,
    build_system_instruction,
    create_agent_strategy,
    persist_cycle_result,
    reconcile_decision_with_tools,
)
from app.trading.agent.gemini import GeminiClient, GeminiConfig
from app.trading.agent.harness import SafeToolExecutionHarness
from app.trading.agent.mandate import AgentMandate
from app.trading.agent.schemas import AgentAction, AgentDecision
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderSide
from app.trading.simulation.replay import ChronologicalReplayEngine

# ==============================================================================
# Test Fakes & Fixtures
# ==============================================================================


class FakeModelsService:
    """Mock models service returning programmed SDK responses."""

    def __init__(self, response_generator: Optional[Callable[..., Any]] = None) -> None:
        self.response_generator = response_generator
        self.call_count = 0
        self.calls: List[Dict[str, Any]] = []

    def generate_content(self, model: str, contents: Any, config: Any) -> Any:
        self.call_count += 1
        call_info = {"model": model, "contents": contents, "config": config}
        self.calls.append(call_info)
        if callable(self.response_generator):
            return self.response_generator(model, contents, config, self.call_count)
        return self.response_generator


class FakeAioModelsService:
    """Mock async models service."""

    def __init__(self, sync_models: FakeModelsService) -> None:
        self._sync = sync_models

    async def generate_content(self, model: str, contents: Any, config: Any) -> Any:
        return self._sync.generate_content(model, contents, config)


class FakeGenAIClient:
    """Mock Google GenAI client."""

    def __init__(self, response_generator: Optional[Callable[..., Any]] = None) -> None:
        self.models = FakeModelsService(response_generator)
        self.aio = SimpleNamespace(models=FakeAioModelsService(self.models))


def make_sdk_decision_response(
    decision_dict: Dict[str, Any],
    prompt_tokens: int = 150,
    candidates_tokens: int = 50,
) -> types.GenerateContentResponse:
    """Construct SDK response carrying structured AgentDecision JSON."""
    raw_json = json.dumps(decision_dict)
    part = types.Part(text=raw_json)
    content = types.Content(role="model", parts=[part])
    candidate = types.Candidate(content=content, finish_reason="STOP")
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=candidates_tokens,
        total_token_count=prompt_tokens + candidates_tokens,
    )
    return types.GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=usage,
    )


def make_sdk_tool_call_response(
    tool_calls: List[tuple[str, Dict[str, Any]]],
    prompt_tokens: int = 120,
    candidates_tokens: int = 30,
) -> types.GenerateContentResponse:
    """Construct SDK response carrying function calls."""
    parts = []
    for idx, (name, args) in enumerate(tool_calls):
        fc = types.FunctionCall(name=name, args=args, id=f"call_{idx}")
        parts.append(types.Part(function_call=fc))

    content = types.Content(role="model", parts=parts)
    candidate = types.Candidate(content=content, finish_reason="STOP")
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_tokens,
        candidates_token_count=candidates_tokens,
        total_token_count=prompt_tokens + candidates_tokens,
    )
    return types.GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=usage,
    )


def generate_synthetic_candles(count: int = 20, base_price: float = 2500.0) -> List[CandleData]:
    """Generate synthetic sequential 15-minute candles."""
    start_time = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candles = []
    curr_price = base_price
    for i in range(count):
        ts = start_time + timedelta(minutes=15 * i)
        o = curr_price
        h = curr_price + 10.0
        l = curr_price - 5.0
        c = curr_price + (2.0 if i % 2 == 0 else -1.0)
        v = 50000.0 + (i * 1000.0)
        candles.append(CandleData(timestamp=ts, open=o, high=h, low=l, close=c, volume=v))
        curr_price = c
    return candles


@pytest.fixture
def sample_mandate() -> AgentMandate:
    return AgentMandate(
        strategy_style="MOMENTUM",
        objectives=["Capitalize on intraday breakouts above EMA20"],
        preferred_indicators=["EMA20", "RSI14"],
        instrument="RELIANCE",
        timeframe="15m",
        risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_daily_loss=0.05,
    )


@pytest.fixture
def sample_context() -> ToolExecutionContext:
    candles = generate_synthetic_candles(count=10, base_price=2500.0)
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    current = candles[-1]
    return ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=current.timestamp,
        current_candle=current,
        visible_candles=candles,
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=[],
    )


# ==============================================================================
# 1. Triggering & Idempotency Tests
# ==============================================================================


def test_decision_cycle_trigger_and_idempotency(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Decision cycle executes once and idempotent guard prevents duplicate execution at same timestamp."""
    decision_dict = {
        "action": "HOLD",
        "confidence": 0.8,
        "reason": "Market consolidating near VWAP.",
        "observations": ["RSI in neutral 50 zone"],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, count: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    # First invocation: runs normally
    res1 = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="agent-test-1",
    )
    assert res1.status == CycleStatus.NO_ACTION
    assert res1.decision is not None
    assert res1.decision.action == AgentAction.HOLD
    assert fake_client.models.call_count == 1

    # Second invocation with same agent_id and virtual_time: duplicate skipped
    res2 = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="agent-test-1",
    )
    assert res2.status == CycleStatus.SKIPPED_DUPLICATE
    assert "Duplicate event" in str(res2.error)
    # Gemini must NOT have been called a second time
    assert fake_client.models.call_count == 1

    # Reset idempotency cache allows re-run
    cycle.reset_idempotency_cache()
    res3 = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="agent-test-1",
    )
    assert res3.status == CycleStatus.NO_ACTION
    assert fake_client.models.call_count == 2


# ==============================================================================
# 2. Context & No-Lookahead Tests
# ==============================================================================


def test_prompt_no_lookahead_and_mandate_fidelity(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Prompts contain strictly data <= t, valid timestamp, and mandate settings."""
    sys_inst = build_system_instruction(sample_mandate)
    assert "RELIANCE" in sys_inst
    assert "15m" in sys_inst
    assert "MOMENTUM" in sys_inst
    assert "EMA20" in sys_inst
    assert "2.00%" in sys_inst
    assert "NO LOOKAHEAD" in sys_inst

    cycle_prompt = build_cycle_prompt(sample_context, sample_mandate)
    assert sample_context.virtual_time.isoformat() in cycle_prompt
    assert f"Close={float(sample_context.current_candle.close):.2f}" in cycle_prompt
    assert "FLAT (no active position)" in cycle_prompt
    assert "Total visible historical candles up to t: 10" in cycle_prompt


# ==============================================================================
# 3. Bounded Multi-Turn Tool Loop Tests
# ==============================================================================


def test_multi_turn_tool_loop_to_decision(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Gemini invokes tools over multiple turns, receiving results before emitting AgentDecision."""
    decision_dict = {
        "action": "BUY",
        "confidence": 0.85,
        "quantity": 5,
        "stop_loss": 2450.0,
        "take_profit": 2600.0,
        "reason": "Breakout confirmed by RSI and indicators.",
        "observations": ["Price > EMA20", "RSI is 62"],
        "tools_used": ["get_market_data", "calculate_position_size"],
    }

    def generator(model, contents, config, turn_count):
        if turn_count == 1:
            # Turn 1: model asks for market data
            return make_sdk_tool_call_response([("get_market_data", {"lookback": 5})])
        elif turn_count == 2:
            # Turn 2: model asks for position sizing
            return make_sdk_tool_call_response(
                [("calculate_position_size", {"entry_price": 2500.0, "stop_loss_price": 2450.0})]
            )
        else:
            # Turn 3: model produces final decision
            return make_sdk_decision_response(decision_dict)

    fake_client = FakeGenAIClient(response_generator=generator)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client, max_turns=5)

    res = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="agent-tool-loop",
    )

    assert res.status == CycleStatus.DECISION_ORDER_STAGED
    assert res.turns_count == 3
    assert len(res.tool_executions) == 2
    assert res.tool_executions[0].tool_name == "get_market_data"
    assert res.tool_executions[0].success is True
    assert res.tool_executions[1].tool_name == "calculate_position_size"
    assert res.tool_executions[1].success is True
    assert res.decision is not None
    assert res.decision.action == AgentAction.BUY
    assert len(sample_context.staged_orders) == 1
    assert sample_context.staged_orders[0].side == OrderSide.BUY


def test_loop_bound_exceeded_terminates_safely(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """If Gemini calls tools indefinitely without a decision, cycle terminates at max_turns safely."""
    # Model always asks for market data and never terminates
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_tool_call_response(
            [("get_market_data", {"lookback": 5})]
        )
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client, max_turns=3)

    res = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="agent-infinite-tools",
    )

    assert res.status == CycleStatus.MAX_TURNS_EXCEEDED
    assert res.turns_count == 3
    assert len(res.tool_executions) == 3
    assert res.decision is None
    assert len(sample_context.staged_orders) == 0


# ==============================================================================
# 4. Reconciliation Tests
# ==============================================================================


def test_reconciliation_tool_staged_order_prevents_duplicate(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """When a tool successfully stages a BUY order, matching BUY AgentDecision does NOT duplicate."""
    curr_px = float(sample_context.current_candle.close)
    decision_dict = {
        "action": "BUY",
        "confidence": 0.9,
        "quantity": 5,
        "stop_loss": round(curr_px * 0.98, 2),
        "take_profit": round(curr_px * 1.05, 2),
        "reason": "Tool order placed; confirming in decision.",
        "observations": [],
        "tools_used": ["place_simulated_order"],
    }

    def generator(model, contents, config, turn_count):
        if turn_count == 1:
            # Model stages order via mutating tool
            return make_sdk_tool_call_response(
                [
                    (
                        "place_simulated_order",
                        {
                            "side": "BUY",
                            "quantity": 5,
                            "stop_loss": round(curr_px * 0.98, 2),
                            "reason": "Tool buy",
                        },
                    )
                ]
            )
        else:
            # Model returns decision matching the tool action
            return make_sdk_decision_response(decision_dict)

    fake_client = FakeGenAIClient(response_generator=generator)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.TOOL_ORDER_STAGED
    assert res.reconciliation is not None
    assert res.reconciliation.order_source == "TOOL"
    assert res.reconciliation.status == "ALREADY_STAGED_BY_TOOL"
    # STRICT INVARIANT: Exactly 1 staged order exists; no duplicate submitted
    assert len(sample_context.staged_orders) == 1
    assert sample_context.staged_orders[0].quantity == 5


def test_reconciliation_direct_buy_without_prior_tool_stages_via_harness(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """When decision is BUY but no tool staged an order, 8C dispatches order through Phase 7C harness."""
    decision_dict = {
        "action": "BUY",
        "confidence": 0.88,
        "quantity": 5,
        "stop_loss": 2400.0,
        "take_profit": 2600.0,
        "reason": "Strong momentum detected.",
        "observations": ["Breakout above resistance"],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.DECISION_ORDER_STAGED
    assert res.reconciliation is not None
    assert res.reconciliation.order_source == "DECISION"
    assert res.reconciliation.status == "STAGED_BY_DECISION"
    assert len(sample_context.staged_orders) == 1
    assert sample_context.staged_orders[0].quantity == 5
    assert sample_context.staged_orders[0].side == OrderSide.BUY


def test_reconciliation_buy_with_none_quantity_computes_sizing_via_harness(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """When decision is BUY with quantity=None, sizing is computed via harness before staging."""
    curr_px = float(sample_context.current_candle.close)
    decision_dict = {
        "action": "BUY",
        "confidence": 0.8,
        "quantity": None,
        "stop_loss": round(curr_px * 0.98, 2),
        "take_profit": round(curr_px * 1.04, 2),
        "reason": "Buy with dynamic position size.",
        "observations": [],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.DECISION_ORDER_STAGED
    assert len(sample_context.staged_orders) == 1
    assert sample_context.staged_orders[0].quantity > 0


def test_reconciliation_sell_with_open_position_stages_close(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """SELL decision when position is open stages close order via Phase 7C harness."""
    # Setup an active open position of 5 shares
    curr_px = float(sample_context.current_candle.close)
    sample_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=5,
        price=curr_px,
        timestamp=sample_context.virtual_time - timedelta(minutes=30),
    )
    assert sample_context.portfolio.get_position("RELIANCE").quantity == 5

    decision_dict = {
        "action": "SELL",
        "confidence": 0.92,
        "quantity": 5,
        "reason": "Exit long position at target.",
        "observations": ["Target reached"],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.DECISION_ORDER_STAGED
    assert res.reconciliation.order_source == "DECISION"
    assert len(sample_context.staged_orders) == 1
    assert sample_context.staged_orders[0].side == OrderSide.SELL
    assert sample_context.staged_orders[0].quantity == 5


def test_reconciliation_sell_when_flat_skips_cleanly(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """SELL decision when flat produces NO_ACTION_FLAT without error or order staging."""
    decision_dict = {
        "action": "SELL",
        "confidence": 0.7,
        "quantity": 10,
        "reason": "Attempting to short, but equities are long-only.",
        "observations": [],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.SUCCESS
    assert res.reconciliation is not None
    assert res.reconciliation.status == "NO_ACTION_FLAT"
    assert res.reconciliation.order_staged is False
    assert len(sample_context.staged_orders) == 0


def test_rejected_tool_order_does_not_count_as_staged(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Rejected mutating tool call is NOT treated as a successfully staged order."""
    # Attempt to place order exceeding risk limit (e.g. 5,000 shares on 100k capital)
    tool_args = {"side": "BUY", "quantity": 5000, "reason": "Excessive size"}
    harness = SafeToolExecutionHarness()
    exec_res = harness.dispatch("place_simulated_order", tool_args, sample_context)
    assert exec_res.success is False

    # Build cycle tool execution record of the rejection
    tool_execs = [
        CycleToolExecution(
            tool_name="place_simulated_order",
            arguments=tool_args,
            success=False,
            error=exec_res.error,
            error_type=str(exec_res.error_type),
        )
    ]
    # Decision is BUY with a safe quantity of 5
    decision = AgentDecision(
        action=AgentAction.BUY,
        confidence=0.8,
        quantity=5,
        stop_loss=2450.0,
        reason="Safe buy after rejected test",
    )

    reconciled = reconcile_decision_with_tools(
        decision=decision,
        tool_executions=tool_execs,
        context=sample_context,
        mandate=sample_mandate,
        harness=harness,
    )

    # Since the tool order failed, reconciliation staged the safe decision order
    assert reconciled.order_staged is True
    assert reconciled.order_source == "DECISION"
    assert len(sample_context.staged_orders) == 1
    assert sample_context.staged_orders[0].quantity == 5


# ==============================================================================
# 5. Failure Containment & Error Boundaries
# ==============================================================================


def test_gemini_api_failure_contained(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Gemini API failure cleanly returns GEMINI_ERROR without unhandled crash or side effects."""
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: (_ for _ in ()).throw(
            RuntimeError("API Network Timeout")
        )
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.GEMINI_ERROR
    assert "API Network Timeout" in str(res.error)
    assert res.decision is None
    assert len(sample_context.staged_orders) == 0


def test_tool_error_fed_to_agent_without_crashing_cycle(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Unknown or failing tool execution is safely contained and passed as response to Gemini."""
    decision_dict = {
        "action": "HOLD",
        "confidence": 0.6,
        "reason": "Tool failed; defaulting to safe HOLD.",
        "observations": ["Invalid lookback schema error"],
        "tools_used": ["get_market_data"],
    }

    def generator(model, contents, config, turn_count):
        if turn_count == 1:
            # Model calls registered tool with invalid arguments
            return make_sdk_tool_call_response([("get_market_data", {"lookback": -5})])
        else:
            # Model receives error and decides HOLD
            return make_sdk_decision_response(decision_dict)

    fake_client = FakeGenAIClient(response_generator=generator)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.NO_ACTION
    assert len(res.tool_executions) == 1
    assert res.tool_executions[0].success is False
    assert "Schema validation failed" in str(res.tool_executions[0].error)


# ==============================================================================
# 6. ChronologicalReplayEngine Integration (Phase 6 Next-Open Execution)
# ==============================================================================


def test_replay_engine_integration_and_next_open_execution(
    sample_mandate: AgentMandate,
):
    """AgentDecisionCycle integrates with ChronologicalReplayEngine via StrategyCallable adapter."""
    candles = generate_synthetic_candles(count=5, base_price=2500.0)
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()

    replay_engine = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Strategy: on step 0, stage a BUY order; on step 1, stage a close SELL order; step 2 HOLD
    curr_px = float(candles[0].close)

    def generator(model, contents, config, turn_count):
        # Examine step from prompt
        text_content = ""
        for item in contents:
            if hasattr(item, "parts"):
                for p in item.parts:
                    if hasattr(p, "text"):
                        text_content += p.text

        if "2025-01-15T09:15:00" in text_content:
            # Step 0: BUY
            return make_sdk_decision_response(
                {
                    "action": "BUY",
                    "confidence": 0.9,
                    "quantity": 5,
                    "stop_loss": round(curr_px * 0.98, 2),
                    "reason": "Step 0 Buy",
                    "observations": [],
                    "tools_used": [],
                }
            )
        elif "2025-01-15T09:30:00" in text_content:
            # Step 1: SELL (close)
            return make_sdk_decision_response(
                {
                    "action": "SELL",
                    "confidence": 0.9,
                    "quantity": 5,
                    "reason": "Step 1 Close",
                    "observations": [],
                    "tools_used": [],
                }
            )
        else:
            return make_sdk_decision_response(
                {
                    "action": "HOLD",
                    "confidence": 0.8,
                    "reason": "Step 2 Flat",
                    "observations": [],
                    "tools_used": [],
                }
            )

    fake_client = FakeGenAIClient(response_generator=generator)
    gemini_client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=gemini_client)

    completed_cycles: List[DecisionCycleResult] = []

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=sample_mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="replay-agent",
        on_cycle_complete=completed_cycles.append,
    )

    summary = replay_engine.run(strategy=strategy)

    # Verifications:
    # 1. 5 candle steps processed
    assert len(completed_cycles) == 5
    # 2. Next-open execution: order staged at Bar 0 Close executed at Bar 1 Open
    assert len(summary.trades) == 1
    assert len(replay_engine.portfolio.closed_trades) == 1
    assert len(replay_engine.execution_history) == 2


# ==============================================================================
# 7. Asynchronous Parity Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_async_cycle_execution_parity(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """run_cycle_async executes identically to run_cycle."""
    decision_dict = {
        "action": "BUY",
        "confidence": 0.85,
        "quantity": 8,
        "stop_loss": 2450.0,
        "reason": "Async cycle execution test.",
        "observations": [],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = await cycle.run_cycle_async(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="async-agent",
    )

    assert res.status == CycleStatus.DECISION_ORDER_STAGED
    assert res.decision is not None
    assert res.decision.action == AgentAction.BUY
    assert len(sample_context.staged_orders) == 1


# ==============================================================================
# 8. Database Persistence Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_database_persistence_of_cycle_and_telemetry(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """persist_cycle_result commits AgentDecision, AgentToolCall, and AgentUsage records."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    decision_dict = {
        "action": "BUY",
        "confidence": 0.91,
        "quantity": 10,
        "stop_loss": 2450.0,
        "take_profit": 2600.0,
        "reason": "Persistent DB cycle record test.",
        "observations": ["Bullish structure"],
        "tools_used": ["get_market_data"],
    }

    def generator(model, contents, config, turn_count):
        if turn_count == 1:
            return make_sdk_tool_call_response([("get_market_data", {"lookback": 5})])
        return make_sdk_decision_response(decision_dict)

    fake_client = FakeGenAIClient(response_generator=generator)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="db-test-agent",
    )

    async with async_session() as db:
        # Create dummy agent record to satisfy foreign key constraint if needed
        db_rec = await persist_cycle_result(db=db, result=res)
        assert db_rec is not None
        assert db_rec.action.value == "BUY"
        assert db_rec.confidence == 0.91
        assert db_rec.reason == "Persistent DB cycle record test."

        # Verify tool calls persisted
        tool_stmt = select(DBAgentToolCall).where(DBAgentToolCall.decision_id == res.cycle_id)
        tool_res = await db.execute(tool_stmt)
        tool_records = tool_res.scalars().all()
        assert len(tool_records) == 1
        assert tool_records[0].tool_name == "get_market_data"

        # Verify usage persisted
        usage_stmt = select(DBAgentUsage).where(DBAgentUsage.agent_id == "db-test-agent")
        usage_res = await db.execute(usage_stmt)
        usage_records = usage_res.scalars().all()
        assert len(usage_records) == 1
        assert usage_records[0].total_tokens > 0

    await engine.dispose()


# ==============================================================================
# 9. Architectural Audit Regression Tests
# ==============================================================================


def test_concurrent_deduplication_thread_safety(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Multiple concurrent threads invoking run_cycle for the same event produce exactly one execution."""
    import concurrent.futures

    decision_dict = {
        "action": "HOLD",
        "confidence": 0.8,
        "reason": "Thread safety test",
        "observations": [],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(
                cycle.run_cycle,
                context=sample_context,
                mandate=sample_mandate,
                agent_id="thread-agent",
                simulation_id="sim-thread",
            )
            for _ in range(5)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    success_count = sum(1 for r in results if r.status == CycleStatus.NO_ACTION)
    duplicate_count = sum(1 for r in results if r.status == CycleStatus.SKIPPED_DUPLICATE)
    assert success_count == 1
    assert duplicate_count == 4


def test_cross_simulation_isolation(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Simulations sim-1 and sim-2 at the same timestamp do not collide in deduplication."""
    decision_dict = {
        "action": "HOLD",
        "confidence": 0.8,
        "reason": "Simulation isolation test",
        "observations": [],
        "tools_used": [],
    }
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(decision_dict)
    )
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res1 = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="shared-agent",
        simulation_id="sim-1",
    )
    res2 = cycle.run_cycle(
        context=sample_context,
        mandate=sample_mandate,
        agent_id="shared-agent",
        simulation_id="sim-2",
    )

    assert res1.status == CycleStatus.NO_ACTION
    assert res2.status == CycleStatus.NO_ACTION
    assert res1.simulation_id == "sim-1"
    assert res2.simulation_id == "sim-2"


@pytest.mark.asyncio
async def test_persistence_failure_rollback(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """When db.commit fails during persistence, rollback is executed and exception propagates."""
    from unittest.mock import AsyncMock, MagicMock

    mock_db = MagicMock(spec=AsyncSession)
    mock_db.commit = AsyncMock(side_effect=RuntimeError("Database write failure"))
    mock_db.rollback = AsyncMock()

    res = DecisionCycleResult(
        cycle_id="err-cycle-1",
        agent_id="err-agent",
        simulation_id="sim-err",
        candle_timestamp=sample_context.virtual_time,
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.HOLD,
            confidence=0.9,
            reason="Test rollback",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        total_latency_ms=20.0,
        turns_count=1,
    )

    with pytest.raises(RuntimeError, match="Database write failure"):
        await persist_cycle_result(db=mock_db, result=res)

    mock_db.rollback.assert_awaited_once()


def test_unexpected_exception_containment(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Unexpected exception in client or cycle safely yields GEMINI_ERROR without crashing."""
    from unittest.mock import MagicMock

    mock_client = MagicMock(spec=GeminiClient)
    mock_client.generate.side_effect = RuntimeError("Fatal connection crash")
    cycle = AgentDecisionCycle(client=mock_client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.GEMINI_ERROR
    assert "Unexpected exception in decision cycle" in (res.error or "")
    assert len(res.orders_staged) == 0


def test_message_history_preservation_across_multiple_turns(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Gemini tool-call turns accumulate full conversation history in request messages."""
    recorded_requests = []

    def generator(model, contents, config, turn_count):
        recorded_requests.append(list(contents))
        if turn_count == 1:
            return make_sdk_tool_call_response([("get_market_data", {"lookback": 2})])
        elif turn_count == 2:
            return make_sdk_tool_call_response([("get_position", {})])
        else:
            return make_sdk_decision_response(
                {
                    "action": "HOLD",
                    "confidence": 0.85,
                    "reason": "Analyzed market data and position.",
                    "observations": ["Flat"],
                    "tools_used": ["get_market_data", "get_position"],
                }
            )

    fake_client = FakeGenAIClient(response_generator=generator)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=client)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.NO_ACTION
    assert res.turns_count == 3
    assert len(recorded_requests) == 3

    # Turn 1: 1 content item (user initial prompt)
    assert len(recorded_requests[0]) == 1
    assert recorded_requests[0][0].role == "user"

    # Turn 2: 3 content items (user prompt + model tc1 + tool resp1)
    assert len(recorded_requests[1]) == 3
    assert recorded_requests[1][0].role == "user"
    assert recorded_requests[1][1].role == "model"
    assert recorded_requests[1][2].role == "tool"

    # Turn 3: 5 content items (user + model tc1 + tool resp1 + model tc2 + tool resp2)
    assert len(recorded_requests[2]) == 5
    assert recorded_requests[2][3].role == "model"
    assert recorded_requests[2][4].role == "tool"
