"""Unit tests for Phase 7B Mutating / Trading Agent Tools (Phase 7D).

Covers:
1. place_simulated_order
2. close_simulated_position
3. Single staged order per candle rule
4. Multi-candle lifecycle
5. RiskEngine rejection and retry semantics
6. ReplayContext bridge
7. End-to-end ChronologicalReplayEngine integration
"""

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from app.market_data.schema import CandleData
from app.trading.agent.schemas import (
    CloseSimulatedPositionInput,
    PlaceSimulatedOrderInput,
)
from app.trading.agent.tools import (
    ToolExecutionContext,
    close_simulated_position,
    get_position,
    get_trade_history,
    place_simulated_order,
)
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderSide, OrderStatus, OrderType
from app.trading.simulation.replay import ChronologicalReplayEngine, ReplayContext

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
def tool_context(base_candles: List[CandleData]) -> ToolExecutionContext:
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


# ==============================================================================
# 1. place_simulated_order Tests
# ==============================================================================


def test_place_simulated_order_success(tool_context: ToolExecutionContext):
    curr_close = float(tool_context.current_candle.close)
    inp = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=5,
        order_type=OrderType.MARKET,
        stop_loss=round(curr_close * 0.98, 2),
        take_profit=round(curr_close * 1.05, 2),
        reason="Agent momentum signal",
    )
    out = place_simulated_order(tool_context, inp)

    assert out.success is True
    assert out.order_id is not None
    assert out.status == OrderStatus.PENDING
    assert out.decision_price == curr_close
    assert out.execution_stage == "QUEUED_FOR_NEXT_OPEN"
    assert out.rejection_reason is None
    assert out.risk_metrics is not None

    # Staging check: order appended to context.staged_orders for candle t+1 Open fill
    assert len(tool_context.staged_orders) == 1
    staged = tool_context.staged_orders[0]
    assert staged.order_id == out.order_id
    assert staged.symbol == "RELIANCE"
    assert staged.quantity == 5
    assert staged.side == OrderSide.BUY
    assert staged.decision_time == tool_context.virtual_time

    # Critical invariant: Zero immediate fills at candle t Close
    assert tool_context.portfolio.cash == 100000.0
    assert tool_context.portfolio.get_position("RELIANCE") is None


def test_place_simulated_order_insufficient_cash(tool_context: ToolExecutionContext):
    # Try buying 10,000 shares (exceeds 100k capital)
    inp = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=10000,
        reason="Overleveraged attempt",
    )
    out = place_simulated_order(tool_context, inp)

    assert out.success is False
    assert out.status == OrderStatus.REJECTED
    assert out.execution_stage == "REJECTED"
    assert "Risk check failed" in str(out.rejection_reason)
    assert len(tool_context.staged_orders) == 0


def test_place_simulated_order_invalid_sl_tp(tool_context: ToolExecutionContext):
    curr_close = float(tool_context.current_candle.close)

    # Invalid Stop-Loss: SL >= decision price for BUY
    inp_sl = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=5,
        stop_loss=curr_close + 10.0,
        reason="Invalid SL",
    )
    out_sl = place_simulated_order(tool_context, inp_sl)
    assert out_sl.success is False
    assert out_sl.status == OrderStatus.REJECTED
    assert "Stop-loss price" in str(out_sl.rejection_reason)
    assert len(tool_context.staged_orders) == 0

    # Invalid Take-Profit: TP <= decision price for BUY
    inp_tp = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=5,
        take_profit=curr_close - 10.0,
        reason="Invalid TP",
    )
    out_tp = place_simulated_order(tool_context, inp_tp)
    assert out_tp.success is False
    assert out_tp.status == OrderStatus.REJECTED
    assert "Take-profit price" in str(out_tp.rejection_reason)
    assert len(tool_context.staged_orders) == 0


def test_one_staged_order_per_candle_step_rule(tool_context: ToolExecutionContext):
    curr_close = float(tool_context.current_candle.close)
    inp = PlaceSimulatedOrderInput(
        side=OrderSide.BUY,
        quantity=2,
        stop_loss=round(curr_close * 0.98, 2),
        reason="Order 1",
    )
    # Order 1: Succeeds
    out1 = place_simulated_order(tool_context, inp)
    assert out1.success is True
    assert len(tool_context.staged_orders) == 1

    # Order 2: Rejected by single staged order per candle rule
    out2 = place_simulated_order(tool_context, inp)
    assert out2.success is False
    assert out2.status == OrderStatus.REJECTED
    assert "Order already staged for current candle step" in str(out2.rejection_reason)
    assert len(tool_context.staged_orders) == 1


# ==============================================================================
# 2. close_simulated_position Tests
# ==============================================================================


def test_close_simulated_position_flat(tool_context: ToolExecutionContext):
    # No position open -> rejected
    inp = CloseSimulatedPositionInput(reason="Closing nonexistent")
    out = close_simulated_position(tool_context, inp)

    assert out.success is False
    assert out.status == "REJECTED"
    assert "No active open position" in str(out.rejection_reason)
    assert len(tool_context.staged_orders) == 0


def test_close_simulated_position_partial_and_full(tool_context: ToolExecutionContext):
    # Setup open position of 30 shares
    tool_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=30,
        price=2480.0,
        transaction_cost=20.0,
        slippage_cost=10.0,
        timestamp=tool_context.virtual_time,
    )

    # 1. Partial close: 10 shares
    inp_partial = CloseSimulatedPositionInput(quantity=10, reason="Partial profit")
    out_partial = close_simulated_position(tool_context, inp_partial)

    assert out_partial.success is True
    assert out_partial.status == "QUEUED_FOR_NEXT_OPEN"
    assert out_partial.closed_quantity == 10
    assert out_partial.remaining_quantity == 20
    assert len(tool_context.staged_orders) == 1

    staged = tool_context.staged_orders[0]
    assert staged.side == OrderSide.SELL
    assert staged.quantity == 10
    assert staged.order_type == OrderType.MARKET


def test_close_simulated_position_full_default(tool_context: ToolExecutionContext):
    # Setup open position of 15 shares
    tool_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=15,
        price=2480.0,
        transaction_cost=15.0,
        slippage_cost=5.0,
        timestamp=tool_context.virtual_time,
    )

    # Default close: quantity=None -> closes entire position (15 shares)
    inp_full = CloseSimulatedPositionInput(reason="Full exit")
    out_full = close_simulated_position(tool_context, inp_full)

    assert out_full.success is True
    assert out_full.closed_quantity == 15
    assert out_full.remaining_quantity == 0
    assert len(tool_context.staged_orders) == 1
    assert tool_context.staged_orders[0].quantity == 15


def test_close_simulated_position_exceeds_quantity(tool_context: ToolExecutionContext):
    tool_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2480.0,
        transaction_cost=10.0,
        slippage_cost=5.0,
        timestamp=tool_context.virtual_time,
    )

    # Try closing 25 shares when only 10 exist
    inp = CloseSimulatedPositionInput(quantity=25, reason="Excess close")
    out = close_simulated_position(tool_context, inp)

    assert out.success is False
    assert out.status == "REJECTED"
    assert "exceeds active position quantity" in str(out.rejection_reason)
    assert len(tool_context.staged_orders) == 0


def test_close_simulated_position_duplicate_order_blocked(tool_context: ToolExecutionContext):
    tool_context.portfolio.open_or_increase_position(
        symbol="RELIANCE",
        quantity=10,
        price=2480.0,
        transaction_cost=10.0,
        slippage_cost=5.0,
        timestamp=tool_context.virtual_time,
    )

    out1 = close_simulated_position(tool_context, CloseSimulatedPositionInput(quantity=5))
    assert out1.success is True

    # Calling again on same candle is blocked
    out2 = close_simulated_position(tool_context, CloseSimulatedPositionInput(quantity=5))
    assert out2.success is False
    assert "Order already staged" in str(out2.rejection_reason)


# ==============================================================================
# 3. Context Bridge & Multi-Candle Lifecycle Tests
# ==============================================================================


def test_tool_context_from_replay_bridge(base_candles: List[CandleData]):
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    current = base_candles[-1]

    rep_ctx = ReplayContext(
        current_candle=current,
        visible_candles=tuple(base_candles),
        portfolio_state=portfolio.get_state(),
        virtual_time=current.timestamp,
        step_index=len(base_candles) - 1,
        total_candles=len(base_candles),
    )

    tool_ctx = ToolExecutionContext.from_replay(
        replay_context=rep_ctx,
        symbol="RELIANCE",
        timeframe="15m",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    assert tool_ctx.symbol == "RELIANCE"
    assert tool_ctx.timeframe == "15m"
    assert tool_ctx.virtual_time == rep_ctx.virtual_time
    assert tool_ctx.current_candle == rep_ctx.current_candle
    assert len(tool_ctx.visible_candles) == 20
    assert tool_ctx.portfolio is portfolio
    assert tool_ctx.risk_engine is risk_engine
    assert tool_ctx.staged_orders == []


def test_multi_candle_staging_lifecycle(base_candles: List[CandleData]):
    """Verify that an order staged on candle t0 does not block a new order on candle t1."""
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    shared_staged_orders: List = []

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
        staged_orders=shared_staged_orders,
    )
    inp0 = PlaceSimulatedOrderInput(side=OrderSide.BUY, quantity=2, reason="Order at t0")
    out0 = place_simulated_order(ctx0, inp0)
    assert out0.success is True
    assert len(shared_staged_orders) == 1
    assert shared_staged_orders[0].decision_time == c0.timestamp

    # Repeated call on candle 0 -> blocked
    out0_repeat = place_simulated_order(ctx0, inp0)
    assert out0_repeat.success is False
    assert "Order already staged for current candle step" in str(out0_repeat.rejection_reason)

    # Advance to Candle 1 (new virtual time)
    c1 = base_candles[1]
    ctx1 = ToolExecutionContext(
        symbol="RELIANCE",
        timeframe="15m",
        virtual_time=c1.timestamp,
        current_candle=c1,
        visible_candles=base_candles[:2],
        portfolio=portfolio,
        risk_engine=risk_engine,
        staged_orders=shared_staged_orders,
    )

    # Order at candle 1 must succeed because no order has decision_time == c1.timestamp
    inp1 = PlaceSimulatedOrderInput(side=OrderSide.BUY, quantity=3, reason="Order at t1")
    out1 = place_simulated_order(ctx1, inp1)
    assert out1.success is True
    assert len(shared_staged_orders) == 2
    assert shared_staged_orders[1].decision_time == c1.timestamp

    # Repeated call on candle 1 -> blocked
    out1_repeat = place_simulated_order(ctx1, inp1)
    assert out1_repeat.success is False
    assert "Order already staged for current candle step" in str(out1_repeat.rejection_reason)


def test_repeated_tool_calls_after_risk_rejection(tool_context: ToolExecutionContext):
    """Verify that if an order is rejected by RiskEngine, a subsequent valid order can be staged."""
    # Attempt 1: Excessive size -> rejected by risk
    inp_bad = PlaceSimulatedOrderInput(side=OrderSide.BUY, quantity=10000, reason="Excessive")
    out_bad = place_simulated_order(tool_context, inp_bad)
    assert out_bad.success is False
    assert len(tool_context.staged_orders) == 0

    # Attempt 2: Safe size on the SAME candle -> succeeds and stages
    inp_good = PlaceSimulatedOrderInput(side=OrderSide.BUY, quantity=4, reason="Adjusted safe size")
    out_good = place_simulated_order(tool_context, inp_good)
    assert out_good.success is True
    assert len(tool_context.staged_orders) == 1

    # Attempt 3: Order already staged -> rejected by single order rule
    out_blocked = place_simulated_order(tool_context, inp_good)
    assert out_blocked.success is False
    assert "Order already staged for current candle step" in str(out_blocked.rejection_reason)


# ==============================================================================
# 4. End-to-End ChronologicalReplayEngine Integration
# ==============================================================================


def test_agent_tools_in_replay_engine_lifecycle(base_candles: List[CandleData]):
    """End-to-end integration test verifying that Phase 7B tools integrate seamlessly with ReplayEngine."""
    portfolio = PortfolioTracker(initial_capital=100000.0)
    risk_engine = RiskEngine()
    engine = ChronologicalReplayEngine(
        candles=base_candles[:5],
        symbol="RELIANCE",
        portfolio=portfolio,
        risk_engine=risk_engine,
    )

    action_history: List[str] = []

    def mock_agent_strategy(replay_ctx: ReplayContext):
        # Bridge to ToolExecutionContext
        staged_orders: List = []
        tool_ctx = ToolExecutionContext.from_replay(
            replay_context=replay_ctx,
            symbol="RELIANCE",
            timeframe="15m",
            portfolio=engine.portfolio,
            risk_engine=engine.risk_engine,
            staged_orders=staged_orders,
        )

        pos = get_position(tool_ctx)

        if replay_ctx.step_index == 0:
            # Bar 0 Close: Flat. Stage BUY order.
            assert not pos.is_open
            mkt_close = float(replay_ctx.current_candle.close)
            out = place_simulated_order(
                tool_ctx,
                PlaceSimulatedOrderInput(
                    side=OrderSide.BUY,
                    quantity=4,
                    stop_loss=round(mkt_close * 0.98, 2),
                    reason="Agent BUY at step 0",
                ),
            )
            assert out.success is True
            action_history.append("PLACED_BUY")
        elif replay_ctx.step_index == 1:
            # Bar 1 Close: Order was filled at Bar 1 Open! Position is now open.
            assert pos.is_open
            assert pos.quantity == 4
            # Close position
            out = close_simulated_position(
                tool_ctx,
                CloseSimulatedPositionInput(reason="Agent CLOSE at step 1"),
            )
            assert out.success is True
            action_history.append("PLACED_CLOSE")
        elif replay_ctx.step_index == 2:
            # Bar 2 Close: Close was filled at Bar 2 Open! Position is flat.
            assert not pos.is_open
            hist = get_trade_history(tool_ctx)
            assert hist.total_closed_trades == 1
            action_history.append("VERIFIED_CLOSED")

        return tool_ctx.staged_orders

    # Run replay with strategy
    summary = engine.run(strategy=mock_agent_strategy)

    assert action_history == ["PLACED_BUY", "PLACED_CLOSE", "VERIFIED_CLOSED"]
    assert len(summary.trades) == 1
    assert len(engine.portfolio.closed_trades) == 1
    assert len(engine.execution_history) == 2  # 1 BUY fill + 1 SELL fill
