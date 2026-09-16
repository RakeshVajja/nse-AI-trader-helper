"""Tests for Safe Tool Execution Harness (Phase 7C)."""

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.market_data.schema import CandleData
from app.trading.agent.harness import (
    CORE_TOOL_NAMES,
    SafeToolExecutionHarness,
    ToolDefinition,
    ToolRegistry,
    create_default_tool_registry,
    dispatch_tool,
    execute_tool,
)
from app.trading.agent.schemas import (
    GetMarketDataInput,
    GetMarketDataOutput,
    ToolErrorType,
)
from app.trading.agent.tools import ToolExecutionContext
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderSide, OrderStatus

# ==============================================================================
# Test Fixtures & Helpers
# ==============================================================================


def generate_synthetic_candles(
    count: int = 30,
    base_price: float = 2500.0,
    start_time: datetime = datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
) -> List[CandleData]:
    candles: List[CandleData] = []
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
def base_candles() -> List[CandleData]:
    return generate_synthetic_candles(count=20, base_price=2500.0)


@pytest.fixture
def sample_context(base_candles: List[CandleData]) -> ToolExecutionContext:
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    current = base_candles[-1]
    return ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=current.timestamp,
        current_candle=current,
        visible_candles=base_candles,
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=[],
    )


@pytest.fixture
def harness() -> SafeToolExecutionHarness:
    return SafeToolExecutionHarness()


# ==============================================================================
# 1. ToolRegistry Tests
# ==============================================================================


def test_default_registry_contents():
    registry = create_default_tool_registry()
    assert len(registry) == 9
    assert set(registry.list_tools()) == CORE_TOOL_NAMES
    for name in CORE_TOOL_NAMES:
        assert name in registry
        tool = registry.get(name)
        assert tool is not None
        assert tool.name == name
        assert tool.input_schema is not None
        assert tool.output_schema is not None
        assert callable(tool.handler)


def test_registry_duplicate_registration_raises():
    registry = ToolRegistry()
    defn = ToolDefinition(
        name="dummy_tool",
        input_schema=GetMarketDataInput,
        output_schema=GetMarketDataOutput,
        handler=lambda ctx, inp: None,  # type: ignore
    )
    registry.register(defn)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(defn)


def test_registry_get_nonexistent():
    registry = ToolRegistry()
    assert registry.get("not_exist") is None
    assert "not_exist" not in registry


# ==============================================================================
# 2. Successful Dispatch for All 9 Tools
# ==============================================================================


def test_dispatch_get_market_data(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_market_data", {"lookback": 5}, sample_context)
    assert res.success is True
    assert res.tool_name == "get_market_data"
    assert res.error is None
    assert res.error_type is None
    assert isinstance(res.data, dict)
    assert res.data["symbol"] == "RELIANCE"
    assert len(res.data["recent_candles"]) == 5
    assert res.data["current_price"] == sample_context.current_candle.close


def test_dispatch_get_indicators(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_indicators", {}, sample_context)
    assert res.success is True
    assert res.tool_name == "get_indicators"
    assert isinstance(res.data, dict)
    assert res.data["symbol"] == "RELIANCE"
    assert "ema_9" in res.data
    assert "rsi_14" in res.data


def test_dispatch_get_market_regime(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_market_regime", {}, sample_context)
    assert res.success is True
    assert res.tool_name == "get_market_regime"
    assert isinstance(res.data, dict)
    assert res.data["symbol"] == "RELIANCE"
    assert "trend_regime" in res.data


def test_dispatch_get_position_flat(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_position", {}, sample_context)
    assert res.success is True
    assert res.tool_name == "get_position"
    assert isinstance(res.data, dict)
    assert res.data["is_open"] is False
    assert res.data["quantity"] == 0


def test_dispatch_get_portfolio(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_portfolio", {}, sample_context)
    assert res.success is True
    assert res.tool_name == "get_portfolio"
    assert isinstance(res.data, dict)
    assert res.data["initial_capital"] == 100000.0
    assert res.data["cash"] == 100000.0


def test_dispatch_get_trade_history(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_trade_history", {"limit": 10}, sample_context)
    assert res.success is True
    assert res.tool_name == "get_trade_history"
    assert isinstance(res.data, dict)
    assert res.data["trades"] == []
    assert res.data["total_closed_trades"] == 0


def test_dispatch_calculate_position_size(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    curr_price = float(sample_context.current_candle.close)
    args = {"entry_price": curr_price, "stop_loss_price": curr_price * 0.98}
    res = harness.dispatch("calculate_position_size", args, sample_context)
    assert res.success is True
    assert res.tool_name == "calculate_position_size"
    assert isinstance(res.data, dict)
    assert res.data["status"] == "APPROVED"
    assert res.data["target_quantity"] > 0


def test_dispatch_place_simulated_order(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    curr_price = float(sample_context.current_candle.close)
    args = {
        "side": OrderSide.BUY.value,
        "quantity": 5,
        "stop_loss": round(curr_price * 0.98, 2),
        "reason": "Safe harness buy",
    }
    res = harness.dispatch("place_simulated_order", args, sample_context)
    assert res.success is True
    assert res.tool_name == "place_simulated_order"
    assert res.error is None
    assert isinstance(res.data, dict)
    assert res.data["status"] == OrderStatus.PENDING.value
    assert res.data["execution_stage"] == "QUEUED_FOR_NEXT_OPEN"
    assert res.data["order_id"] is not None
    assert len(sample_context.staged_orders) == 1


def test_dispatch_close_simulated_position(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    # Setup an active position
    sample_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2490.0,
        transaction_cost=10.0,
        slippage_cost=5.0,
        timestamp=sample_context.virtual_time,
        stop_loss=2440.0,
        take_profit=2550.0,
    )
    res = harness.dispatch("close_simulated_position", {"reason": "Take profit"}, sample_context)
    assert res.success is True
    assert res.tool_name == "close_simulated_position"
    assert isinstance(res.data, dict)
    assert res.data["status"] == "QUEUED_FOR_NEXT_OPEN"
    assert res.data["closed_quantity"] == 10
    assert len(sample_context.staged_orders) == 1


# ==============================================================================
# 3. Security & Trust Boundary Tests
# ==============================================================================


def test_unknown_tool_rejection(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    bad_tools = [
        "execute_arbitrary_python",
        "os.system",
        "exec",
        "eval",
        "__import__",
        "subprocess",
        "drop_database",
        "",
        "   ",
    ]
    for bad in bad_tools:
        res = harness.dispatch(bad, {}, sample_context)
        assert res.success is False
        assert res.error_type == ToolErrorType.UNKNOWN_TOOL
        assert res.data is None
        assert "not registered" in res.error or "non-empty" in res.error


def test_extra_field_injection_rejected(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    """Extra fields must be forbidden by Pydantic schema validation."""
    malicious_payloads = [
        {"lookback": 5, "malicious_code": "import os; os.system('rm -rf /')"},
        {"lookback": 5, "__class__": "evil"},
        {"lookback": 5, "extra_flag": True},
    ]
    for payload in malicious_payloads:
        res = harness.dispatch("get_market_data", payload, sample_context)
        assert res.success is False
        assert res.error_type == ToolErrorType.SCHEMA_ERROR
        assert "Schema validation failed" in res.error


def test_malformed_arguments_rejected(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    # Passing a non-dict / non-JSON type
    bad_types = [12345, [1, 2, 3], True]
    for bt in bad_types:
        res = harness.dispatch("get_market_data", bt, sample_context)
        assert res.success is False
        assert res.error_type == ToolErrorType.SCHEMA_ERROR
        assert "must be a dictionary" in res.error

    # Passing malformed JSON string
    res = harness.dispatch("get_market_data", "{invalid: json", sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.SCHEMA_ERROR
    assert "Malformed JSON" in res.error

    # JSON string that decodes to list instead of dict
    res = harness.dispatch("get_market_data", "[1, 2, 3]", sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.SCHEMA_ERROR
    assert "must decode to an object/dict" in res.error


def test_invalid_enum_and_bounds_rejected(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    # Invalid enum in place_simulated_order
    res = harness.dispatch(
        "place_simulated_order",
        {"side": "SUPER_BUY", "quantity": 10},
        sample_context,
    )
    assert res.success is False
    assert res.error_type == ToolErrorType.SCHEMA_ERROR

    # Negative quantity
    res = harness.dispatch(
        "place_simulated_order",
        {"side": "BUY", "quantity": -5},
        sample_context,
    )
    assert res.success is False
    assert res.error_type == ToolErrorType.SCHEMA_ERROR

    # Lookback out of range (max is 100)
    res = harness.dispatch("get_market_data", {"lookback": 200}, sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.SCHEMA_ERROR


def test_symbol_override_attempt_blocked(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    # Context locked to RELIANCE; agent tries to query TCS
    res = harness.dispatch("get_market_data", {"symbol": "TCS"}, sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.STATE_ERROR
    assert "Symbol mismatch" in res.error

    # Matching symbol (case insensitive) succeeds
    res_ok = harness.dispatch("get_market_data", {"symbol": "reliance"}, sample_context)
    assert res_ok.success is True


def test_invalid_context_type_handled(harness: SafeToolExecutionHarness):
    # Pass non-ToolExecutionContext
    res = harness.dispatch("get_market_data", {}, None)  # type: ignore
    assert res.success is False
    assert res.error_type == ToolErrorType.INTERNAL_ERROR
    assert "Invalid or missing ToolExecutionContext" in res.error


# ==============================================================================
# 4. Mutating Tool Staged-Order Guard & Lifecycle
# ==============================================================================


def test_single_staged_order_per_candle_enforced_by_harness(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    curr_price = float(sample_context.current_candle.close)
    args = {
        "side": OrderSide.BUY.value,
        "quantity": 5,
        "stop_loss": round(curr_price * 0.98, 2),
        "reason": "First buy",
    }
    # Call 1: Succeeds
    res1 = harness.dispatch("place_simulated_order", args, sample_context)
    assert res1.success is True
    assert len(sample_context.staged_orders) == 1

    # Call 2 (same candle): Blocked with ORDER_ALREADY_STAGED
    res2 = harness.dispatch("place_simulated_order", args, sample_context)
    assert res2.success is False
    assert res2.error_type == ToolErrorType.ORDER_ALREADY_STAGED
    assert "already staged" in res2.error

    # Call 3 (same candle, close_simulated_position): Also blocked
    res3 = harness.dispatch("close_simulated_position", {}, sample_context)
    assert res3.success is False
    assert res3.error_type == ToolErrorType.ORDER_ALREADY_STAGED

    # Read-only tools still work on the same candle!
    res_ro = harness.dispatch("get_market_data", {}, sample_context)
    assert res_ro.success is True


def test_risk_rejection_mapping_and_retry(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    curr_price = float(sample_context.current_candle.close)
    # Attempt 1: Excessive size -> rejected by risk engine
    excessive_args = {
        "side": OrderSide.BUY.value,
        "quantity": 10000,
        "stop_loss": round(curr_price * 0.98, 2),
        "reason": "Excessive size",
    }
    res_bad = harness.dispatch("place_simulated_order", excessive_args, sample_context)
    assert res_bad.success is False
    assert res_bad.error_type == ToolErrorType.RISK_REJECTION
    assert "Risk check failed" in res_bad.error
    assert len(sample_context.staged_orders) == 0
    # Metadata is preserved in data payload for Phase 8 inspection
    assert res_bad.data is not None
    assert res_bad.data["status"] == OrderStatus.REJECTED.value
    assert res_bad.data["order_id"] is not None

    # Attempt 2: Safe size on same candle -> succeeds
    safe_args = {
        "side": OrderSide.BUY.value,
        "quantity": 4,
        "stop_loss": round(curr_price * 0.98, 2),
        "reason": "Safe size",
    }
    res_good = harness.dispatch("place_simulated_order", safe_args, sample_context)
    assert res_good.success is True
    assert res_good.error is None
    assert len(sample_context.staged_orders) == 1


def test_close_position_state_errors(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    # No active position -> STATE_ERROR
    res = harness.dispatch("close_simulated_position", {}, sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.STATE_ERROR
    assert "No active open position" in res.error

    # Position exists with qty 5; agent tries to close 20
    sample_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=5,
        price=2500.0,
        transaction_cost=5.0,
        slippage_cost=2.0,
        timestamp=sample_context.virtual_time,
        stop_loss=2450.0,
        take_profit=2550.0,
    )
    res_over = harness.dispatch("close_simulated_position", {"quantity": 20}, sample_context)
    assert res_over.success is False
    assert res_over.error_type == ToolErrorType.STATE_ERROR
    assert "exceeds active position quantity" in res_over.error


# ==============================================================================
# 5. Output Validation & Exception Containment
# ==============================================================================


def test_output_is_pure_json_dict(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    res = harness.dispatch("get_portfolio", {}, sample_context)
    assert res.success is True
    assert isinstance(res.data, dict)
    # Check that no complex domain objects leak into data
    for v in res.data.values():
        assert isinstance(v, (int, float, str, bool, list, dict, type(None)))


def test_exception_containment_in_rogue_tool(sample_context: ToolExecutionContext):
    """If an internal exception occurs, harness returns INTERNAL_ERROR instead of crashing."""
    custom_registry = ToolRegistry()

    def buggy_handler(ctx, inp):
        raise RuntimeError("Simulated internal bug in tool computation")

    custom_registry.register(
        ToolDefinition(
            name="buggy_tool",
            input_schema=GetMarketDataInput,
            output_schema=GetMarketDataOutput,
            handler=buggy_handler,
        )
    )

    custom_harness = SafeToolExecutionHarness(registry=custom_registry)
    res = custom_harness.dispatch("buggy_tool", {}, sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.INTERNAL_ERROR
    assert "Simulated internal bug" in res.error


def test_convenience_helpers(sample_context: ToolExecutionContext):
    # test execute_tool
    res1 = execute_tool(sample_context, "get_market_data", {"lookback": 3})
    assert res1.success is True
    assert res1.tool_name == "get_market_data"

    # test dispatch_tool
    res2 = dispatch_tool("get_position", {}, sample_context)
    assert res2.success is True
    assert res2.tool_name == "get_position"


# ==============================================================================
# 6. Architectural & Security Regression Tests
# ==============================================================================


def test_context_identity_and_read_only_immutability(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    """Verify that dispatch preserves exact object identity and read-only tools cause zero mutation."""
    orig_portfolio_id = id(sample_context.portfolio)
    orig_risk_engine_id = id(sample_context.risk_engine)
    orig_staged_orders_id = id(sample_context.staged_orders)
    orig_cash = sample_context.portfolio.cash

    # Execute read-only tools
    res1 = harness.dispatch("get_market_data", {"lookback": 5}, sample_context)
    res2 = harness.dispatch("get_indicators", {}, sample_context)
    res3 = harness.dispatch("get_portfolio", {}, sample_context)
    res4 = harness.dispatch("get_position", {}, sample_context)

    assert res1.success and res2.success and res3.success and res4.success

    # Assert exact object identity preservation
    assert id(sample_context.portfolio) == orig_portfolio_id
    assert id(sample_context.risk_engine) == orig_risk_engine_id
    assert id(sample_context.staged_orders) == orig_staged_orders_id

    # Assert zero state mutation
    assert sample_context.portfolio.cash == orig_cash
    assert len(sample_context.staged_orders) == 0
    assert len(sample_context.portfolio.positions) == 0


def test_staged_order_guard_parity_between_7b_and_7c(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    """Verify that 7B direct invocation and 7C harness dispatch enforce exact identical guard semantics."""
    from app.trading.agent.tools import place_simulated_order

    curr_price = float(sample_context.current_candle.close)
    order_args = {
        "side": OrderSide.BUY.value,
        "quantity": 2,
        "stop_loss": round(curr_price * 0.98, 2),
        "reason": "Parity test order",
    }

    # Step 1: Stage an order via harness
    res1 = harness.dispatch("place_simulated_order", order_args, sample_context)
    assert res1.success is True
    assert len(sample_context.staged_orders) == 1

    # Step 2: Attempt second order via harness -> blocked with ORDER_ALREADY_STAGED
    res_harness = harness.dispatch("place_simulated_order", order_args, sample_context)
    assert res_harness.success is False
    assert res_harness.error_type == ToolErrorType.ORDER_ALREADY_STAGED
    assert "already staged for current candle step" in res_harness.error

    # Step 3: Attempt direct 7B tool call -> also blocked with exact same reason
    from app.trading.agent.schemas import PlaceSimulatedOrderInput

    inp = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=2,
        stop_loss=round(curr_price * 0.98, 2),
        reason="Direct 7B attempt",
    )
    res_7b = place_simulated_order(sample_context, inp)
    assert res_7b.success is False
    assert res_7b.status == OrderStatus.REJECTED
    assert "already staged for current candle step" in str(res_7b.rejection_reason)


def test_output_schema_mismatch_containment(sample_context: ToolExecutionContext):
    """Verify that if a rogue tool handler returns an output violating its schema, INTERNAL_ERROR is returned."""
    custom_registry = ToolRegistry()

    def bad_output_handler(ctx, inp):
        # Return dict missing required fields or having invalid types
        return {"invalid_output_structure": 12345}

    custom_registry.register(
        ToolDefinition(
            name="bad_output_tool",
            input_schema=GetMarketDataInput,
            output_schema=GetMarketDataOutput,
            handler=bad_output_handler,
        )
    )

    harness = SafeToolExecutionHarness(registry=custom_registry)
    res = harness.dispatch("bad_output_tool", {}, sample_context)
    assert res.success is False
    assert res.error_type == ToolErrorType.INTERNAL_ERROR
    assert "failed schema validation" in res.error


def test_multi_candle_harness_staging_lifecycle(
    harness: SafeToolExecutionHarness, base_candles: List[CandleData]
):
    """Verify multi-candle progression: order on t0 does not block order on t1."""
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    shared_orders: List = []

    # Candle 0
    c0 = base_candles[0]
    ctx0 = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c0.timestamp,
        current_candle=c0,
        visible_candles=[c0],
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=shared_orders,
    )
    args0 = {
        "side": OrderSide.BUY.value,
        "quantity": 2,
        "stop_loss": round(float(c0.close) * 0.98, 2),
        "reason": "Order at t0",
    }
    res0 = harness.dispatch("place_simulated_order", args0, ctx0)
    assert res0.success is True
    assert len(shared_orders) == 1

    # Candle 0 repeated call -> blocked
    res0_repeat = harness.dispatch("place_simulated_order", args0, ctx0)
    assert res0_repeat.success is False
    assert res0_repeat.error_type == ToolErrorType.ORDER_ALREADY_STAGED

    # Advance to Candle 1
    c1 = base_candles[1]
    ctx1 = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c1.timestamp,
        current_candle=c1,
        visible_candles=base_candles[:2],
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=shared_orders,
    )
    args1 = {
        "side": OrderSide.BUY.value,
        "quantity": 3,
        "stop_loss": round(float(c1.close) * 0.98, 2),
        "reason": "Order at t1",
    }
    res1 = harness.dispatch("place_simulated_order", args1, ctx1)
    assert res1.success is True
    assert len(shared_orders) == 2
    assert shared_orders[1].decision_time == c1.timestamp

    # Candle 1 repeated call -> blocked
    res1_repeat = harness.dispatch("place_simulated_order", args1, ctx1)
    assert res1_repeat.success is False
    assert res1_repeat.error_type == ToolErrorType.ORDER_ALREADY_STAGED


def test_attempts_to_pass_agent_controlled_context_rejected(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    """Verify that attempting to inject simulation context parameters into tool arguments is rejected."""
    malicious_context_payloads = [
        {"virtual_time": "2099-01-01T00:00:00Z"},
        {"cash": 100000000.0},
        {"portfolio": {"cash": 1000000.0}},
        {"staged_orders": []},
        {"visible_candles": []},
        {"risk_engine": {}},
    ]
    for payload in malicious_context_payloads:
        res = harness.dispatch("get_portfolio", payload, sample_context)
        assert res.success is False
        assert res.error_type == ToolErrorType.SCHEMA_ERROR
        assert "Extra inputs are not permitted" in res.error


def test_handler_override_injection_attempt_rejected(
    harness: SafeToolExecutionHarness, sample_context: ToolExecutionContext
):
    """Verify that attempts to inject handler, callable, or registry keys into tool args are rejected."""
    injection_payloads = [
        {"handler": "custom_func"},
        {"callable": "os.system"},
        {"registry": {}},
        {"__dict__": {}},
    ]
    for payload in injection_payloads:
        res = harness.dispatch("get_market_data", payload, sample_context)
        assert res.success is False
        assert res.error_type == ToolErrorType.SCHEMA_ERROR


def test_cross_layer_end_to_end_replay_integration(base_candles: List[CandleData]):
    """Verify complete cross-layer workflow: untrusted args -> harness -> 7B tools -> replay engine."""
    from app.trading.simulation.replay import ChronologicalReplayEngine, ReplayContext

    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    engine = ChronologicalReplayEngine(
        candles=base_candles[:5],
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )
    harness = SafeToolExecutionHarness()

    step_log: List[str] = []

    def agent_harness_strategy(rep_ctx: ReplayContext):
        # Construct authoritative ToolExecutionContext from ReplayContext
        staged: List = []
        tool_ctx = ToolExecutionContext.from_replay(
            replay_context=rep_ctx,
            symbol="RELIANCE",
            timeframe="15m",
            portfolio=engine.portfolio,
            risk_engine=engine.risk_engine,
            staged_orders=staged,
        )

        if rep_ctx.step_index == 0:
            # Inspect market via harness
            mkt_res = harness.dispatch("get_market_data", {"lookback": 5}, tool_ctx)
            assert mkt_res.success is True
            curr_px = mkt_res.data["current_price"]

            # Size position via harness
            size_res = harness.dispatch(
                "calculate_position_size",
                {"entry_price": curr_px, "stop_loss_price": round(curr_px * 0.98, 2)},
                tool_ctx,
            )
            assert size_res.success is True
            target_qty = size_res.data["target_quantity"]
            assert target_qty > 0

            # Stage BUY order via harness
            buy_res = harness.dispatch(
                "place_simulated_order",
                {
                    "side": OrderSide.BUY.value,
                    "quantity": target_qty,
                    "stop_loss": round(curr_px * 0.98, 2),
                    "reason": "Harness buy at step 0",
                },
                tool_ctx,
            )
            assert buy_res.success is True
            assert buy_res.data["execution_stage"] == "QUEUED_FOR_NEXT_OPEN"
            step_log.append("STAGED_BUY")

        elif rep_ctx.step_index == 1:
            # Bar 1 Close: Order was filled at Bar 1 Open
            pos_res = harness.dispatch("get_position", {}, tool_ctx)
            assert pos_res.success is True
            assert pos_res.data["is_open"] is True
            assert pos_res.data["quantity"] > 0

            # Close position via harness
            close_res = harness.dispatch(
                "close_simulated_position",
                {"reason": "Harness close at step 1"},
                tool_ctx,
            )
            assert close_res.success is True
            assert close_res.data["status"] == "QUEUED_FOR_NEXT_OPEN"
            step_log.append("STAGED_CLOSE")

        elif rep_ctx.step_index == 2:
            # Bar 2 Close: Close was filled at Bar 2 Open
            pos_res = harness.dispatch("get_position", {}, tool_ctx)
            assert pos_res.success is True
            assert pos_res.data["is_open"] is False

            # Inspect trade history via harness
            hist_res = harness.dispatch("get_trade_history", {"limit": 5}, tool_ctx)
            assert hist_res.success is True
            assert hist_res.data["total_closed_trades"] == 1
            assert len(hist_res.data["trades"]) == 1

            # Inspect portfolio via harness
            port_res = harness.dispatch("get_portfolio", {}, tool_ctx)
            assert port_res.success is True
            assert port_res.data["open_positions_count"] == 0
            step_log.append("VERIFIED_HISTORY")

        return tool_ctx.staged_orders

    summary = engine.run(strategy=agent_harness_strategy)

    assert step_log == ["STAGED_BUY", "STAGED_CLOSE", "VERIFIED_HISTORY"]
    assert len(summary.trades) == 1
    assert len(engine.portfolio.closed_trades) == 1
    assert len(engine.execution_history) == 2
