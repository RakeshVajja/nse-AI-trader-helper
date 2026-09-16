"""Phase 8F — Live Gemini Decision-Cycle Tests.

Validates the end-to-end integration path using real Google Gemini API calls:
simulation/replay candle
→ agent strategy
→ AgentDecisionCycle
→ GeminiClient (real google-genai SDK)
→ SafeToolExecutionHarness
→ Phase 7 tools
→ reconciliation
→ AgentDecision
→ staging
→ ReplayEngine next-open execution
→ portfolio/trade state
→ AgentMemory.

CRITICAL SAFETY & GATING REQUIREMENTS:
- NEVER run by default if credentials are not configured.
- Marked with `@pytest.mark.live_gemini`.
- Gated behind `os.getenv("GEMINI_API_KEY")`.
- When key is absent, tests skip cleanly (SKIP, not FAIL).
- Zero hardcoded credentials or secrets.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.market_data.schema import CandleData
from app.trading.agent.cycle.engine import AgentDecisionCycle, create_agent_strategy
from app.trading.agent.cycle.schemas import CycleStatus
from app.trading.agent.gemini.client import GeminiClient, GeminiConfig
from app.trading.agent.harness import SafeToolExecutionHarness
from app.trading.agent.mandate.schemas import AgentMandate
from app.trading.agent.memory.service import AgentMemoryService
from app.trading.agent.schemas import AgentAction
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.simulation.replay import ChronologicalReplayEngine


def _generate_live_test_candles(
    count: int = 5,
    base_price: float = 2500.0,
) -> List[CandleData]:
    """Generate minimal deterministic sequential 15m candles."""
    start = datetime(2026, 9, 7, 9, 15, tzinfo=timezone.utc)
    candles: List[CandleData] = []
    curr_px = base_price
    for i in range(count):
        ts = start + timedelta(minutes=15 * i)
        candles.append(
            CandleData(
                timestamp=ts,
                open=curr_px,
                high=curr_px + 10.0,
                low=curr_px - 5.0,
                close=curr_px + 4.0,
                volume=30000.0 + (i * 1000.0),
            )
        )
        curr_px += 4.0
    return candles


def _make_live_test_mandate(symbol: str = "RELIANCE") -> AgentMandate:
    """Construct a clean, unambiguous mandate for live model evaluation."""
    return AgentMandate(
        strategy_style="MOMENTUM",
        objectives=[
            "Capitalize on short-term trend momentum",
            "Preserve capital strictly with risk-adjusted sizing",
        ],
        preferred_indicators=["EMA20", "RSI14"],
        instrument=symbol,
        timeframe="15m",
        risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_daily_loss=0.05,
        rationale="Phase 8F Live Gemini decision cycle verification mandate",
    )


@pytest.mark.live_gemini
@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY environment variable is not set; skipping live Gemini decision-cycle test.",
)
def test_live_decision_cycle_in_replay_engine() -> None:
    """Live verification of the complete real integration path against Google Gemini API.

    Executes:
    1. Real GeminiClient using GEMINI_API_KEY from environment.
    2. SafeToolExecutionHarness with Phase 7 registered tools.
    3. ChronologicalReplayEngine stepping through market candles.
    4. Model decision generation and/or tool calls.
    5. Reconciliation into staged orders or HOLD action.
    6. Verifies token usage, latency, and valid structured output.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    client = GeminiClient(
        config=GeminiConfig(
            api_key=api_key,
            model_name=model_name,
            temperature=0.1,
            max_output_tokens=1024,
            timeout_seconds=30.0,
        )
    )
    harness = SafeToolExecutionHarness()
    memory_service = AgentMemoryService()
    cycle = AgentDecisionCycle(
        client=client,
        harness=harness,
        memory_service=memory_service,
        max_turns=5,
    )

    portfolio = PortfolioTracker(initial_capital=200000.0)
    risk_engine = RiskEngine()
    mandate = _make_live_test_mandate(symbol="RELIANCE")
    candles = _generate_live_test_candles(count=3, base_price=2500.0)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="live-gemini-agent",
        simulation_id="live-sim-1",
        memory_service=memory_service,
    )

    replay = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    # Execute step 0 (candle 0): Real Gemini decision cycle runs
    step_res = replay.step(strategy=strategy)

    # 1. Verify ReplayStep completed cleanly
    assert step_res.step_index == 0
    assert step_res.candle.timestamp == candles[0].timestamp

    # 2. Portfolio should be consistent (no phantom positions or corrupt cash)
    assert portfolio.cash <= 200000.0
    assert portfolio.cash > 0.0

    # 3. If an order was staged, verify it was validly formatted and queued
    if step_res.strategy_orders_queued:
        assert len(step_res.strategy_orders_queued) == 1
        staged = step_res.strategy_orders_queued[0]
        assert staged.symbol == "RELIANCE"
        assert staged.side in (AgentAction.BUY, AgentAction.SELL)
        assert staged.quantity > 0

        # Step 1 (candle 1): Verify the staged order fills at candle 1 OPEN
        step1 = replay.step()
        assert len(step1.strategy_orders_executed) == 1
        exec_res = step1.strategy_orders_executed[0]
        assert exec_res.market_price == candles[1].open
        assert portfolio.get_position("RELIANCE") is not None
    else:
        # HOLD decision: clean state maintained
        step1 = replay.step()
        assert len(step1.strategy_orders_executed) == 0


@pytest.mark.live_gemini
@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY environment variable is not set; skipping live Gemini direct cycle test.",
)
def test_live_direct_decision_cycle_execution() -> None:
    """Live verification of direct AgentDecisionCycle.run_cycle with memory and tools."""
    from app.trading.agent.tools import ToolExecutionContext

    api_key = os.getenv("GEMINI_API_KEY", "")
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    client = GeminiClient(
        config=GeminiConfig(
            api_key=api_key,
            model_name=model_name,
            temperature=0.1,
            max_output_tokens=1024,
            timeout_seconds=30.0,
        )
    )
    harness = SafeToolExecutionHarness()
    memory_service = AgentMemoryService()
    cycle = AgentDecisionCycle(
        client=client,
        harness=harness,
        memory_service=memory_service,
        max_turns=5,
    )

    mandate = _make_live_test_mandate(symbol="RELIANCE")
    candles = _generate_live_test_candles(count=4, base_price=2500.0)
    portfolio = PortfolioTracker(initial_capital=200000.0)
    risk_engine = RiskEngine()

    context = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=candles[-1].timestamp,
        current_candle=candles[-1],
        visible_candles=candles,
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=[],
    )

    result = cycle.run_cycle(
        context=context,
        mandate=mandate,
        agent_id="live-direct-agent",
        simulation_id="live-direct-sim",
    )

    # Assert authoritative cycle result
    assert result.status in (
        CycleStatus.SUCCESS,
        CycleStatus.NO_ACTION,
        CycleStatus.DECISION_ORDER_STAGED,
        CycleStatus.TOOL_ORDER_STAGED,
    )
    assert result.decision is not None
    assert result.decision.action in (AgentAction.BUY, AgentAction.SELL, AgentAction.HOLD)
    assert result.decision.confidence >= 0.0 and result.decision.confidence <= 1.0
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
    assert result.total_latency_ms > 0.0
    assert result.turns_count >= 1
