"""Comprehensive unit and integration tests for Phase 8E: Agent Failure Handling & Auto-Pause."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.models import Agent as DBAgent
from app.database.models import AgentStatus
from app.market_data.schema import CandleData
from app.trading.agent.cycle import (
    AgentDecisionCycle,
    CycleStatus,
    CycleToolExecution,
    DecisionCycleResult,
    create_agent_strategy,
)
from app.trading.agent.mandate import AgentMandate
from app.trading.agent.safety import (
    AgentFailureHandler,
    AgentFailureState,
    AgentSafetyService,
    FailureCategory,
    FailurePolicyConfig,
    classify_cycle_result,
    sanitize_error_message,
)
from app.trading.agent.schemas import AgentAction, AgentDecision
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderRequest, OrderSide, OrderType

# ==============================================================================
# Helpers & Fixtures
# ==============================================================================


def make_test_mandate(
    instrument: str = "RELIANCE",
    timeframe: str = "15m",
) -> AgentMandate:
    return AgentMandate(
        strategy_style="momentum",
        objectives=["Identify trend continuation", "Control downside"],
        preferred_indicators=["RSI14", "EMA20"],
        instrument=instrument,
        timeframe=timeframe,
        risk_per_trade=0.02,
        max_position_exposure=0.25,
        max_daily_loss=0.05,
        rationale="Safety test mandate",
    )


def make_mock_cycle_result(
    status: CycleStatus = CycleStatus.SUCCESS,
    decision: Optional[AgentDecision] = None,
    error: Optional[str] = None,
    orders_staged: Optional[List[str]] = None,
    candle_timestamp: Optional[datetime] = None,
    agent_id: str = "agent-1",
    simulation_id: Optional[str] = "sim-1",
    cycle_id: Optional[str] = None,
    tool_executions: Optional[List[CycleToolExecution]] = None,
) -> DecisionCycleResult:
    return DecisionCycleResult(
        cycle_id=cycle_id or f"cycle-{int(datetime.now(timezone.utc).timestamp() * 1000)}",
        agent_id=agent_id,
        simulation_id=simulation_id,
        candle_timestamp=candle_timestamp or datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc),
        status=status,
        decision=decision,
        orders_staged=orders_staged or [],
        tool_executions=tool_executions or [],
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        total_latency_ms=120.0,
        turns_count=1,
        error=error,
    )


# ==============================================================================
# 1. Failure Classification Tests
# ==============================================================================


def test_classify_success_outcomes() -> None:
    """Successful or benign outcomes must not be classified as failures."""
    non_failure_statuses = [
        CycleStatus.SUCCESS,
        CycleStatus.TOOL_ORDER_STAGED,
        CycleStatus.DECISION_ORDER_STAGED,
        CycleStatus.NO_ACTION,
        CycleStatus.SKIPPED_DUPLICATE,
    ]
    for status in non_failure_statuses:
        result = make_mock_cycle_result(status=status)
        category, retryable, sanitized = classify_cycle_result(result)
        assert category is None
        assert retryable is False
        assert sanitized is None


def test_classify_normal_risk_rejection() -> None:
    """Normal risk rejection must not be counted as an agent failure."""
    risk_errors = [
        "Risk check failed: Max order quantity exceeded",
        "Risk limit violated: Capital limit of 50000 exceeded",
        "Order rejected by risk engine: Position limit",
    ]
    for err in risk_errors:
        result = make_mock_cycle_result(status=CycleStatus.GEMINI_ERROR, error=err)
        category, retryable, sanitized = classify_cycle_result(result)
        assert category is None, f"Expected None for risk error: {err}"
        assert retryable is False
        assert sanitized is None


def test_classify_api_transient_failures() -> None:
    """Transient API errors (503, connection reset, timeout) must be retryable."""
    transient_cases = [
        "Gemini 503 Service Unavailable",
        "Connection reset by peer",
        "Request timed out after 30s",
        "502 Bad Gateway from Google API",
        "API deadline exceeded",
    ]
    for err in transient_cases:
        result = make_mock_cycle_result(
            status=CycleStatus.GEMINI_ERROR,
            error=err,
        )
        category, retryable, sanitized = classify_cycle_result(result)
        assert category == FailureCategory.API_TRANSIENT
        assert retryable is True
        assert sanitized == err


def test_classify_rate_limit_failures() -> None:
    """Rate limit / quota exhaustion must be categorized as RATE_LIMIT."""
    rate_cases = [
        "429 Too Many Requests: Quota exceeded",
        "Resource exhausted: quota limit per minute reached",
    ]
    for err in rate_cases:
        result = make_mock_cycle_result(
            status=CycleStatus.GEMINI_ERROR,
            error=err,
        )
        category, retryable, _ = classify_cycle_result(result)
        assert category == FailureCategory.RATE_LIMIT
        assert retryable is False


def test_classify_authentication_failures() -> None:
    """Auth failures (401, 403, API_KEY_INVALID) must be AUTHENTICATION and non-retryable."""
    auth_cases = [
        "401 Unauthorized: API key invalid",
        "403 Forbidden: Caller lacks permission",
    ]
    for err in auth_cases:
        result = make_mock_cycle_result(
            status=CycleStatus.GEMINI_ERROR,
            error=err,
        )
        category, retryable, _ = classify_cycle_result(result)
        assert category == FailureCategory.AUTHENTICATION
        assert retryable is False


def test_classify_malformed_output_failures() -> None:
    """Malformed output and JSON decode failures must be MALFORMED_OUTPUT."""
    result = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed: JSONDecodeError: Expecting ',' delimiter",
    )
    category, retryable, _ = classify_cycle_result(result)
    assert category == FailureCategory.MALFORMED_OUTPUT
    assert retryable is False


def test_classify_tool_call_errors() -> None:
    """Tool invocation syntax or unknown tool calls must be TOOL_CALL_ERROR."""
    result = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Model requested unauthorized or unregistered tool: 'place_crypto_order'",
    )
    category, retryable, _ = classify_cycle_result(result)
    assert category == FailureCategory.TOOL_CALL_ERROR
    assert retryable is False


def test_classify_max_turns_exceeded() -> None:
    """Exceeding maximum conversation turns must be MAX_TURNS_EXCEEDED."""
    result = make_mock_cycle_result(
        status=CycleStatus.MAX_TURNS_EXCEEDED,
        error="Agent interaction bound exceeded (5 turns) without decision.",
    )
    category, retryable, _ = classify_cycle_result(result)
    assert category == FailureCategory.MAX_TURNS_EXCEEDED
    assert retryable is False


def test_classify_tool_execution_failure() -> None:
    """Tool execution fatal exceptions must be TOOL_EXECUTION_FAILURE."""
    tool_exec = CycleToolExecution(
        tool_name="calculate_position_size",
        arguments={"capital": 10000},
        success=False,
        error="ZeroDivisionError: division by zero",
        error_type="HANDLER_EXCEPTION",
        execution_time_ms=5.0,
    )
    result = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Tool execution crashed",
        tool_executions=[tool_exec],
    )
    category, retryable, _ = classify_cycle_result(result)
    assert category == FailureCategory.TOOL_EXECUTION_FAILURE
    assert retryable is False


def test_classify_internal_exception() -> None:
    """Unexpected cycle crashes must be INTERNAL_EXCEPTION."""
    result = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Unexpected exception in decision cycle: KeyError: 'portfolio'",
    )
    category, retryable, _ = classify_cycle_result(result)
    assert category == FailureCategory.INTERNAL_EXCEPTION
    assert retryable is False


def test_sanitize_error_message_strips_sensitive_data() -> None:
    """Sensitive API keys, tokens, and internal paths must be redacted."""
    raw = (
        "Failed request with api_key=AIzaSyA1234567890abcdef1234567890abcde "
        "at /Users/rakeshvajja/secrets/key.json"
    )
    sanitized = sanitize_error_message(raw)
    assert "AIzaSy" not in sanitized
    assert "/Users/rakeshvajja" not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized
    assert "[REDACTED_PATH]" in sanitized


# ==============================================================================
# 2. Retry Policy & Bounded Execution Tests
# ==============================================================================


def test_retry_transient_failure_then_succeeds() -> None:
    """Transient failures must retry up to max_retries and succeed without incrementing failure counter."""
    config = FailurePolicyConfig(max_retries=2, initial_backoff_seconds=0.0)
    handler = AgentFailureHandler(config=config)

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    # Attempt 1: Transient 503 failure
    # Attempt 2: Success
    mock_cycle.run_cycle.side_effect = [
        make_mock_cycle_result(
            status=CycleStatus.GEMINI_ERROR,
            error="503 Service Unavailable",
            candle_timestamp=t,
        ),
        make_mock_cycle_result(
            status=CycleStatus.SUCCESS,
            decision=AgentDecision(
                action=AgentAction.HOLD,
                reason="Wait for pullback",
                confidence=0.8,
            ),
            candle_timestamp=t,
        ),
    ]

    context = MagicMock()
    context.virtual_time = t
    mandate = make_test_mandate()

    result = handler.execute_cycle(
        cycle=mock_cycle,
        context=context,
        mandate=mandate,
        agent_id="agent-1",
        simulation_id="sim-1",
    )

    assert result.status == CycleStatus.SUCCESS
    assert mock_cycle.run_cycle.call_count == 2
    # The event key must be un-registered in cycle between retries to allow re-entry
    mock_cycle.remove_processed_event.assert_called_once_with(
        simulation_id="sim-1", agent_id="agent-1", candle_ts=t
    )

    state = handler.get_state("agent-1", "sim-1")
    assert state.consecutive_failures == 0
    assert not state.is_paused


def test_retry_bounded_exceeded_triggers_failure() -> None:
    """If transient failures exceed max_retries, retry ceases and failure is recorded."""
    config = FailurePolicyConfig(
        max_retries=2, initial_backoff_seconds=0.0, max_consecutive_failures=5
    )
    handler = AgentFailureHandler(config=config)

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    # 3 transient failures (1 initial + 2 retries)
    mock_cycle.run_cycle.return_value = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="503 Service Unavailable",
        candle_timestamp=t,
    )

    context = MagicMock()
    context.virtual_time = t
    mandate = make_test_mandate()

    result = handler.execute_cycle(
        cycle=mock_cycle,
        context=context,
        mandate=mandate,
        agent_id="agent-1",
        simulation_id="sim-1",
    )

    assert result.status == CycleStatus.GEMINI_ERROR
    assert mock_cycle.run_cycle.call_count == 3  # 1 initial + 2 retries
    assert mock_cycle.remove_processed_event.call_count == 2

    state = handler.get_state("agent-1", "sim-1")
    assert state.consecutive_failures == 1
    assert state.total_failures == 1
    assert state.last_failure_category == FailureCategory.API_TRANSIENT


def test_non_retryable_failure_not_retried() -> None:
    """Non-retryable failures (e.g. MALFORMED_OUTPUT) must not be retried even once."""
    config = FailurePolicyConfig(max_retries=3, max_consecutive_failures=5)
    handler = AgentFailureHandler(config=config)

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    mock_cycle.run_cycle.return_value = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed: JSONDecodeError",
        candle_timestamp=t,
    )

    context = MagicMock()
    context.virtual_time = t
    mandate = make_test_mandate()

    result = handler.execute_cycle(
        cycle=mock_cycle,
        context=context,
        mandate=mandate,
        agent_id="agent-1",
        simulation_id="sim-1",
    )

    assert result.status == CycleStatus.GEMINI_ERROR
    assert mock_cycle.run_cycle.call_count == 1
    mock_cycle.remove_processed_event.assert_not_called()

    state = handler.get_state("agent-1", "sim-1")
    assert state.consecutive_failures == 1
    assert state.last_failure_category == FailureCategory.MALFORMED_OUTPUT


# ==============================================================================
# 3. Failure Counters & Idempotency Tests
# ==============================================================================


def test_consecutive_failure_counter_increments_and_resets() -> None:
    """Counter increments on each distinct failed candle and resets on success."""
    config = FailurePolicyConfig(max_consecutive_failures=5, max_retries=0)
    handler = AgentFailureHandler(config=config)

    t1 = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 7, 10, 1, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 7, 10, 2, tzinfo=timezone.utc)

    # Candle 1 fails
    res1 = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed",
        candle_timestamp=t1,
    )
    handler.record_cycle_result(res1, agent_id="agent-1", simulation_id="sim-1")
    state = handler.get_state("agent-1", "sim-1")
    assert state.consecutive_failures == 1
    assert state.total_failures == 1

    # Candle 2 fails
    res2 = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Tool execution crashed: division by zero",
        candle_timestamp=t2,
    )
    handler.record_cycle_result(res2, agent_id="agent-1", simulation_id="sim-1")
    state = handler.get_state("agent-1", "sim-1")
    assert state.consecutive_failures == 2
    assert state.total_failures == 2

    # Candle 3 succeeds -> resets consecutive_failures to 0
    res3 = make_mock_cycle_result(status=CycleStatus.SUCCESS, candle_timestamp=t3)
    handler.record_cycle_result(res3, agent_id="agent-1", simulation_id="sim-1")
    state = handler.get_state("agent-1", "sim-1")
    assert state.consecutive_failures == 0
    assert state.total_failures == 2  # total cumulative remains tracked


def test_idempotency_duplicate_failed_result() -> None:
    """Duplicate processing of the exact same candle result must not increment counters twice."""
    config = FailurePolicyConfig(max_consecutive_failures=5, max_retries=0)
    handler = AgentFailureHandler(config=config)

    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    res = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed",
        candle_timestamp=t,
    )

    # 1st delivery
    s1 = handler.record_cycle_result(res, agent_id="agent-1", simulation_id="sim-1")
    assert s1.consecutive_failures == 1

    # 2nd delivery of the exact same event
    s2 = handler.record_cycle_result(res, agent_id="agent-1", simulation_id="sim-1")
    assert s2.consecutive_failures == 1
    assert s2.total_failures == 1


def test_failure_counter_isolation_by_agent_and_simulation() -> None:
    """Failure state must be strictly scoped to (simulation_id, agent_id)."""
    config = FailurePolicyConfig(max_consecutive_failures=5, max_retries=0)
    handler = AgentFailureHandler(config=config)

    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    res = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Tool execution crashed",
        candle_timestamp=t,
    )

    # Fail agent A in sim 1
    handler.record_cycle_result(res, agent_id="agent-A", simulation_id="sim-1")

    # Verify agent B in sim 1 is clean
    state_b1 = handler.get_state("agent-B", "sim-1")
    assert state_b1.consecutive_failures == 0
    assert not state_b1.is_paused

    # Verify agent A in sim 2 is clean
    state_a2 = handler.get_state("agent-A", "sim-2")
    assert state_a2.consecutive_failures == 0
    assert not state_a2.is_paused


# ==============================================================================
# 4. Auto-Pause Trigger & Authoritative Control Tests
# ==============================================================================


def test_auto_pause_threshold_trigger_and_callback() -> None:
    """When consecutive failures hit threshold, auto-pause is triggered and callback invoked."""
    pause_callback = MagicMock()
    config = FailurePolicyConfig(max_consecutive_failures=2, max_retries=0)
    handler = AgentFailureHandler(config=config, pause_callback=pause_callback)

    t1 = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 7, 10, 1, tzinfo=timezone.utc)

    # 1st failure: below threshold (2)
    res1 = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed",
        candle_timestamp=t1,
    )
    handler.record_cycle_result(res1, agent_id="agent-1", simulation_id="sim-1")
    assert not handler.is_paused("agent-1", "sim-1")
    pause_callback.assert_not_called()

    # 2nd failure: hits threshold
    res2 = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed",
        candle_timestamp=t2,
    )
    handler.record_cycle_result(res2, agent_id="agent-1", simulation_id="sim-1")
    assert handler.is_paused("agent-1", "sim-1")
    pause_callback.assert_called_once()
    args, _ = pause_callback.call_args
    assert args[0] == "sim-1"
    assert args[1] == "agent-1"
    assert "consecutive failures reached threshold" in args[2]


def test_auto_pause_idempotency_when_already_paused() -> None:
    """Further failures when already paused do not trigger duplicate pause callbacks."""
    pause_callback = MagicMock()
    config = FailurePolicyConfig(max_consecutive_failures=1, max_retries=0)
    handler = AgentFailureHandler(config=config, pause_callback=pause_callback)

    t1 = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 7, 10, 1, tzinfo=timezone.utc)

    # 1st failure triggers pause
    res1 = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Unexpected exception in decision cycle: KeyError",
        candle_timestamp=t1,
    )
    handler.record_cycle_result(res1, agent_id="agent-1", simulation_id="sim-1")
    assert pause_callback.call_count == 1

    # 2nd failure while already paused
    res2 = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Unexpected exception in decision cycle: KeyError",
        candle_timestamp=t2,
    )
    handler.record_cycle_result(res2, agent_id="agent-1", simulation_id="sim-1")
    assert pause_callback.call_count == 1  # Not called again


def test_resume_clears_pause_and_resets_counter() -> None:
    """Explicit resume unpauses the agent and resets consecutive failures."""
    config = FailurePolicyConfig(max_consecutive_failures=1, max_retries=0)
    handler = AgentFailureHandler(config=config)

    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    res = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Tool execution crashed",
        candle_timestamp=t,
    )
    handler.record_cycle_result(res, agent_id="agent-1", simulation_id="sim-1")
    assert handler.is_paused("agent-1", "sim-1")

    # Explicit resume
    state = handler.resume("agent-1", "sim-1")
    assert not state.is_paused
    assert state.consecutive_failures == 0
    assert not handler.is_paused("agent-1", "sim-1")


# ==============================================================================
# 5. Replay Strategy & Control Flow Integration Tests
# ==============================================================================


def test_create_agent_strategy_with_failure_handler_halts_on_pause() -> None:
    """When an agent is auto-paused, create_agent_strategy immediately skips cycles without placing orders."""
    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=1, max_retries=0)
    )

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    mock_cycle.memory_service = None

    t1 = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 7, 10, 1, tzinfo=timezone.utc)

    # Cycle fails on candle 1
    mock_cycle.run_cycle.return_value = make_mock_cycle_result(
        status=CycleStatus.GEMINI_ERROR,
        error="Structured output validation failed: JSONDecodeError",
        candle_timestamp=t1,
    )

    portfolio = PortfolioTracker(initial_capital=100_000.0)
    risk_engine = RiskEngine()
    mandate = make_test_mandate()

    strategy_fn = create_agent_strategy(
        cycle=mock_cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="test-sim",
        failure_handler=handler,
    )

    # Step 1: execute candle 1 -> fails -> triggers pause -> returns []
    ctx1 = MagicMock()
    ctx1.virtual_time = t1
    ctx1.candle = CandleData(
        timestamp=t1,
        open=100.0,
        high=105.0,
        low=99.0,
        close=103.0,
        volume=1000.0,
    )
    ctx1.historical_candles = []
    orders1 = strategy_fn(ctx1)
    assert orders1 == []
    assert mock_cycle.run_cycle.call_count == 1
    assert handler.is_paused("test-agent", "test-sim")

    # Step 2: execute candle 2 -> agent is auto-paused -> fast path returns [] without invoking LLM
    ctx2 = MagicMock()
    ctx2.virtual_time = t2
    ctx2.candle = CandleData(
        timestamp=t2,
        open=103.0,
        high=106.0,
        low=102.0,
        close=105.0,
        volume=1200.0,
    )
    ctx2.historical_candles = []
    orders2 = strategy_fn(ctx2)
    assert orders2 == []
    # run_cycle call_count MUST remain 1 (never called for candle 2)
    assert mock_cycle.run_cycle.call_count == 1


def test_create_agent_strategy_normal_success_path_intact() -> None:
    """Normal success cycle works seamlessly through failure_handler with staged orders returned."""
    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=1, max_retries=0)
    )

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    mock_cycle.memory_service = None

    t1 = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    staged_order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=5,
        price=None,
        decision_time=t1,
    )

    def fake_run_cycle(**kwargs: Any) -> DecisionCycleResult:
        context: ToolExecutionContext = kwargs["context"]
        context.staged_orders.append(staged_order)
        return make_mock_cycle_result(
            status=CycleStatus.DECISION_ORDER_STAGED,
            decision=AgentDecision(
                action=AgentAction.BUY,
                quantity=5,
                reason="Momentum signal",
                confidence=0.9,
            ),
            orders_staged=["order-123"],
            candle_timestamp=t1,
        )

    mock_cycle.run_cycle.side_effect = fake_run_cycle

    portfolio = PortfolioTracker(initial_capital=100_000.0)
    risk_engine = RiskEngine()
    mandate = make_test_mandate()

    strategy_fn = create_agent_strategy(
        cycle=mock_cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="test-sim",
        failure_handler=handler,
    )

    ctx = MagicMock()
    ctx.virtual_time = t1
    ctx.candle = CandleData(
        timestamp=t1,
        open=100.0,
        high=105.0,
        low=99.0,
        close=103.0,
        volume=1000.0,
    )
    ctx.historical_candles = []

    orders = strategy_fn(ctx)
    assert len(orders) == 1
    assert orders[0].symbol == "RELIANCE"
    assert orders[0].quantity == 5
    assert not handler.is_paused("test-agent", "test-sim")


# ==============================================================================
# 6. Database Persistence & SimulationService Integration Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_safety_service_persistence_updates_agent_status() -> None:
    """AgentSafetyService.persist_agent_pause_state updates the DB Agent.status to PAUSED."""
    from app.database import models

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        inst = models.Instrument(
            id=1,
            symbol="RELIANCE",
            name="Reliance Industries",
            exchange="NSE",
            instrument_type=models.InstrumentType.EQUITY,
        )
        session.add(inst)
        await session.commit()

        # Create an active test agent
        agent = DBAgent(
            id="agent-123",
            name="Test Safety Agent",
            status=AgentStatus.RUNNING,
            instrument_id=1,
            strategy_prompt="Test strategy prompt",
            initial_capital=100000.0,
        )
        session.add(agent)
        await session.commit()

    service = AgentSafetyService()

    failure_state = AgentFailureState(
        agent_id="agent-123",
        is_paused=True,
        pause_reason="Repeated Gemini API failures",
    )

    async with async_session() as session:
        updated = await service.persist_agent_pause_state(
            db=session,
            agent_id="agent-123",
            state_or_reason=failure_state,
        )
        assert updated is True

    # Verify agent is now PAUSED in the DB
    async with async_session() as session:
        res = await session.execute(select(DBAgent).where(DBAgent.id == "agent-123"))
        persisted_agent = res.scalar_one()
        assert persisted_agent.status == AgentStatus.PAUSED

    await engine.dispose()


@pytest.mark.asyncio
async def test_safety_service_attach_simulation_service_invokes_pause() -> None:
    """AgentSafetyService invokes SimulationService.pause_simulation on auto-pause."""
    mock_sim_service = MagicMock()
    mock_sim_service.pause_simulation = AsyncMock()
    mock_sim_service.session_factory = None

    service = AgentSafetyService()
    service.attach_simulation_service(mock_sim_service)

    # Invoke the pause callback created by safety service
    callback = service.create_pause_callback(agent_id="agent-123", db=None)
    callback("sim-999", "agent-123", "Too many errors")

    # Allow async task to complete
    await asyncio.sleep(0.05)

    mock_sim_service.pause_simulation.assert_awaited_once()
    _, kwargs = mock_sim_service.pause_simulation.call_args
    assert kwargs["simulation_id"] == "sim-999"


def test_retry_after_partial_cycle_clears_staged_orders_and_avoids_duplicate() -> None:
    """If an attempt stages an order then crashes with transient error, retry starts with a clean slate."""
    config = FailurePolicyConfig(max_retries=2, initial_backoff_seconds=0.0)
    handler = AgentFailureHandler(config=config)

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    staged_attempt1 = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        price=None,
        decision_time=t,
    )

    def fake_run_cycle(**kwargs: Any) -> DecisionCycleResult:
        context: ToolExecutionContext = kwargs["context"]
        if mock_cycle.run_cycle.call_count == 1:
            # Attempt 1: stages an order, then fails with 503
            context.staged_orders.append(staged_attempt1)
            return make_mock_cycle_result(
                status=CycleStatus.GEMINI_ERROR,
                error="503 Service Unavailable",
                candle_timestamp=t,
            )
        else:
            # Attempt 2 (retry): decides HOLD
            # Staged orders must have been cleared before attempt 2
            assert len(context.staged_orders) == 0
            return make_mock_cycle_result(
                status=CycleStatus.NO_ACTION,
                decision=AgentDecision(
                    action=AgentAction.HOLD,
                    reason="Market conditions changed on re-evaluation",
                    confidence=0.85,
                ),
                candle_timestamp=t,
            )

    mock_cycle.run_cycle.side_effect = fake_run_cycle

    context = MagicMock()
    context.virtual_time = t
    context.staged_orders = []
    mandate = make_test_mandate()

    res = handler.execute_cycle(
        cycle=mock_cycle,
        context=context,
        mandate=mandate,
        agent_id="agent-1",
        simulation_id="sim-1",
    )

    assert res.status == CycleStatus.NO_ACTION
    assert mock_cycle.run_cycle.call_count == 2
    # Ensure no orphaned orders remain
    assert len(context.staged_orders) == 0


def test_failed_cycle_without_immediate_pause_clears_staged_orders() -> None:
    """If max_consecutive_failures > 1 and cycle fails, staged orders are strictly cleared."""
    handler = AgentFailureHandler(
        config=FailurePolicyConfig(max_consecutive_failures=3, max_retries=0)
    )

    mock_cycle = MagicMock(spec=AgentDecisionCycle)
    mock_cycle.memory_service = None
    t = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)

    # Attempt stages an order then fails with GEMINI_ERROR
    staged_order = OrderRequest(
        symbol="RELIANCE",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=5,
        price=None,
        decision_time=t,
    )

    def fake_run_cycle(**kwargs: Any) -> DecisionCycleResult:
        context: ToolExecutionContext = kwargs["context"]
        context.staged_orders.append(staged_order)
        return make_mock_cycle_result(
            status=CycleStatus.GEMINI_ERROR,
            error="Structured output validation failed: JSONDecodeError",
            candle_timestamp=t,
        )

    mock_cycle.run_cycle.side_effect = fake_run_cycle

    portfolio = PortfolioTracker(initial_capital=100_000.0)
    risk_engine = RiskEngine()
    mandate = make_test_mandate()

    strategy_fn = create_agent_strategy(
        cycle=mock_cycle,
        mandate=mandate,
        portfolio=portfolio,
        risk_engine=risk_engine,
        agent_id="test-agent",
        simulation_id="test-sim",
        failure_handler=handler,
    )

    ctx = MagicMock()
    ctx.virtual_time = t
    ctx.candle = CandleData(
        timestamp=t,
        open=100.0,
        high=105.0,
        low=99.0,
        close=103.0,
        volume=1000.0,
    )
    ctx.historical_candles = []

    # Execute strategy: consecutive_failures becomes 1 (< 3 threshold, so NOT paused)
    orders = strategy_fn(ctx)
    # Staged orders MUST be cleared because the cycle failed
    assert orders == []
    assert not handler.is_paused("test-agent", "test-sim")
    assert handler.get_state("test-agent", "test-sim").consecutive_failures == 1


def test_sanitizer_redacts_bearer_credentials_container_paths_and_tracebacks() -> None:
    """Sanitizer must redact bearer tokens, credentials, container paths, and traceback frames."""
    raw = (
        "Failed request: Authorization: Bearer ya29.a0AfH6SM12345 password=supersecret "
        "at /app/trading/agent/cycle.py:42 Traceback (most recent call last):\n"
        '  File "/app/engine.py", line 123, in run\n    raise ValueError("Bad")'
    )
    sanitized = sanitize_error_message(raw)
    assert "ya29" not in sanitized
    assert "supersecret" not in sanitized
    assert "/app/" not in sanitized
    assert "Traceback" not in sanitized
    assert "[REDACTED_CREDENTIAL]" in sanitized
    assert "[REDACTED_PATH]" in sanitized


@pytest.mark.asyncio
async def test_safety_service_persistence_rollback_on_db_error() -> None:
    """If DB commit fails during persist_agent_pause_state, rollback is invoked and exception raised."""
    mock_db = MagicMock(spec=AsyncSession)
    mock_res = MagicMock()
    mock_agent = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_agent
    mock_db.execute = AsyncMock(return_value=mock_res)
    mock_db.commit = AsyncMock(side_effect=RuntimeError("Database connection lost"))
    mock_db.rollback = AsyncMock()

    service = AgentSafetyService()
    with pytest.raises(RuntimeError, match="Database connection lost"):
        await service.persist_agent_pause_state(
            db=mock_db,
            agent_id="agent-999",
            state_or_reason="pause reason",
        )

    mock_db.rollback.assert_awaited_once()
