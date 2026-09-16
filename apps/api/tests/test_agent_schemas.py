"""Unit tests for Phase 7A Agent Tool & Structured Output Pydantic Schemas."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.indicators.schemas import (
    TrendRegime,
    TrendSignalDetails,
    VolatilityMetrics,
    VolatilityRegime,
)
from app.trading.agent.schemas import (
    AgentAction,
    AgentDecision,
    CalculatePositionSizeInput,
    CalculatePositionSizeOutput,
    CloseSimulatedPositionInput,
    CloseSimulatedPositionOutput,
    GetIndicatorsInput,
    GetIndicatorsOutput,
    GetMarketDataInput,
    GetMarketDataOutput,
    GetMarketRegimeInput,
    GetMarketRegimeOutput,
    GetPortfolioInput,
    GetPortfolioOutput,
    GetPositionInput,
    GetPositionOutput,
    GetTradeHistoryInput,
    GetTradeHistoryOutput,
    MarketCandleSchema,
    PlaceSimulatedOrderInput,
    PlaceSimulatedOrderOutput,
    ToolErrorType,
    ToolExecutionResult,
    TradeRecordSchema,
)
from app.trading.schemas import OrderSide, OrderStatus, OrderType

# ==============================================================================
# Helper Fixtures
# ==============================================================================


@pytest.fixture
def sample_candle() -> MarketCandleSchema:
    return MarketCandleSchema(
        timestamp=datetime(2025, 1, 1, 9, 15, tzinfo=timezone.utc),
        open=2500.0,
        high=2520.0,
        low=2495.0,
        close=2515.0,
        volume=100000.0,
    )


# ==============================================================================
# Tool 1: get_market_data Tests
# ==============================================================================


def test_market_candle_schema_valid(sample_candle: MarketCandleSchema):
    assert sample_candle.open == 2500.0
    assert sample_candle.close == 2515.0


def test_market_candle_schema_bounds():
    # Price must be gt 0
    with pytest.raises(ValidationError):
        MarketCandleSchema(
            timestamp=datetime.now(timezone.utc),
            open=0.0,
            high=2520.0,
            low=2495.0,
            close=2515.0,
            volume=1000.0,
        )
    # Volume cannot be negative
    with pytest.raises(ValidationError):
        MarketCandleSchema(
            timestamp=datetime.now(timezone.utc),
            open=2500.0,
            high=2520.0,
            low=2495.0,
            close=2515.0,
            volume=-1.0,
        )


def test_get_market_data_input():
    # Default lookback
    inp = GetMarketDataInput()
    assert inp.lookback == 10
    assert inp.symbol is None

    # Custom valid lookback
    inp2 = GetMarketDataInput(lookback=50, symbol="RELIANCE")
    assert inp2.lookback == 50
    assert inp2.symbol == "RELIANCE"

    # Bounds: lookback < 1 or > 100
    with pytest.raises(ValidationError):
        GetMarketDataInput(lookback=0)
    with pytest.raises(ValidationError):
        GetMarketDataInput(lookback=101)

    # extra="forbid"
    with pytest.raises(ValidationError):
        GetMarketDataInput(lookback=10, invalid_field="stuff")  # type: ignore


def test_get_market_data_output(sample_candle: MarketCandleSchema):
    out = GetMarketDataOutput(
        symbol="RELIANCE",
        timeframe="15m",
        current_candle=sample_candle,
        recent_candles=[sample_candle],
        current_price=2515.0,
        price_change=15.0,
        price_change_pct=0.6,
        current_volume=100000.0,
    )
    assert out.symbol == "RELIANCE"
    assert out.current_price == 2515.0

    # Immutability
    with pytest.raises(ValidationError):
        out.current_price = 2600.0  # type: ignore

    # extra="forbid"
    with pytest.raises(ValidationError):
        GetMarketDataOutput(
            symbol="RELIANCE",
            timeframe="15m",
            current_candle=sample_candle,
            recent_candles=[sample_candle],
            current_price=2515.0,
            price_change=15.0,
            price_change_pct=0.6,
            current_volume=100000.0,
            extra_hack="blocked",  # type: ignore
        )


# ==============================================================================
# Tool 2: get_indicators Tests
# ==============================================================================


def test_get_indicators_input():
    inp = GetIndicatorsInput(symbol="TCS")
    assert inp.symbol == "TCS"

    with pytest.raises(ValidationError):
        GetIndicatorsInput(extra_arg=123)  # type: ignore


def test_get_indicators_output():
    now = datetime.now(timezone.utc)
    # Warmup state with Nones
    out_warmup = GetIndicatorsOutput(
        symbol="RELIANCE",
        timestamp=now,
        close=2500.0,
        is_warmed_up=False,
    )
    assert out_warmup.ema_9 is None
    assert out_warmup.is_warmed_up is False

    # Fully warmed up state
    out_warmed = GetIndicatorsOutput(
        symbol="RELIANCE",
        timestamp=now,
        close=2500.0,
        ema_9=2490.0,
        ema_20=2480.0,
        sma_50=2450.0,
        rsi_14=55.2,
        macd=12.4,
        macd_signal=10.1,
        macd_histogram=2.3,
        is_warmed_up=True,
    )
    assert out_warmed.rsi_14 == 55.2

    # RSI range bound: 0 <= rsi <= 100
    with pytest.raises(ValidationError):
        GetIndicatorsOutput(
            symbol="RELIANCE",
            timestamp=now,
            close=2500.0,
            rsi_14=105.0,
        )


# ==============================================================================
# Tool 3: get_market_regime Tests
# ==============================================================================


def test_get_market_regime_input():
    inp = GetMarketRegimeInput()
    assert inp.symbol is None

    with pytest.raises(ValidationError):
        GetMarketRegimeInput(bogus="bad")  # type: ignore


def test_get_market_regime_output():
    now = datetime.now(timezone.utc)
    out = GetMarketRegimeOutput(
        symbol="RELIANCE",
        timestamp=now,
        trend_regime=TrendRegime.BULLISH,
        volatility_regime=VolatilityRegime.NORMAL,
        trend_signals=TrendSignalDetails(
            close_vs_sma50="BULLISH",
            ema9_vs_ema20="BULLISH",
            macd_vs_zero="BULLISH",
            rsi14_vs_50="BEARISH",
            bullish_votes=3,
            bearish_votes=1,
        ),
        volatility_metrics=VolatilityMetrics(
            current_atrp14=1.25,
            p20_threshold=0.8,
            p80_threshold=2.0,
            sample_count=100,
        ),
    )
    assert out.trend_regime == TrendRegime.BULLISH
    assert out.trend_signals.bullish_votes == 3

    # Invalid enum rejection
    with pytest.raises(ValidationError):
        GetMarketRegimeOutput(
            symbol="RELIANCE",
            timestamp=now,
            trend_regime="SUPER_BULLISH",  # type: ignore
        )


# ==============================================================================
# Tool 4: get_position Tests
# ==============================================================================


def test_get_position_schemas():
    inp = GetPositionInput(symbol="INFY")
    assert inp.symbol == "INFY"

    # Open position
    out_open = GetPositionOutput(
        symbol="INFY",
        is_open=True,
        quantity=50,
        average_entry_price=1800.0,
        current_price=1850.0,
        market_value=92500.0,
        stop_loss=1764.0,
        take_profit=1900.0,
        unrealized_pnl=2500.0,
        unrealized_pnl_pct=2.78,
        entry_time=datetime.now(timezone.utc),
    )
    assert out_open.is_open is True
    assert out_open.quantity == 50

    # Flat position
    out_flat = GetPositionOutput(
        symbol="INFY",
        is_open=False,
        quantity=0,
        average_entry_price=None,
        current_price=1850.0,
        market_value=0.0,
        stop_loss=None,
        take_profit=None,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        entry_time=None,
    )
    assert out_flat.quantity == 0

    # Negative quantity rejected
    with pytest.raises(ValidationError):
        GetPositionOutput(
            symbol="INFY",
            is_open=True,
            quantity=-1,
            current_price=1850.0,
            market_value=0.0,
            unrealized_pnl=0.0,
            unrealized_pnl_pct=0.0,
        )


# ==============================================================================
# Tool 5: get_portfolio Tests
# ==============================================================================


def test_get_portfolio_schemas():
    inp = GetPortfolioInput()
    assert inp.model_dump() == {}

    with pytest.raises(ValidationError):
        GetPortfolioInput(arg="not_allowed")  # type: ignore

    out = GetPortfolioOutput(
        initial_capital=100000.0,
        cash=75000.0,
        total_market_value=26000.0,
        total_portfolio_value=101000.0,
        realized_gross_pnl=500.0,
        realized_net_pnl=460.0,
        unrealized_gross_pnl=1000.0,
        total_transaction_costs=40.0,
        total_slippage_cost=20.0,
        gross_pnl=1500.0,
        net_pnl=1460.0,
        total_return_pct=1.46,
        exposure_pct=25.74,
        daily_starting_equity=100000.0,
        daily_realized_pnl=500.0,
        open_positions_count=1,
    )
    assert out.cash == 75000.0
    assert out.total_return_pct == 1.46

    # Exposure bounds: ge=0, le=100
    with pytest.raises(ValidationError):
        GetPortfolioOutput(
            initial_capital=100000.0,
            cash=100000.0,
            total_market_value=0.0,
            total_portfolio_value=100000.0,
            exposure_pct=105.0,  # invalid
            daily_starting_equity=100000.0,
        )


# ==============================================================================
# Tool 6: get_trade_history Tests
# ==============================================================================


def test_trade_record_schema():
    now = datetime.now(timezone.utc)
    rec = TradeRecordSchema(
        trade_id="TR-001",
        symbol="RELIANCE",
        side=OrderSide.BUY,
        quantity=10,
        entry_price=2400.0,
        exit_price=2500.0,
        gross_pnl=1000.0,
        net_pnl=980.0,
        transaction_costs=20.0,
        slippage_cost=10.0,
        entry_time=now,
        exit_time=now,
        exit_reason="MANUAL_EXIT",
    )
    assert rec.trade_id == "TR-001"
    assert rec.quantity == 10

    with pytest.raises(ValidationError):
        TradeRecordSchema(
            trade_id="TR-002",
            symbol="RELIANCE",
            quantity=0,  # must be gt 0
            entry_price=2400.0,
            exit_price=2500.0,
            gross_pnl=0.0,
            net_pnl=0.0,
            entry_time=now,
            exit_time=now,
        )


def test_get_trade_history_input_and_output():
    inp = GetTradeHistoryInput(limit=25)
    assert inp.limit == 25

    # Bounds: limit 1 to 50
    with pytest.raises(ValidationError):
        GetTradeHistoryInput(limit=0)
    with pytest.raises(ValidationError):
        GetTradeHistoryInput(limit=51)

    out = GetTradeHistoryOutput(trades=[], total_closed_trades=0)
    assert out.total_closed_trades == 0


# ==============================================================================
# Tool 7: calculate_position_size Tests
# ==============================================================================


def test_calculate_position_size_input():
    inp = CalculatePositionSizeInput(
        entry_price=2500.0,
        stop_loss_price=2450.0,
        risk_per_trade=0.02,
        symbol="RELIANCE",
    )
    assert inp.entry_price == 2500.0
    assert inp.stop_loss_price == 2450.0

    # Entry and SL must be > 0
    with pytest.raises(ValidationError):
        CalculatePositionSizeInput(entry_price=-10.0, stop_loss_price=2450.0)
    with pytest.raises(ValidationError):
        CalculatePositionSizeInput(entry_price=2500.0, stop_loss_price=0.0)

    # Risk per trade must be > 0 and <= 1.0
    with pytest.raises(ValidationError):
        CalculatePositionSizeInput(entry_price=2500.0, stop_loss_price=2450.0, risk_per_trade=1.5)


def test_calculate_position_size_output():
    out = CalculatePositionSizeOutput(
        target_quantity=10,
        estimated_execution_price=2501.25,
        estimated_cost=25020.0,
        risk_amount=512.5,
        risk_pct_of_portfolio=0.51,
        position_exposure_pct=25.0,
        status="APPROVED",
    )
    assert out.status == "APPROVED"
    assert out.target_quantity == 10


# ==============================================================================
# Tool 8: place_simulated_order Tests
# ==============================================================================


def test_place_simulated_order_input():
    inp = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=25,
        order_type=OrderType.MARKET,
        stop_loss=2450.0,
        take_profit=2600.0,
        reason="Bullish breakout above SMA50",
    )
    assert inp.side == OrderSide.BUY
    assert inp.quantity == 25
    assert inp.reason == "Bullish breakout above SMA50"

    # Quantity must be > 0
    with pytest.raises(ValidationError):
        PlaceSimulatedOrderInput(
            side=OrderSide.BUY,
            quantity=0,
            reason="Zero shares",
        )

    # Empty reason
    with pytest.raises(ValidationError):
        PlaceSimulatedOrderInput(
            side=OrderSide.BUY,
            quantity=10,
            reason="   ",
        )

    # Extra fields rejected
    with pytest.raises(ValidationError):
        PlaceSimulatedOrderInput(
            side=OrderSide.BUY,
            quantity=10,
            reason="Valid",
            execute_now=True,  # type: ignore
        )


def test_place_simulated_order_output():
    out_approved = PlaceSimulatedOrderOutput(
        success=True,
        order_id="ORD-12345",
        status=OrderStatus.PENDING,
        decision_price=2500.0,
        execution_stage="QUEUED_FOR_NEXT_OPEN",
        risk_metrics={"equity": 100000.0, "trade_risk": 500.0},
    )
    assert out_approved.success is True
    assert out_approved.execution_stage == "QUEUED_FOR_NEXT_OPEN"

    out_rejected = PlaceSimulatedOrderOutput(
        success=False,
        order_id=None,
        status=OrderStatus.REJECTED,
        decision_price=2500.0,
        execution_stage="REJECTED",
        rejection_reason="Insufficient cash",
    )
    assert out_rejected.success is False
    assert out_rejected.rejection_reason == "Insufficient cash"


# ==============================================================================
# Tool 9: close_simulated_position Tests
# ==============================================================================


def test_close_simulated_position_schemas():
    inp_full = CloseSimulatedPositionInput()
    assert inp_full.quantity is None
    assert inp_full.reason == "AGENT_CLOSE"

    inp_partial = CloseSimulatedPositionInput(quantity=15, reason="Taking partial profit")
    assert inp_partial.quantity == 15

    # Quantity must be gt 0 if supplied
    with pytest.raises(ValidationError):
        CloseSimulatedPositionInput(quantity=0)

    # Empty reason rejected
    with pytest.raises(ValidationError):
        CloseSimulatedPositionInput(reason="")

    out = CloseSimulatedPositionOutput(
        success=True,
        order_id="ORD-CLOSE-01",
        status="QUEUED_FOR_NEXT_OPEN",
        closed_quantity=20,
        remaining_quantity=0,
    )
    assert out.closed_quantity == 20


# ==============================================================================
# ToolExecutionResult Envelope Tests
# ==============================================================================


def test_tool_execution_result_envelope():
    success_res = ToolExecutionResult(
        tool_name="get_market_data",
        success=True,
        data={"current_price": 2500.0},
    )
    assert success_res.success is True
    assert success_res.data["current_price"] == 2500.0

    error_res = ToolExecutionResult(
        tool_name="place_simulated_order",
        success=False,
        error="Order already staged for current candle step",
        error_type=ToolErrorType.ORDER_ALREADY_STAGED,
    )
    assert error_res.success is False
    assert error_res.error_type == ToolErrorType.ORDER_ALREADY_STAGED

    # Unknown fields forbidden
    with pytest.raises(ValidationError):
        ToolExecutionResult(
            tool_name="test",
            success=True,
            extra_payload="bad",  # type: ignore
        )


# ==============================================================================
# AgentDecision Structured Output Tests (Section 39)
# ==============================================================================


def test_agent_decision_valid():
    dec = AgentDecision(
        action=AgentAction.BUY,
        confidence=0.85,
        quantity=10,
        stop_loss=2450.0,
        take_profit=2600.0,
        reason="EMA9 crossover EMA20 in BULLISH trend regime",
        observations=["Bullish volume spike", "RSI 58 above midline"],
        tools_used=["get_market_data", "get_indicators", "get_market_regime"],
    )
    assert dec.action == AgentAction.BUY
    assert dec.confidence == 0.85
    assert dec.quantity == 10
    assert len(dec.observations) == 2


def test_agent_decision_hold_valid():
    dec = AgentDecision(
        action=AgentAction.HOLD,
        confidence=0.5,
        reason="Market is in SIDEWAYS regime, awaiting breakout",
    )
    assert dec.action == AgentAction.HOLD
    assert dec.quantity is None
    assert dec.stop_loss is None


def test_agent_decision_bounds_and_validations():
    # Confidence bounds: 0.0 <= conf <= 1.0
    with pytest.raises(ValidationError):
        AgentDecision(
            action=AgentAction.BUY,
            confidence=-0.1,
            reason="Negative confidence",
        )
    with pytest.raises(ValidationError):
        AgentDecision(
            action=AgentAction.BUY,
            confidence=1.05,
            reason="Excess confidence",
        )

    # Quantity must be > 0 if supplied
    with pytest.raises(ValidationError):
        AgentDecision(
            action=AgentAction.BUY,
            confidence=0.8,
            quantity=0,
            reason="Zero quantity",
        )

    # Prices must be > 0 if supplied
    with pytest.raises(ValidationError):
        AgentDecision(
            action=AgentAction.BUY,
            confidence=0.8,
            stop_loss=-5.0,
            reason="Negative stop loss",
        )

    # Reason cannot be blank
    with pytest.raises(ValidationError):
        AgentDecision(
            action=AgentAction.BUY,
            confidence=0.8,
            reason="   ",
        )

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        AgentDecision(
            action=AgentAction.HOLD,
            confidence=0.5,
            reason="Valid",
            execute_code="hack()",  # type: ignore
        )

    # Immutability
    dec = AgentDecision(
        action=AgentAction.HOLD,
        confidence=0.5,
        reason="Valid",
    )
    with pytest.raises(ValidationError):
        dec.confidence = 0.9  # type: ignore


# ==============================================================================
# Schema Serialization, Immutability & Boundary Edge Cases (Phase 7D)
# ==============================================================================


def test_all_tool_error_types_serialization():
    """Verify every ToolErrorType can be serialized and deserialized via ToolExecutionResult."""
    for err_type in ToolErrorType:
        res = ToolExecutionResult(
            tool_name="test_tool",
            success=False,
            error=f"Error code: {err_type.value}",
            error_type=err_type,
        )
        json_str = res.model_dump_json()
        deserialized = ToolExecutionResult.model_validate_json(json_str)
        assert deserialized.error_type == err_type
        assert deserialized.success is False


def test_schema_json_serialization_round_trips(sample_candle: MarketCandleSchema):
    """Verify JSON round-trip across inputs and outputs preserves exact values."""
    # 1. MarketCandleSchema
    c_json = sample_candle.model_dump_json()
    c_deserialized = MarketCandleSchema.model_validate_json(c_json)
    assert c_deserialized.open == sample_candle.open
    assert c_deserialized.timestamp == sample_candle.timestamp

    # 2. GetMarketDataOutput
    mkt_out = GetMarketDataOutput(
        symbol="RELIANCE",
        timeframe="15m",
        current_candle=sample_candle,
        recent_candles=[sample_candle],
        current_price=2515.0,
        price_change=15.0,
        price_change_pct=0.6,
        current_volume=100000.0,
    )
    mkt_json = mkt_out.model_dump_json()
    mkt_deserialized = GetMarketDataOutput.model_validate_json(mkt_json)
    assert mkt_deserialized.symbol == "RELIANCE"
    assert mkt_deserialized.current_price == 2515.0

    # 3. CalculatePositionSizeOutput
    calc_out = CalculatePositionSizeOutput(
        target_quantity=10,
        estimated_execution_price=2501.25,
        estimated_cost=25020.0,
        risk_amount=512.5,
        risk_pct_of_portfolio=0.51,
        position_exposure_pct=25.0,
        status="APPROVED",
    )
    calc_json = calc_out.model_dump_json()
    calc_deserialized = CalculatePositionSizeOutput.model_validate_json(calc_json)
    assert calc_deserialized.target_quantity == 10
    assert calc_deserialized.status == "APPROVED"

    # 4. PlaceSimulatedOrderOutput
    order_out = PlaceSimulatedOrderOutput(
        success=True,
        order_id="ORD-TEST-99",
        status=OrderStatus.PENDING,
        decision_price=2500.0,
        execution_stage="QUEUED_FOR_NEXT_OPEN",
        risk_metrics={"equity": 100000.0},
    )
    order_json = order_out.model_dump_json()
    order_deserialized = PlaceSimulatedOrderOutput.model_validate_json(order_json)
    assert order_deserialized.order_id == "ORD-TEST-99"
    assert order_deserialized.status == OrderStatus.PENDING

    # 5. AgentDecision
    dec = AgentDecision(
        action=AgentAction.BUY,
        confidence=0.9,
        quantity=5,
        stop_loss=2450.0,
        take_profit=2600.0,
        reason="Breakout confirmed",
        observations=["Strong volume", "RSI expanding"],
        tools_used=["get_market_data", "get_indicators"],
    )
    dec_json = dec.model_dump_json()
    dec_deserialized = AgentDecision.model_validate_json(dec_json)
    assert dec_deserialized.action == AgentAction.BUY
    assert dec_deserialized.confidence == 0.9
    assert dec_deserialized.observations == ["Strong volume", "RSI expanding"]


def test_strict_immutability_across_input_schemas():
    """Verify that input schemas are frozen and disallow runtime mutation."""
    inp_mkt = GetMarketDataInput(lookback=5)
    with pytest.raises(ValidationError):
        inp_mkt.lookback = 10  # type: ignore

    inp_calc = CalculatePositionSizeInput(entry_price=2500.0, stop_loss_price=2450.0)
    with pytest.raises(ValidationError):
        inp_calc.entry_price = 2600.0  # type: ignore

    inp_order = PlaceSimulatedOrderInput(side=OrderSide.BUY, quantity=10, reason="Valid")
    with pytest.raises(ValidationError):
        inp_order.quantity = 20  # type: ignore

    inp_close = CloseSimulatedPositionInput(quantity=5, reason="Exit")
    with pytest.raises(ValidationError):
        inp_close.quantity = 10  # type: ignore


def test_numeric_boundary_edge_cases():
    """Verify precise numeric boundary validation for all schema bounds."""
    # 1. CalculatePositionSizeInput: risk_per_trade bounds (0.0 < x <= 1.0)
    with pytest.raises(ValidationError):
        CalculatePositionSizeInput(entry_price=2500.0, stop_loss_price=2450.0, risk_per_trade=0.0)
    with pytest.raises(ValidationError):
        CalculatePositionSizeInput(
            entry_price=2500.0, stop_loss_price=2450.0, risk_per_trade=1.0001
        )
    inp_max_risk = CalculatePositionSizeInput(
        entry_price=2500.0, stop_loss_price=2450.0, risk_per_trade=1.0
    )
    assert inp_max_risk.risk_per_trade == 1.0

    # 2. AgentDecision: confidence bounds (0.0 <= x <= 1.0)
    dec_zero = AgentDecision(action=AgentAction.HOLD, confidence=0.0, reason="Zero confidence hold")
    assert dec_zero.confidence == 0.0
    dec_full = AgentDecision(action=AgentAction.BUY, confidence=1.0, reason="Max confidence buy")
    assert dec_full.confidence == 1.0
    with pytest.raises(ValidationError):
        AgentDecision(action=AgentAction.HOLD, confidence=-0.0001, reason="Negative")
    with pytest.raises(ValidationError):
        AgentDecision(action=AgentAction.HOLD, confidence=1.0001, reason="Over 1")

    # 3. GetMarketDataInput: lookback bounds (1 <= x <= 100)
    inp_min_lb = GetMarketDataInput(lookback=1)
    assert inp_min_lb.lookback == 1
    inp_max_lb = GetMarketDataInput(lookback=100)
    assert inp_max_lb.lookback == 100
    with pytest.raises(ValidationError):
        GetMarketDataInput(lookback=0)
    with pytest.raises(ValidationError):
        GetMarketDataInput(lookback=101)

    # 4. GetTradeHistoryInput: limit bounds (1 <= x <= 50)
    inp_min_lim = GetTradeHistoryInput(limit=1)
    assert inp_min_lim.limit == 1
    inp_max_lim = GetTradeHistoryInput(limit=50)
    assert inp_max_lim.limit == 50
    with pytest.raises(ValidationError):
        GetTradeHistoryInput(limit=0)
    with pytest.raises(ValidationError):
        GetTradeHistoryInput(limit=51)
