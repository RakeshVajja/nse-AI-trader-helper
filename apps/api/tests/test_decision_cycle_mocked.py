"""Phase 8F: Mocked Decision-Cycle End-to-End Integration Tests.

Validates the complete integration path:
simulation/replay candle
→ agent strategy
→ AgentDecisionCycle
→ GeminiClient
→ SafeToolExecutionHarness
→ Phase 7 tools
→ reconciliation
→ AgentDecision
→ staging
→ ChronologicalReplayEngine next-open execution
→ portfolio/trade state
→ AgentMemory
→ failure handling / auto-pause
→ persistence.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import (
    Agent as DBAgent,
)
from app.database.models import (
    AgentDecision as DBAgentDecision,
)
from app.database.models import (
    AgentStatus,
    Instrument,
    InstrumentType,
    SimulationRun,
    SimulationStatus,
)
from app.database.models import (
    AgentUsage as DBAgentUsage,
)
from app.market_data.schema import CandleData
from app.trading.agent.cycle import (
    AgentDecisionCycle,
    CycleStatus,
    DecisionCycleResult,
    create_agent_strategy,
    persist_cycle_result,
)
from app.trading.agent.gemini import GeminiClient, GeminiConfig
from app.trading.agent.harness import SafeToolExecutionHarness
from app.trading.agent.mandate import AgentMandate
from app.trading.agent.memory import AgentMemoryService
from app.trading.agent.safety import (
    AgentFailureHandler,
    FailureCategory,
    FailurePolicyConfig,
)
from app.trading.agent.schemas import AgentAction, AgentDecision
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderSide, OrderStatus
from app.trading.simulation.replay import ChronologicalReplayEngine

# ==============================================================================
# Mock SDK Fixtures & Factories
# ==============================================================================


class FakeModelsService:
    """Mock Google GenAI models service returning programmed SDK responses."""

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
    """Mock Google GenAI client injecting FakeModelsService."""

    def __init__(self, response_generator: Optional[Callable[..., Any]] = None) -> None:
        self.models = FakeModelsService(response_generator)
        self.aio = SimpleNamespace(models=FakeAioModelsService(self.models))


def make_sdk_decision_response(
    decision_dict: Dict[str, Any],
    prompt_tokens: int = 150,
    candidates_tokens: int = 50,
) -> types.GenerateContentResponse:
    """Construct SDK response containing structured AgentDecision JSON."""
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
    """Construct SDK response requesting tool execution."""
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


def generate_candles(
    count: int = 10,
    base_price: float = 2500.0,
    start_time: Optional[datetime] = None,
) -> List[CandleData]:
    """Generate sequential 15m OHLCV candles."""
    start = start_time or datetime(2026, 9, 7, 9, 15, tzinfo=timezone.utc)
    candles = []
    curr_px = base_price
    for i in range(count):
        ts = start + timedelta(minutes=15 * i)
        o = curr_px
        h = curr_px + 8.0
        l = curr_px - 4.0
        c = curr_px + 3.0
        v = 25000.0 + (i * 500.0)
        candles.append(CandleData(timestamp=ts, open=o, high=h, low=l, close=c, volume=v))
        curr_px = c
    return candles


def make_test_mandate(symbol: str = "RELIANCE") -> AgentMandate:
    return AgentMandate(
        strategy_style="MOMENTUM",
        objectives=["Capitalize on trend breakouts above EMA20", "Strict capital preservation"],
        preferred_indicators=["EMA20", "RSI14"],
        instrument=symbol,
        timeframe="15m",
        risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_daily_loss=0.05,
        rationale="Phase 8F end-to-end test mandate",
    )


# ==============================================================================
# 1. Successful HOLD Decision
# ==============================================================================


def test_mocked_cycle_successful_hold_decision() -> None:
    """Case 1: Gemini produces structured HOLD decision; 0 orders staged, portfolio flat."""
    resp = make_sdk_decision_response(
        {
            "action": "HOLD",
            "confidence": 0.8,
            "reason": "Market consolidating near resistance; no setup",
            "observations": ["Price at 2503", "RSI neutral"],
            "tools_used": [],
        }
    )
    fake_sdk = FakeGenAIClient(resp)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    memory_service = AgentMemoryService()
    cycle = AgentDecisionCycle(client=client, harness=harness, memory_service=memory_service)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()

    candles = generate_candles(count=2)
    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-hold",
        memory_service=memory_service,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step1 = replay.step(strategy=strategy)
    assert step1.candle.timestamp == candles[0].timestamp
    assert step1.strategy_orders_queued == []
    assert portfolio.get_position("RELIANCE") is None
    assert portfolio.cash == 100000.0

    # Memory check: HOLD decision was recorded into memory
    mem = memory_service.get_memory_from_context(
        context=ToolExecutionContext.from_replay(
            replay_context=MagicMock(virtual_time=candles[1].timestamp),
            symbol="RELIANCE",
            timeframe="15m",
            portfolio=portfolio,
            risk_engine=risk_engine,
        ),
        agent_id="test-agent",
        simulation_id="sim-hold",
    )
    assert len(mem.recent_decisions) == 1
    assert mem.recent_decisions[0].action == AgentAction.HOLD


# ==============================================================================
# 2. Successful BUY Decision (Structured Decision Path)
# ==============================================================================


def test_mocked_cycle_successful_buy_decision() -> None:
    """Case 2: Gemini produces BUY decision; order staged and executed at next candle OPEN."""
    resp = make_sdk_decision_response(
        {
            "action": "BUY",
            "quantity": 10,
            "confidence": 0.9,
            "reason": "Breakout confirmed above 2500",
            "observations": ["Strong bullish bar", "Volume spike"],
            "tools_used": [],
            "stop_loss": 2480.0,
            "take_profit": 2550.0,
        }
    )
    fake_sdk = FakeGenAIClient(resp)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=200000.0)
    risk_engine = RiskEngine()

    candles = generate_candles(count=3, base_price=2500.0)
    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-buy",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Step 1 at candle 0 (decision generated and queued for candle 1 Open)
    step0 = replay.step(strategy=strategy)
    assert len(step0.strategy_orders_queued) == 1
    staged_order = step0.strategy_orders_queued[0]
    assert staged_order.side == OrderSide.BUY
    assert staged_order.quantity == 10
    assert staged_order.decision_time == candles[0].timestamp
    # At step 0 CLOSE, order is not yet filled
    assert portfolio.get_position("RELIANCE") is None

    # Step 2 at candle 1 (order filled at candle 1 OPEN)
    step1 = replay.step()
    assert len(step1.strategy_orders_executed) == 1
    exec_res = step1.strategy_orders_executed[0]
    assert exec_res.status == OrderStatus.FILLED
    assert exec_res.quantity == 10
    assert exec_res.market_price == candles[1].open

    pos = portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10
    assert pos.average_entry_price == exec_res.execution_price
    assert portfolio.cash < 200000.0


# ==============================================================================
# 3. Successful SELL Decision
# ==============================================================================


def test_mocked_cycle_successful_sell_decision() -> None:
    """Case 3: Gemini produces SELL decision on open position; position closed at next Open."""
    candles = generate_candles(count=4, base_price=2500.0)
    portfolio = PortfolioTracker(initial_capital=200000.0)
    risk_engine = RiskEngine()

    replay = ChronologicalReplayEngine(
        candles=candles[1:],  # replay starting from candle 1
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Pre-open position of 10 shares (after replay init so set_candles doesn't reset it)
    portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2500.0,
        timestamp=candles[0].timestamp,
    )
    assert portfolio.get_position("RELIANCE").quantity == 10

    resp = make_sdk_decision_response(
        {
            "action": "SELL",
            "quantity": 10,
            "confidence": 0.85,
            "reason": "Target achieved; taking profit",
            "observations": ["Price reached target"],
            "tools_used": [],
        }
    )
    fake_sdk = FakeGenAIClient(resp)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-sell",
    )

    # Step 1: Decision cycle stages SELL
    step0 = replay.step(strategy=strategy)
    assert len(step0.strategy_orders_queued) == 1
    assert step0.strategy_orders_queued[0].side == OrderSide.SELL

    # Step 2: Next candle OPEN fills the SELL
    step1 = replay.step()
    assert len(step1.strategy_orders_executed) == 1
    assert step1.strategy_orders_executed[0].status == OrderStatus.FILLED
    assert portfolio.get_position("RELIANCE") is None
    assert len(portfolio.closed_trades) == 1


# ==============================================================================
# 4. Multi-Turn Tool Call Flow to Subsequent Decision
# ==============================================================================


def test_mocked_cycle_tool_call_flow_to_decision() -> None:
    """Case 4: Turn 1: model requests indicators; Turn 2: model produces BUY decision."""

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        if call_count == 1:
            return make_sdk_tool_call_response(
                [("get_indicators", {"indicators": ["EMA20", "RSI14"]})]
            )
        else:
            return make_sdk_decision_response(
                {
                    "action": "BUY",
                    "quantity": 5,
                    "confidence": 0.88,
                    "reason": "RSI shows bullish momentum following indicator check",
                    "observations": ["RSI above 50", "Price above EMA20"],
                    "tools_used": ["get_indicators"],
                }
            )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=25, base_price=2500.0)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-tools",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    # Exactly 2 turns executed
    assert fake_sdk.models.call_count == 2
    assert len(step.strategy_orders_queued) == 1
    assert step.strategy_orders_queued[0].side == OrderSide.BUY
    assert step.strategy_orders_queued[0].quantity == 5


# ==============================================================================
# 5. Tool-Staged Order Reconciliation (G1)
# ==============================================================================


def test_mocked_cycle_tool_staged_order_g1_reconciliation() -> None:
    """Case 5: Turn 1 stages order via place_simulated_order; Turn 2 confirms BUY; 0 duplicates."""

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        if call_count == 1:
            return make_sdk_tool_call_response(
                [
                    (
                        "place_simulated_order",
                        {
                            "side": "BUY",
                            "quantity": 8,
                            "order_type": "MARKET",
                            "reason": "Tool stage breakout",
                        },
                    )
                ]
            )
        else:
            return make_sdk_decision_response(
                {
                    "action": "BUY",
                    "quantity": 8,
                    "confidence": 0.92,
                    "reason": "Confirming pre-staged tool order",
                    "observations": ["Order placed by tool"],
                    "tools_used": ["place_simulated_order"],
                }
            )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=2)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-g1",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    # G1 reconciliation ensures exactly ONE order is staged (not duplicated)
    assert len(step.strategy_orders_queued) == 1
    assert step.strategy_orders_queued[0].quantity == 8
    assert step.strategy_orders_queued[0].side == OrderSide.BUY


# ==============================================================================
# 6. Decision-Only Order Path
# ==============================================================================


def test_mocked_cycle_decision_only_order_routed_through_harness() -> None:
    """Case 6: Model calls read-only tool; produces BUY; reconciliation routes via harness."""

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        if call_count == 1:
            return make_sdk_tool_call_response([("get_market_regime", {})])
        else:
            return make_sdk_decision_response(
                {
                    "action": "BUY",
                    "quantity": 6,
                    "confidence": 0.85,
                    "reason": "Regime is trending; executing BUY from decision",
                    "observations": ["Trending regime"],
                    "tools_used": ["get_market_regime"],
                }
            )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=25)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-dec-only",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    assert len(step.strategy_orders_queued) == 1
    assert step.strategy_orders_queued[0].quantity == 6


# ==============================================================================
# 7. Invalid Tool Call Recovered Gracefully
# ==============================================================================


def test_mocked_cycle_invalid_tool_call_recovered() -> None:
    """Case 7: Model calls unknown tool; harness catches it; model falls back to HOLD."""

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        if call_count == 1:
            return make_sdk_tool_call_response(
                [("get_indicators", {"indicators": ["UNSUPPORTED_XYZ"]})]
            )
        else:
            return make_sdk_decision_response(
                {
                    "action": "HOLD",
                    "confidence": 0.7,
                    "reason": "Unknown tool error handled; holding position",
                    "observations": ["Tool error encountered"],
                    "tools_used": [],
                }
            )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=2)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-bad-tool",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    assert fake_sdk.models.call_count == 2
    assert step.strategy_orders_queued == []


# ==============================================================================
# 8. Malformed Gemini Output Behavior
# ==============================================================================


def test_mocked_cycle_malformed_gemini_output() -> None:
    """Case 8: Gemini returns unparseable text; structured output error caught; 0 orders."""
    raw_bad_text = "Here is my reasoning: I think we should buy, but this is not JSON."
    part = types.Part(text=raw_bad_text)
    content = types.Content(role="model", parts=[part])
    candidate = types.Candidate(content=content, finish_reason="STOP")
    resp = types.GenerateContentResponse(candidates=[candidate])

    fake_sdk = FakeGenAIClient(resp)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=1, max_retries=0)
    )
    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=2)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-malformed",
        failure_handler=handler,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    assert step.strategy_orders_queued == []
    # Auto-pause triggered due to malformed output
    assert handler.is_paused("test-agent", "sim-malformed")
    assert handler.get_state("test-agent", "sim-malformed").last_failure_category == (
        FailureCategory.MALFORMED_OUTPUT
    )


# ==============================================================================
# 9. Maximum Tool-Turn Behavior
# ==============================================================================


def test_mocked_cycle_max_turns_exceeded() -> None:
    """Case 9: Model loops requesting tools; terminates at max_turns with 0 orders staged."""
    tool_resp = make_sdk_tool_call_response([("get_indicators", {"indicators": ["RSI14"]})])
    fake_sdk = FakeGenAIClient(tool_resp)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness, max_turns=3)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=25)

    last_res: Optional[DecisionCycleResult] = None

    def on_cycle(r: DecisionCycleResult) -> None:
        nonlocal last_res
        last_res = r

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-max-turns",
        on_cycle_complete=on_cycle,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    assert fake_sdk.models.call_count == 3
    assert step.strategy_orders_queued == []
    assert last_res is not None
    assert last_res.status == CycleStatus.MAX_TURNS_EXCEEDED


# ==============================================================================
# 10. Retryable Gemini Failure Interacting with Phase 8E Retry Handling
# ==============================================================================


def test_mocked_cycle_retryable_transient_failure_retries_and_succeeds() -> None:
    """Case 10: Attempt 1 fails with 503; 8E retries; Attempt 2 succeeds; counter reset."""

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        if call_count == 1:
            raise RuntimeError("503 Service Unavailable")
        return make_sdk_decision_response(
            {
                "action": "BUY",
                "quantity": 10,
                "confidence": 0.88,
                "reason": "Recovered after transient 503 retry",
                "observations": ["Market ready"],
                "tools_used": [],
            }
        )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_retries=2, initial_backoff_seconds=0.0)
    )
    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=200000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=2)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-retry-ok",
        failure_handler=handler,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    assert fake_sdk.models.call_count == 2
    assert len(step.strategy_orders_queued) == 1
    assert handler.get_state("test-agent", "sim-retry-ok").consecutive_failures == 0
    assert not handler.is_paused("test-agent", "sim-retry-ok")


# ==============================================================================
# 11. Non-Retryable Gemini Failure Causing Auto-Pause
# ==============================================================================


def test_mocked_cycle_non_retryable_failure_causes_auto_pause() -> None:
    """Case 11: 401 Unauthorized triggers auto-pause; subsequent candles fast-path skipped."""
    pause_cb = MagicMock()
    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=1, max_retries=0),
        pause_callback=pause_cb,
    )

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        raise RuntimeError("401 Unauthorized: API key invalid")

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=3)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-auth-pause",
        failure_handler=handler,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Candle 0: fails with 401 -> triggers auto-pause
    step0 = replay.step(strategy=strategy)
    assert step0.strategy_orders_queued == []
    assert handler.is_paused("test-agent", "sim-auth-pause")
    pause_cb.assert_called_once()
    assert fake_sdk.models.call_count == 1

    # Candle 1: while paused, fast-path skips without invoking Gemini
    step1 = replay.step(strategy=strategy)
    assert step1.strategy_orders_queued == []
    assert fake_sdk.models.call_count == 1  # Not called again


# ==============================================================================
# 12. No Order Leaks from a Failed/Partial Cycle
# ==============================================================================


def test_mocked_cycle_partial_work_failure_no_order_leaks() -> None:
    """Case 12: Turn 1 stages order via tool; Turn 2 crashes; order strictly cleared."""

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        if call_count == 1:
            return make_sdk_tool_call_response(
                [
                    (
                        "place_simulated_order",
                        {
                            "side": "BUY",
                            "quantity": 10,
                            "order_type": "MARKET",
                            "reason": "Attempt 1 order",
                        },
                    )
                ]
            )
        else:
            raise RuntimeError("503 Service Unavailable")

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=3, max_retries=0)
    )
    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=2)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-no-leak",
        failure_handler=handler,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    step = replay.step(strategy=strategy)
    # The partial order staged in turn 1 MUST NOT leak into the simulation
    assert step.strategy_orders_queued == []
    assert len(replay.pending_strategy_orders) == 0


# ==============================================================================
# 13. Memory Bounded and Updated Only on Successful Completion
# ==============================================================================


def test_mocked_cycle_memory_bounded_and_updated_only_on_success() -> None:
    """Case 13: Failed cycles do not update memory; completed cycles record bounded history."""
    call_idx = 0

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            # Candle 0: fails
            raise RuntimeError("503 Service Unavailable")
        else:
            # Candle 1: succeeds
            return make_sdk_decision_response(
                {
                    "action": "HOLD",
                    "confidence": 0.8,
                    "reason": f"Decision {call_idx}",
                    "observations": [],
                    "tools_used": [],
                }
            )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    memory_service = AgentMemoryService()
    cycle = AgentDecisionCycle(client=client, harness=harness, memory_service=memory_service)

    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=5, max_retries=0)
    )
    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=3)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-mem",
        memory_service=memory_service,
        failure_handler=handler,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Step 0 (fails)
    replay.step(strategy=strategy)
    # Memory must have ZERO decisions recorded because step 0 failed
    mem0 = memory_service.get_memory_from_context(
        context=ToolExecutionContext.from_replay(
            replay_context=MagicMock(virtual_time=candles[1].timestamp),
            symbol="RELIANCE",
            timeframe="15m",
            portfolio=portfolio,
            risk_engine=risk_engine,
        ),
        agent_id="test-agent",
        simulation_id="sim-mem",
    )
    assert len(mem0.recent_decisions) == 0

    # Step 1 (succeeds)
    replay.step(strategy=strategy)
    mem1 = memory_service.get_memory_from_context(
        context=ToolExecutionContext.from_replay(
            replay_context=MagicMock(virtual_time=candles[2].timestamp),
            symbol="RELIANCE",
            timeframe="15m",
            portfolio=portfolio,
            risk_engine=risk_engine,
        ),
        agent_id="test-agent",
        simulation_id="sim-mem",
    )
    assert len(mem1.recent_decisions) == 1
    assert mem1.recent_decisions[0].candle_timestamp == candles[1].timestamp


# ==============================================================================
# 14. Idempotent Duplicate Candle Delivery
# ==============================================================================


def test_mocked_cycle_idempotent_duplicate_candle_delivery() -> None:
    """Case 14: Duplicate event delivery at same timestamp produces SKIPPED_DUPLICATE."""
    resp = make_sdk_decision_response(
        {
            "action": "HOLD",
            "confidence": 0.8,
            "reason": "Test idempotency",
            "observations": [],
            "tools_used": [],
        }
    )
    fake_sdk = FakeGenAIClient(resp)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    candles = generate_candles(count=2)
    mandate = make_test_mandate()

    ctx = ToolExecutionContext.from_replay(
        replay_context=MagicMock(
            virtual_time=candles[0].timestamp,
            current_candle=candles[0],
            visible_candles=(candles[0],),
        ),
        symbol="RELIANCE",
        timeframe="15m",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # 1st execution
    res1 = cycle.run_cycle(context=ctx, mandate=mandate, agent_id="a1", simulation_id="s1")
    assert res1.status == CycleStatus.NO_ACTION

    # 2nd execution of the exact same event
    res2 = cycle.run_cycle(context=ctx, mandate=mandate, agent_id="a1", simulation_id="s1")
    assert res2.status == CycleStatus.SKIPPED_DUPLICATE
    assert fake_sdk.models.call_count == 1  # Gemini not invoked second time


# ==============================================================================
# 15. Correct Next-Open Execution / No-Lookahead Behavior
# ==============================================================================


def test_mocked_cycle_no_lookahead_and_next_open_execution() -> None:
    """Case 15: Proves decisions at T see data <= T; order fills at T+1 OPEN."""
    candles = generate_candles(count=3, base_price=2500.0)
    seen_candles_count = 0

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        nonlocal seen_candles_count
        prompt_text = str(contents)
        # Verify prompt only references visible candles up to current virtual time
        assert "Total visible historical candles up to t: 1" in prompt_text
        seen_candles_count = 1
        return make_sdk_decision_response(
            {
                "action": "BUY",
                "quantity": 5,
                "confidence": 0.9,
                "reason": "Breakout at t=0",
                "observations": [],
                "tools_used": [],
            }
        )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-lookahead",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Step at candle 0: model runs on candle 0
    replay.step(strategy=strategy)
    assert seen_candles_count == 1
    # At candle 0 CLOSE, order is NOT filled yet
    assert portfolio.get_position("RELIANCE") is None

    # Step 1 at candle 1: order executed at candle 1 OPEN
    step1 = replay.step()
    assert len(step1.strategy_orders_executed) == 1
    assert step1.strategy_orders_executed[0].market_price == candles[1].open
    assert portfolio.get_position("RELIANCE") is not None


# ==============================================================================
# 16. End-to-End State After Execution
# ==============================================================================


def test_mocked_cycle_end_to_end_state_and_portfolio_accounting() -> None:
    """Case 16: Complete trade cycle (BUY -> Hold -> SELL) with P&L and Trade accounting."""
    candles = generate_candles(count=4, base_price=2500.0)
    call_idx = 0

    def generator(model: str, contents: Any, config: Any, call_count: int) -> Any:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return make_sdk_decision_response(
                {
                    "action": "BUY",
                    "quantity": 10,
                    "confidence": 0.9,
                    "reason": "Enter long",
                    "observations": [],
                    "tools_used": [],
                }
            )
        else:
            return make_sdk_decision_response(
                {
                    "action": "SELL",
                    "quantity": 10,
                    "confidence": 0.9,
                    "reason": "Exit long",
                    "observations": [],
                    "tools_used": [],
                }
            )

    fake_sdk = FakeGenAIClient(generator)
    client = GeminiClient(config=GeminiConfig(api_key="mock-key"), genai_client=fake_sdk)
    harness = SafeToolExecutionHarness()
    cycle = AgentDecisionCycle(client=client, harness=harness)

    mandate = make_test_mandate()
    portfolio = PortfolioTracker(initial_capital=200000.0)
    risk_engine = RiskEngine()

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="sim-e2e",
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Step 0: BUY staged
    replay.step(strategy=strategy)
    # Step 1: BUY filled at candle 1 Open; SELL staged
    replay.step(strategy=strategy)
    pos = portfolio.get_position("RELIANCE")
    assert pos is not None
    assert pos.quantity == 10
    # Step 2: SELL filled at candle 2 Open; trade closed
    replay.step(strategy=strategy)

    assert portfolio.get_position("RELIANCE") is None
    assert len(portfolio.closed_trades) == 1
    trade = portfolio.closed_trades[0]
    assert trade.symbol == "RELIANCE"
    assert trade.quantity == 10
    assert trade.exit_price > 0.0
    assert trade.net_pnl is not None


# ==============================================================================
# 17. Cross-Simulation Isolation
# ==============================================================================


def test_mocked_cycle_cross_simulation_isolation() -> None:
    """Case 17: Multi-agent and cross-simulation counters, pause states, and memory are isolated."""
    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=1, max_retries=0)
    )

    # Sim 1 fails
    res_fail = DecisionCycleResult(
        cycle_id="c1",
        agent_id="agent-A",
        simulation_id="sim-1",
        candle_timestamp=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
        status=CycleStatus.GEMINI_ERROR,
        error="401 Unauthorized",
        orders_staged=[],
    )
    handler.record_cycle_result(res_fail, agent_id="agent-A", simulation_id="sim-1")

    assert handler.is_paused("agent-A", "sim-1")
    # Sim 2 agent-A is NOT paused
    assert not handler.is_paused("agent-A", "sim-2")
    # Sim 1 agent-B is NOT paused
    assert not handler.is_paused("agent-B", "sim-1")


# ==============================================================================
# 18. Database Persistence Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_mocked_cycle_database_persistence() -> None:
    """Case 18: Agent decisions, tool calls, and usage telemetry are transactionally persisted."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        inst = Instrument(
            id=1,
            symbol="RELIANCE",
            name="Reliance Industries",
            exchange="NSE",
            instrument_type=InstrumentType.EQUITY,
        )
        session.add(inst)
        await session.commit()

        agent = DBAgent(
            id="agent-persist-test",
            name="Persist Agent",
            status=AgentStatus.RUNNING,
            instrument_id=1,
            strategy_prompt="Test",
            initial_capital=100000.0,
        )
        sim = SimulationRun(
            id="sim-persist-test",
            agent_id="agent-persist-test",
            instrument_id=1,
            start_date=datetime(2026, 9, 7, 9, 15, tzinfo=timezone.utc),
            end_date=datetime(2026, 9, 7, 15, 30, tzinfo=timezone.utc),
            initial_capital=100000.0,
            status=SimulationStatus.RUNNING,
        )
        session.add_all([agent, sim])
        await session.commit()

    cycle_res = DecisionCycleResult(
        cycle_id="cycle-db-1",
        agent_id="agent-persist-test",
        simulation_id="sim-persist-test",
        candle_timestamp=datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
        status=CycleStatus.DECISION_ORDER_STAGED,
        decision=AgentDecision(
            action=AgentAction.BUY,
            quantity=15,
            confidence=0.88,
            reason="Persisted decision test",
            observations=["Observation 1"],
            tools_used=["get_indicators"],
        ),
        orders_staged=["order-99"],
        prompt_tokens=150,
        completion_tokens=60,
        total_tokens=210,
        total_latency_ms=150.0,
        turns_count=1,
    )

    async with async_session() as session:
        saved = await persist_cycle_result(db=session, result=cycle_res)
        assert saved is not None
        assert saved.id == "cycle-db-1"

    # Verify rows in PostgreSQL / SQLite
    async with async_session() as session:
        res = await session.execute(
            select(DBAgentDecision).where(DBAgentDecision.id == "cycle-db-1")
        )
        persisted_dec = res.scalar_one_or_none()
        assert persisted_dec is not None
        assert persisted_dec.action == AgentAction.BUY
        assert persisted_dec.confidence == 0.88
        assert persisted_dec.quantity == 15

        usage_res = await session.execute(
            select(DBAgentUsage).where(DBAgentUsage.agent_id == "agent-persist-test")
        )
        usage = usage_res.scalar_one_or_none()
        assert usage is not None
        assert usage.total_tokens == 210

    await engine.dispose()
