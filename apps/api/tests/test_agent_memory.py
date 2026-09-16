"""Unit and integration tests for Phase 8D: Compact Bounded Agent Memory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import AgentAction as DBAgentAction
from app.database.models import AgentDecision as DBAgentDecision
from app.market_data.schema import CandleData
from app.trading.agent.cycle import (
    AgentDecisionCycle,
    CycleStatus,
    DecisionCycleResult,
    create_agent_strategy,
)
from app.trading.agent.gemini import GeminiClient, GeminiConfig
from app.trading.agent.mandate import AgentMandate
from app.trading.agent.memory import (
    MAX_RECENT_DECISIONS,
    MAX_RECENT_TRADES,
    AgentMemory,
    AgentMemoryService,
    MemoryDecisionRecord,
    MemoryTradeRecord,
)
from app.trading.agent.schemas import AgentAction, AgentDecision
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderSide, TradeRecord
from app.trading.simulation.replay import ChronologicalReplayEngine

# ==============================================================================
# Helpers & Fixtures
# ==============================================================================


@pytest.fixture
def sample_mandate() -> AgentMandate:
    return AgentMandate(
        instrument="RELIANCE",
        timeframe="15m",
        strategy_style="MOMENTUM",
        objectives=["Capital appreciation"],
        preferred_indicators=["EMA20", "RSI14"],
        risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_daily_loss=0.05,
    )


@pytest.fixture
def sample_context() -> ToolExecutionContext:
    base_time = datetime(2025, 1, 15, 9, 30, tzinfo=timezone.utc)
    candle = CandleData(
        timestamp=base_time,
        open=2500.0,
        high=2510.0,
        low=2495.0,
        close=2505.0,
        volume=10000.0,
    )
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    return ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        current_candle=candle,
        visible_candles=[candle],
        portfolio=portfolio,
        risk_engine=risk_engine,
        virtual_time=base_time,
        staged_orders=[],
    )


# ==============================================================================
# 1. Boundedness & Schema Validations
# ==============================================================================


def test_decision_record_truncation_bounds():
    """Oversized reason (>150 chars) and observations (>2, >80 chars) are strictly truncated."""
    long_reason = "A" * 200
    long_obs = ["Obs 1: " + "B" * 100, "Obs 2: " + "C" * 100, "Obs 3: extra item"]

    rec = MemoryDecisionRecord(
        candle_timestamp=datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc),
        action=AgentAction.BUY,
        confidence=0.85,
        quantity=5,
        reason=long_reason,
        observations=long_obs,
    )

    assert len(rec.reason) == 150
    assert rec.reason.endswith("...")
    assert len(rec.observations) == 2
    assert len(rec.observations[0]) == 80
    assert rec.observations[0].endswith("...")
    assert len(rec.observations[1]) == 80
    assert rec.observations[1].endswith("...")


def test_agent_memory_bounds_enforced():
    """AgentMemory schema forbids more than 5 decisions and 10 trades."""
    ts = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)

    decisions = [
        MemoryDecisionRecord(
            candle_timestamp=ts - timedelta(minutes=15 * i),
            action=AgentAction.HOLD,
            confidence=0.8,
            reason=f"Hold step {i}",
        )
        for i in range(6)  # 6 decisions (exceeds max 5)
    ]

    with pytest.raises(ValidationError):
        AgentMemory(recent_decisions=decisions)

    trades = [
        MemoryTradeRecord(
            trade_id=f"tr-{i}",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            quantity=5,
            entry_price=2500.0,
            exit_price=2510.0,
            gross_pnl=50.0,
            net_pnl=48.0,
            entry_time=ts - timedelta(hours=1),
            exit_time=ts - timedelta(minutes=i),
            exit_reason="MANUAL_EXIT",
        )
        for i in range(11)  # 11 trades (exceeds max 10)
    ]

    with pytest.raises(ValidationError):
        AgentMemory(recent_trades=trades)


def test_service_decision_memory_bounded_to_max_5(sample_context: ToolExecutionContext):
    """AgentMemoryService limits recorded decisions to the 5 most recent."""
    service = AgentMemoryService()
    base_time = sample_context.virtual_time

    # Record 8 past decisions at 15m intervals before virtual_time
    for i in range(8, 0, -1):
        dec_time = base_time - timedelta(minutes=15 * i)
        dummy_res = DecisionCycleResult(
            cycle_id=f"cycle-{i}",
            agent_id="test-agent",
            simulation_id="sim-1",
            candle_timestamp=dec_time,
            status=CycleStatus.SUCCESS,
            decision=AgentDecision(
                action=AgentAction.HOLD,
                confidence=0.7 + (i * 0.02),
                reason=f"Historical decision {i}",
                observations=[],
                tools_used=[],
            ),
            reconciliation=None,
            tool_executions=[],
            orders_staged=[],
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            total_latency_ms=5.0,
            turns_count=1,
        )
        service.record_decision("test-agent", "sim-1", dummy_res)

    memory = service.get_memory_from_context(sample_context, "test-agent", "sim-1")

    assert len(memory.recent_decisions) == MAX_RECENT_DECISIONS  # 5
    # Must be ordered most-recent-first (i=1 is latest)
    assert memory.recent_decisions[0].reason == "Historical decision 1"
    assert memory.recent_decisions[1].reason == "Historical decision 2"
    assert memory.recent_decisions[4].reason == "Historical decision 5"


def test_service_trade_memory_bounded_to_max_10(sample_context: ToolExecutionContext):
    """AgentMemoryService limits portfolio closed trades to the 10 most recent."""
    service = AgentMemoryService()
    base_time = sample_context.virtual_time

    # Populate portfolio with 15 closed trades
    for i in range(15):
        tr = TradeRecord(
            trade_id=f"tr-{i}",
            symbol="RELIANCE",
            side=OrderSide.BUY,
            quantity=5,
            entry_price=2500.0,
            exit_price=2510.0 + i,
            gross_pnl=50.0 + i,
            net_pnl=48.0 + i,
            entry_time=base_time - timedelta(hours=2),
            exit_time=base_time - timedelta(minutes=10 * (15 - i)),  # tr-14 is most recent
            exit_reason="TAKE_PROFIT",
        )
        sample_context.portfolio.closed_trades.append(tr)

    memory = service.get_memory_from_context(sample_context, "test-agent", "sim-1")

    assert len(memory.recent_trades) == MAX_RECENT_TRADES  # 10
    # Must be ordered most-recent-first (tr-14 is first)
    assert memory.recent_trades[0].trade_id == "tr-14"
    assert memory.recent_trades[1].trade_id == "tr-13"
    assert memory.recent_trades[9].trade_id == "tr-5"


# ==============================================================================
# 2. Temporal Safety (Strict No-Lookahead)
# ==============================================================================


def test_memory_excludes_same_candle_and_future_decisions(
    sample_context: ToolExecutionContext,
):
    """Decisions at or after context.virtual_time t are strictly excluded from memory."""
    service = AgentMemoryService()
    current_time = sample_context.virtual_time

    # 1. Past decision (< t) -> should be included
    past_res = DecisionCycleResult(
        cycle_id="past-1",
        agent_id="test-agent",
        simulation_id="sim-1",
        candle_timestamp=current_time - timedelta(minutes=15),
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.BUY,
            confidence=0.8,
            reason="Past decision",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        total_latency_ms=5.0,
        turns_count=1,
    )
    service.record_decision("test-agent", "sim-1", past_res)

    # 2. Same-candle decision (= t) -> must be excluded (cannot self-reference active decision)
    current_res = DecisionCycleResult(
        cycle_id="current-1",
        agent_id="test-agent",
        simulation_id="sim-1",
        candle_timestamp=current_time,
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.SELL,
            confidence=0.9,
            reason="Same-candle decision",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        total_latency_ms=5.0,
        turns_count=1,
    )
    service.record_decision("test-agent", "sim-1", current_res)

    # 3. Future decision (> t) -> must be excluded
    future_res = DecisionCycleResult(
        cycle_id="future-1",
        agent_id="test-agent",
        simulation_id="sim-1",
        candle_timestamp=current_time + timedelta(minutes=15),
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.HOLD,
            confidence=0.7,
            reason="Future decision",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        total_latency_ms=5.0,
        turns_count=1,
    )
    service.record_decision("test-agent", "sim-1", future_res)

    memory = service.get_memory_from_context(sample_context, "test-agent", "sim-1")

    assert len(memory.recent_decisions) == 1
    assert memory.recent_decisions[0].reason == "Past decision"


def test_memory_excludes_future_trades(sample_context: ToolExecutionContext):
    """Trades exiting after context.virtual_time t are strictly excluded."""
    service = AgentMemoryService()
    current_time = sample_context.virtual_time

    # Past trade (<= t)
    past_tr = TradeRecord(
        trade_id="past-trade",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        entry_price=2500.0,
        exit_price=2520.0,
        gross_pnl=100.0,
        net_pnl=95.0,
        entry_time=current_time - timedelta(hours=1),
        exit_time=current_time - timedelta(minutes=5),
        exit_reason="TAKE_PROFIT",
    )
    # Future trade (> t)
    future_tr = TradeRecord(
        trade_id="future-trade",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        entry_price=2500.0,
        exit_price=2530.0,
        gross_pnl=150.0,
        net_pnl=145.0,
        entry_time=current_time,
        exit_time=current_time + timedelta(minutes=30),
        exit_reason="TAKE_PROFIT",
    )
    sample_context.portfolio.closed_trades.extend([past_tr, future_tr])

    memory = service.get_memory_from_context(sample_context, "test-agent", "sim-1")

    assert len(memory.recent_trades) == 1
    assert memory.recent_trades[0].trade_id == "past-trade"


# ==============================================================================
# 3. Agent & Simulation Isolation
# ==============================================================================


def test_agent_and_simulation_isolation(sample_context: ToolExecutionContext):
    """Memory is strictly segregated by (simulation_id, agent_id)."""
    service = AgentMemoryService()
    ts = sample_context.virtual_time - timedelta(minutes=15)

    res_agent1_sim1 = DecisionCycleResult(
        cycle_id="c1",
        agent_id="agent-1",
        simulation_id="sim-1",
        candle_timestamp=ts,
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.BUY,
            confidence=0.8,
            reason="A1 S1",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        total_latency_ms=5.0,
        turns_count=1,
    )
    res_agent2_sim1 = DecisionCycleResult(
        cycle_id="c2",
        agent_id="agent-2",
        simulation_id="sim-1",
        candle_timestamp=ts,
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.SELL,
            confidence=0.7,
            reason="A2 S1",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        total_latency_ms=5.0,
        turns_count=1,
    )
    res_agent1_sim2 = DecisionCycleResult(
        cycle_id="c3",
        agent_id="agent-1",
        simulation_id="sim-2",
        candle_timestamp=ts,
        status=CycleStatus.SUCCESS,
        decision=AgentDecision(
            action=AgentAction.HOLD,
            confidence=0.9,
            reason="A1 S2",
            observations=[],
            tools_used=[],
        ),
        reconciliation=None,
        tool_executions=[],
        orders_staged=[],
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        total_latency_ms=5.0,
        turns_count=1,
    )

    service.record_decision("agent-1", "sim-1", res_agent1_sim1)
    service.record_decision("agent-2", "sim-1", res_agent2_sim1)
    service.record_decision("agent-1", "sim-2", res_agent1_sim2)

    mem_a1_s1 = service.get_memory_from_context(sample_context, "agent-1", "sim-1")
    mem_a2_s1 = service.get_memory_from_context(sample_context, "agent-2", "sim-1")
    mem_a1_s2 = service.get_memory_from_context(sample_context, "agent-1", "sim-2")

    assert len(mem_a1_s1.recent_decisions) == 1
    assert mem_a1_s1.recent_decisions[0].reason == "A1 S1"

    assert len(mem_a2_s1.recent_decisions) == 1
    assert mem_a2_s1.recent_decisions[0].reason == "A2 S1"

    assert len(mem_a1_s2.recent_decisions) == 1
    assert mem_a1_s2.recent_decisions[0].reason == "A1 S2"


def test_symbol_isolation_for_trades(sample_context: ToolExecutionContext):
    """Closed trades for a different symbol are filtered out of current instrument memory."""
    service = AgentMemoryService()
    current_time = sample_context.virtual_time

    # Trade for RELIANCE (current symbol)
    rel_tr = TradeRecord(
        trade_id="tr-reliance",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=5,
        entry_price=2500.0,
        exit_price=2520.0,
        gross_pnl=100.0,
        net_pnl=95.0,
        entry_time=current_time - timedelta(hours=1),
        exit_time=current_time - timedelta(minutes=5),
        exit_reason="TAKE_PROFIT",
    )
    # Trade for TCS (unrelated instrument)
    tcs_tr = TradeRecord(
        trade_id="tr-tcs",
        symbol="TCS",
        side=OrderSide.BUY,
        quantity=2,
        entry_price=3500.0,
        exit_price=3550.0,
        gross_pnl=100.0,
        net_pnl=95.0,
        entry_time=current_time - timedelta(hours=1),
        exit_time=current_time - timedelta(minutes=5),
        exit_reason="TAKE_PROFIT",
    )
    sample_context.portfolio.closed_trades.extend([rel_tr, tcs_tr])

    memory = service.get_memory_from_context(sample_context, "test-agent", "sim-1")

    assert len(memory.recent_trades) == 1
    assert memory.recent_trades[0].symbol == "RELIANCE"


# ==============================================================================
# 4. Prompt Demarcation & Current State Separation
# ==============================================================================


def test_prompt_demarcation_between_current_state_and_memory(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """Prompt cleanly separates current account/position state from historical memory context."""
    from app.trading.agent.cycle.prompts import build_cycle_prompt

    memory = AgentMemory(
        recent_decisions=[
            MemoryDecisionRecord(
                candle_timestamp=sample_context.virtual_time - timedelta(minutes=15),
                action=AgentAction.BUY,
                confidence=0.88,
                quantity=5,
                reason="Breakout confirmed",
                observations=["RSI oversold"],
                status="DECISION_ORDER_STAGED",
            )
        ],
        recent_trades=[
            MemoryTradeRecord(
                trade_id="tr-101",
                symbol="RELIANCE",
                side=OrderSide.BUY,
                quantity=5,
                entry_price=2480.0,
                exit_price=2510.0,
                gross_pnl=150.0,
                net_pnl=142.50,
                entry_time=sample_context.virtual_time - timedelta(hours=2),
                exit_time=sample_context.virtual_time - timedelta(minutes=30),
                exit_reason="TAKE_PROFIT",
            )
        ],
    )

    prompt = build_cycle_prompt(sample_context, sample_mandate, memory=memory)

    # 1. Authoritative Current State Section
    assert "=== CURRENT ACCOUNT STATE AT t ===" in prompt
    assert "Position: FLAT (no active position)" in prompt

    # 2. Historical Memory Section
    assert "=== HISTORICAL AGENT MEMORY (PRIOR CONTEXT ONLY) ===" in prompt
    assert "They do NOT represent the current account balance" in prompt
    assert "[Recent Past Decisions (last 1 <= 5)]:" in prompt
    assert (
        'Action=BUY, Conf=0.88, Qty=5, Status=DECISION_ORDER_STAGED, Reason="Breakout confirmed"'
        in prompt
    )
    assert "[Recent Closed Trades (last 1 <= 10)]:" in prompt
    assert "Trade tr-101 (RELIANCE): BUY 5 shares @ ₹2480.00 -> Exit @ ₹2510.00" in prompt


# ==============================================================================
# 5. Database Persistence Retrieval
# ==============================================================================


@pytest.mark.asyncio
async def test_database_memory_retrieval(sample_context: ToolExecutionContext):
    """AgentMemoryService queries persisted AgentDecision records from PostgreSQL."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    as_of = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)

    # Insert 6 decision records (5 before as_of, 1 after as_of)
    async with async_session() as db:
        for i in range(5):
            ts = as_of - timedelta(minutes=15 * (i + 1))
            db.add(
                DBAgentDecision(
                    id=f"db-dec-{i}",
                    agent_id="agent-db",
                    simulation_id="sim-db",
                    candle_timestamp=ts,
                    action=DBAgentAction.BUY if i % 2 == 0 else DBAgentAction.HOLD,
                    confidence=0.85,
                    reason=f"DB reason {i}",
                    observations=["Obs test"],
                    tools_used=["get_market_data"],
                )
            )
        # Future decision after as_of
        db.add(
            DBAgentDecision(
                id="db-dec-future",
                agent_id="agent-db",
                simulation_id="sim-db",
                candle_timestamp=as_of + timedelta(minutes=15),
                action=DBAgentAction.SELL,
                confidence=0.95,
                reason="Future decision should be excluded",
                observations=[],
                tools_used=[],
            )
        )
        await db.commit()

    service = AgentMemoryService()
    async with async_session() as db:
        mem = await service.get_memory_from_db(
            db=db,
            agent_id="agent-db",
            simulation_id="sim-db",
            as_of_time=as_of,
            portfolio=sample_context.portfolio,
            symbol="RELIANCE",
        )

    assert len(mem.recent_decisions) == 5
    # Future record excluded
    for d in mem.recent_decisions:
        assert d.candle_timestamp < as_of
        assert "Future decision" not in d.reason

    await engine.dispose()


# ==============================================================================
# 6. Replay Engine Multi-Step Memory Propagation
# ==============================================================================


def test_replay_memory_propagation_across_candles(sample_mandate: AgentMandate):
    """In multi-candle simulation, decisions and executed trades accumulate into memory across steps."""
    # Build 4 15-minute candles
    base_time = datetime(2025, 1, 15, 9, 15, tzinfo=timezone.utc)
    candles = [
        CandleData(
            timestamp=base_time + timedelta(minutes=15 * i),
            open=2500.0 + i * 5,
            high=2510.0 + i * 5,
            low=2495.0 + i * 5,
            close=2505.0 + i * 5,
            volume=10000.0,
        )
        for i in range(4)
    ]

    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    replay_engine = ChronologicalReplayEngine(
        candles=candles,
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    from tests.test_agent_decision_cycle import (
        FakeGenAIClient,
        make_sdk_decision_response,
    )

    prompts_received: List[str] = []

    def generator(model, contents, config, turn_count):
        prompt_text = ""
        for item in contents:
            if hasattr(item, "parts"):
                for p in item.parts:
                    if hasattr(p, "text"):
                        prompt_text += p.text
        prompts_received.append(prompt_text)

        if "NEW COMPLETED CANDLE EVENT (t = 2025-01-15T09:15:00" in prompt_text:
            return make_sdk_decision_response(
                {
                    "action": "BUY",
                    "confidence": 0.9,
                    "quantity": 5,
                    "reason": "Step 0 Buy Action",
                    "observations": [],
                    "tools_used": [],
                }
            )
        elif "NEW COMPLETED CANDLE EVENT (t = 2025-01-15T09:30:00" in prompt_text:
            return make_sdk_decision_response(
                {
                    "action": "SELL",
                    "confidence": 0.85,
                    "quantity": 5,
                    "reason": "Step 1 Close Action",
                    "observations": [],
                    "tools_used": [],
                }
            )
        else:
            return make_sdk_decision_response(
                {
                    "action": "HOLD",
                    "confidence": 0.75,
                    "reason": "Step 2/3 Flat Action",
                    "observations": [],
                    "tools_used": [],
                }
            )

    fake_client = FakeGenAIClient(response_generator=generator)
    client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)

    memory_service = AgentMemoryService()
    cycle = AgentDecisionCycle(client=client, memory_service=memory_service)

    strategy = create_agent_strategy(
        cycle=cycle,
        mandate=sample_mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="replay-agent",
        simulation_id="replay-sim",
        memory_service=memory_service,
    )

    summary = replay_engine.run(strategy=strategy)

    assert len(summary.trades) == 1
    assert len(prompts_received) == 4

    # Step 0 (09:15:00): Memory was empty
    assert "=== HISTORICAL AGENT MEMORY (PRIOR CONTEXT ONLY) ===" not in prompts_received[0]

    # Step 1 (09:30:00): Prompt received memory of Step 0 Decision
    assert "=== HISTORICAL AGENT MEMORY (PRIOR CONTEXT ONLY) ===" in prompts_received[1]
    assert "Step 0 Buy Action" in prompts_received[1]

    # Step 2 (09:45:00): Prompt received both Step 0 & Step 1 Decisions
    assert "Step 1 Close Action" in prompts_received[2]
    assert "Step 0 Buy Action" in prompts_received[2]

    # Step 3 (10:00:00): Trade was executed and closed at Step 2 open, so Step 3 prompt sees the closed trade
    assert "Recent Closed Trades (last 1 <= 10)" in prompts_received[3]


# ==============================================================================
# 7. Failure Containment
# ==============================================================================


def test_memory_failure_graceful_fallback(
    sample_context: ToolExecutionContext, sample_mandate: AgentMandate
):
    """If an exception occurs during memory extraction, empty memory is returned without failing cycle."""
    from unittest.mock import MagicMock

    from tests.test_agent_decision_cycle import (
        FakeGenAIClient,
        make_sdk_decision_response,
    )

    # Corrupt closed_trades so that an unexpected exception is raised during trade iteration
    sample_context.portfolio.closed_trades = MagicMock(
        side_effect=RuntimeError("Corrupted trade list")
    )

    service = AgentMemoryService()
    mem = service.get_memory_from_context(sample_context, "test-agent", "sim-1")

    assert mem.is_empty
    assert len(mem.recent_decisions) == 0
    assert len(mem.recent_trades) == 0

    # Decision cycle still runs cleanly
    fake_client = FakeGenAIClient(
        response_generator=lambda m, c, cfg, cnt: make_sdk_decision_response(
            {
                "action": "HOLD",
                "confidence": 0.8,
                "reason": "Safe fallback test",
                "observations": [],
                "tools_used": [],
            }
        )
    )
    gemini_client = GeminiClient(config=GeminiConfig(api_key="k"), genai_client=fake_client)
    cycle = AgentDecisionCycle(client=gemini_client, memory_service=service)

    res = cycle.run_cycle(context=sample_context, mandate=sample_mandate)

    assert res.status == CycleStatus.NO_ACTION
    assert res.decision.action == AgentAction.HOLD


def test_clear_history_scoped_lifecycle(sample_context: ToolExecutionContext):
    """clear_history correctly resets history by simulation_id, agent_id, or globally."""
    service = AgentMemoryService()
    base_time = sample_context.virtual_time - timedelta(minutes=15)

    def _make_res(agent: str, sim: Optional[str], r: str) -> DecisionCycleResult:
        return DecisionCycleResult(
            cycle_id=f"c-{agent}-{sim}",
            agent_id=agent,
            simulation_id=sim,
            candle_timestamp=base_time,
            status=CycleStatus.SUCCESS,
            decision=AgentDecision(
                action=AgentAction.HOLD,
                confidence=0.8,
                reason=r,
                observations=[],
                tools_used=[],
            ),
            reconciliation=None,
            tool_executions=[],
            orders_staged=[],
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            total_latency_ms=5.0,
            turns_count=1,
        )

    service.record_decision("agent-1", "sim-A", _make_res("agent-1", "sim-A", "A1-SimA"))
    service.record_decision("agent-2", "sim-A", _make_res("agent-2", "sim-A", "A2-SimA"))
    service.record_decision("agent-1", "sim-B", _make_res("agent-1", "sim-B", "A1-SimB"))

    # 1. Clear by simulation_id alone: removes all agents in sim-A
    service.clear_history(simulation_id="sim-A")
    assert service.get_memory_from_context(sample_context, "agent-1", "sim-A").is_empty
    assert service.get_memory_from_context(sample_context, "agent-2", "sim-A").is_empty
    # sim-B is unaffected
    assert not service.get_memory_from_context(sample_context, "agent-1", "sim-B").is_empty

    # 2. Clear by agent_id alone: removes agent-1 in sim-B
    service.clear_history(agent_id="agent-1")
    assert service.get_memory_from_context(sample_context, "agent-1", "sim-B").is_empty

    # 3. Global clear
    service.record_decision("agent-3", "sim-C", _make_res("agent-3", "sim-C", "A3-SimC"))
    assert not service.get_memory_from_context(sample_context, "agent-3", "sim-C").is_empty
    service.clear_history()
    assert service.get_memory_from_context(sample_context, "agent-3", "sim-C").is_empty


@pytest.mark.asyncio
async def test_database_memory_simulation_isolation_null_vs_populated(
    sample_context: ToolExecutionContext,
):
    """Database query isolates simulation_id=None (live) from specific backtest simulation runs."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    as_of = datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc)
    past_time = as_of - timedelta(minutes=15)

    async with async_session() as db:
        # Decision for backtest sim-1
        db.add(
            DBAgentDecision(
                id="dec-sim1",
                agent_id="agent-iso",
                simulation_id="sim-1",
                candle_timestamp=past_time,
                action=DBAgentAction.BUY,
                confidence=0.8,
                reason="Sim 1 decision",
                observations=[],
                tools_used=[],
            )
        )
        # Decision for live session (simulation_id is None)
        db.add(
            DBAgentDecision(
                id="dec-live",
                agent_id="agent-iso",
                simulation_id=None,
                candle_timestamp=past_time,
                action=DBAgentAction.SELL,
                confidence=0.9,
                reason="Live session decision",
                observations=[],
                tools_used=[],
            )
        )
        await db.commit()

    service = AgentMemoryService()
    async with async_session() as db:
        # Querying sim-1 only gets sim-1
        mem_sim1 = await service.get_memory_from_db(
            db=db,
            agent_id="agent-iso",
            simulation_id="sim-1",
            as_of_time=as_of,
        )
        assert len(mem_sim1.recent_decisions) == 1
        assert mem_sim1.recent_decisions[0].reason == "Sim 1 decision"

        # Querying simulation_id=None (live) only gets live decision, not sim-1
        mem_live = await service.get_memory_from_db(
            db=db,
            agent_id="agent-iso",
            simulation_id=None,
            as_of_time=as_of,
        )
        assert len(mem_live.recent_decisions) == 1
        assert mem_live.recent_decisions[0].reason == "Live session decision"

    await engine.dispose()
