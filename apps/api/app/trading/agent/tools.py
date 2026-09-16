"""Core Agent Tools Implementation (Phase 7B).

Provides the 9 thin typed agent tools specified in Section 37-38:
1. get_market_data()
2. get_indicators()
3. get_market_regime()
4. get_position()
5. get_portfolio()
6. get_trade_history()
7. calculate_position_size()
8. place_simulated_order()
9. close_simulated_position()

All tools operate strictly within the provided ToolExecutionContext.
Mutating tools stage orders for candle t+1 Open execution through the authoritative
RiskEngine and order queue. Immediate fills at candle t Close are strictly prohibited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence

from app.indicators.engine import QuantitativeIndicatorEngine
from app.indicators.regime import classify_market_regime_snapshot
from app.market_data.schema import CandleData
from app.trading.agent.schemas import (
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
    TradeRecordSchema,
)
from app.trading.portfolio import PortfolioTracker
from app.trading.risk import RiskEngine
from app.trading.schemas import OrderRequest, OrderSide, OrderStatus, OrderType
from app.trading.simulation.replay import ReplayContext


@dataclass
class ToolExecutionContext:
    """Authoritative execution context bound to an active simulation session."""

    symbol: str
    timeframe: str
    virtual_time: datetime
    current_candle: CandleData
    visible_candles: Sequence[CandleData]
    portfolio: PortfolioTracker
    risk_engine: RiskEngine
    staged_orders: List[OrderRequest] = field(default_factory=list)

    @classmethod
    def from_replay(
        cls,
        replay_context: ReplayContext,
        symbol: str,
        timeframe: str,
        portfolio: PortfolioTracker,
        risk_engine: RiskEngine,
        staged_orders: Optional[List[OrderRequest]] = None,
    ) -> ToolExecutionContext:
        """Construct ToolExecutionContext directly from simulation ReplayContext."""
        return cls(
            symbol=symbol.strip().upper(),
            timeframe=timeframe,
            virtual_time=replay_context.virtual_time,
            current_candle=replay_context.current_candle,
            visible_candles=replay_context.visible_candles,
            portfolio=portfolio,
            risk_engine=risk_engine,
            staged_orders=staged_orders if staged_orders is not None else [],
        )


def _to_market_candle(candle: CandleData) -> MarketCandleSchema:
    """Convert raw CandleData to typed MarketCandleSchema."""
    return MarketCandleSchema(
        timestamp=candle.timestamp,
        open=float(candle.open),
        high=float(candle.high),
        low=float(candle.low),
        close=float(candle.close),
        volume=float(candle.volume),
    )


# ==============================================================================
# 1. get_market_data
# ==============================================================================


def get_market_data(
    context: ToolExecutionContext,
    inp: Optional[GetMarketDataInput] = None,
) -> GetMarketDataOutput:
    """Return recent completed OHLCV, current price, price change, and volume."""
    inp = inp or GetMarketDataInput()
    if inp.symbol and inp.symbol.strip().upper() != context.symbol:
        raise ValueError(
            f"Symbol mismatch: tool context is locked to '{context.symbol}', but received '{inp.symbol}'."
        )

    candles = context.visible_candles
    if not candles:
        raise ValueError("Tool execution context has no visible candles.")

    curr = candles[-1]
    curr_schema = _to_market_candle(curr)
    recent = [_to_market_candle(c) for c in candles[-inp.lookback :]]
    current_price = float(curr.close)

    if len(candles) >= 2:
        prev_close = float(candles[-2].close)
        price_change = round(current_price - prev_close, 4)
        price_change_pct = (
            round(((current_price - prev_close) / prev_close) * 100.0, 4)
            if prev_close > 0.0
            else 0.0
        )
    else:
        price_change = 0.0
        price_change_pct = 0.0

    return GetMarketDataOutput(
        symbol=context.symbol,
        timeframe=context.timeframe,
        current_candle=curr_schema,
        recent_candles=recent,
        current_price=current_price,
        price_change=price_change,
        price_change_pct=price_change_pct,
        current_volume=float(curr.volume),
    )


# ==============================================================================
# 2. get_indicators
# ==============================================================================


def get_indicators(
    context: ToolExecutionContext,
    inp: Optional[GetIndicatorsInput] = None,
) -> GetIndicatorsOutput:
    """Return latest technical indicators calculated on visible completed candles."""
    inp = inp or GetIndicatorsInput()
    if inp.symbol and inp.symbol.strip().upper() != context.symbol:
        raise ValueError(
            f"Symbol mismatch: tool context is locked to '{context.symbol}', but received '{inp.symbol}'."
        )

    candles = context.visible_candles
    if not candles:
        raise ValueError("Tool execution context has no visible candles.")

    curr = candles[-1]

    # Delegate to QuantitativeIndicatorEngine
    snapshot = QuantitativeIndicatorEngine.compute_snapshot(
        symbol=context.symbol,
        timeframe=context.timeframe,
        candles=candles,
    )

    if snapshot is None:
        return GetIndicatorsOutput(
            symbol=context.symbol,
            timestamp=curr.timestamp,
            close=float(curr.close),
            is_warmed_up=False,
        )

    core_values = [
        snapshot.ema9,
        snapshot.ema20,
        snapshot.sma50,
        snapshot.rsi14,
        snapshot.macd,
        snapshot.macd_signal,
        snapshot.macd_histogram,
    ]
    is_warmed_up = all(v is not None for v in core_values)

    return GetIndicatorsOutput(
        symbol=context.symbol,
        timestamp=curr.timestamp,
        close=float(curr.close),
        ema_9=snapshot.ema9,
        ema_20=snapshot.ema20,
        sma_50=snapshot.sma50,
        rsi_14=snapshot.rsi14,
        macd=snapshot.macd,
        macd_signal=snapshot.macd_signal,
        macd_histogram=snapshot.macd_histogram,
        is_warmed_up=is_warmed_up,
    )


# ==============================================================================
# 3. get_market_regime
# ==============================================================================


def get_market_regime(
    context: ToolExecutionContext,
    inp: Optional[GetMarketRegimeInput] = None,
) -> GetMarketRegimeOutput:
    """Return deterministic trend and rolling volatility regime classification."""
    inp = inp or GetMarketRegimeInput()
    if inp.symbol and inp.symbol.strip().upper() != context.symbol:
        raise ValueError(
            f"Symbol mismatch: tool context is locked to '{context.symbol}', but received '{inp.symbol}'."
        )

    candles = context.visible_candles
    if not candles:
        raise ValueError("Tool execution context has no visible candles.")

    curr = candles[-1]
    regime_snapshot = classify_market_regime_snapshot(candles)

    if regime_snapshot is None:
        return GetMarketRegimeOutput(
            symbol=context.symbol,
            timestamp=curr.timestamp,
            trend_regime=None,
            volatility_regime=None,
            trend_signals=None,
            volatility_metrics=None,
        )

    return GetMarketRegimeOutput(
        symbol=context.symbol,
        timestamp=curr.timestamp,
        trend_regime=regime_snapshot.trend_regime,
        volatility_regime=regime_snapshot.volatility_regime,
        trend_signals=regime_snapshot.trend_details,
        volatility_metrics=regime_snapshot.volatility_details,
    )


# ==============================================================================
# 4. get_position
# ==============================================================================


def get_position(
    context: ToolExecutionContext,
    inp: Optional[GetPositionInput] = None,
) -> GetPositionOutput:
    """Return active open position details marked to market at candle t Close."""
    inp = inp or GetPositionInput()
    target_sym = inp.symbol.strip().upper() if inp.symbol else context.symbol
    if target_sym != context.symbol:
        raise ValueError(
            f"Symbol mismatch: tool context is locked to '{context.symbol}', but received '{inp.symbol}'."
        )

    pos = context.portfolio.get_position(target_sym)
    curr_close = float(context.current_candle.close)

    if pos is None or not pos.is_open or pos.quantity <= 0:
        return GetPositionOutput(
            symbol=target_sym,
            is_open=False,
            quantity=0,
            average_entry_price=None,
            current_price=curr_close,
            market_value=0.0,
            stop_loss=None,
            take_profit=None,
            unrealized_pnl=0.0,
            unrealized_pnl_pct=0.0,
            entry_time=None,
        )

    return GetPositionOutput(
        symbol=target_sym,
        is_open=pos.is_open,
        quantity=pos.quantity,
        average_entry_price=pos.average_entry_price,
        current_price=pos.current_price,
        market_value=pos.market_value,
        stop_loss=pos.stop_loss,
        take_profit=pos.take_profit,
        unrealized_pnl=pos.unrealized_gross_pnl,
        unrealized_pnl_pct=pos.unrealized_pnl_pct,
        entry_time=pos.entry_time,
    )


# ==============================================================================
# 5. get_portfolio
# ==============================================================================


def get_portfolio(
    context: ToolExecutionContext,
    inp: Optional[GetPortfolioInput] = None,
) -> GetPortfolioOutput:
    """Return authoritative portfolio accounting metrics and cash balances."""
    _ = inp  # Parameterless tool
    st = context.portfolio.get_state()
    return GetPortfolioOutput(
        initial_capital=st.initial_capital,
        cash=st.cash,
        total_market_value=st.total_market_value,
        total_portfolio_value=st.total_portfolio_value,
        realized_gross_pnl=st.realized_gross_pnl,
        realized_net_pnl=st.realized_net_pnl,
        unrealized_gross_pnl=st.unrealized_gross_pnl,
        total_transaction_costs=st.total_transaction_costs,
        total_slippage_cost=st.total_slippage_cost,
        gross_pnl=st.gross_pnl,
        net_pnl=st.net_pnl,
        total_return_pct=st.total_return_pct,
        exposure_pct=st.exposure_pct,
        daily_starting_equity=st.daily_starting_equity,
        daily_realized_pnl=st.daily_realized_pnl,
        open_positions_count=st.open_positions_count,
    )


# ==============================================================================
# 6. get_trade_history
# ==============================================================================


def get_trade_history(
    context: ToolExecutionContext,
    inp: Optional[GetTradeHistoryInput] = None,
) -> GetTradeHistoryOutput:
    """Return recent completed trades closed on or before candle t."""
    inp = inp or GetTradeHistoryInput()
    filter_sym = inp.symbol.strip().upper() if inp.symbol else None

    trades = context.portfolio.closed_trades
    if filter_sym:
        trades = [t for t in trades if t.symbol == filter_sym]

    total_count = len(trades)
    recent = trades[-inp.limit :]

    trade_schemas = [
        TradeRecordSchema(
            trade_id=t.trade_id,
            symbol=t.symbol,
            side=t.side,
            quantity=t.quantity,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            gross_pnl=t.gross_pnl,
            net_pnl=t.net_pnl,
            transaction_costs=t.transaction_costs,
            slippage_cost=t.slippage_cost,
            entry_time=t.entry_time,
            exit_time=t.exit_time,
            exit_reason=t.exit_reason,
        )
        for t in recent
    ]

    return GetTradeHistoryOutput(
        trades=trade_schemas,
        total_closed_trades=total_count,
    )


# ==============================================================================
# 7. calculate_position_size
# ==============================================================================


def calculate_position_size(
    context: ToolExecutionContext,
    inp: CalculatePositionSizeInput,
) -> CalculatePositionSizeOutput:
    """Deterministically calculate maximum safe position size respecting all risk limits."""
    target_sym = inp.symbol.strip().upper() if inp.symbol else context.symbol
    if target_sym != context.symbol:
        raise ValueError(
            f"Symbol mismatch: tool context is locked to '{context.symbol}', but received '{inp.symbol}'."
        )

    # For long spot trades, stop loss must be strictly less than planned entry
    if inp.stop_loss_price >= inp.entry_price:
        return CalculatePositionSizeOutput(
            target_quantity=0,
            estimated_execution_price=inp.entry_price,
            estimated_cost=0.0,
            risk_amount=0.0,
            risk_pct_of_portfolio=0.0,
            position_exposure_pct=0.0,
            status="REJECTED",
            reason="Stop-loss price must be strictly less than entry price for BUY orders.",
        )

    # Support optional per-trade risk fraction override
    if inp.risk_per_trade is not None:
        custom_config = context.risk_engine.config.model_copy(
            update={"max_risk_per_trade": inp.risk_per_trade}
        )
        engine = RiskEngine(
            config=custom_config,
            execution_config=context.risk_engine.execution_config,
        )
    else:
        engine = context.risk_engine

    qty = engine.calculate_position_size(
        symbol=target_sym,
        price=inp.entry_price,
        stop_loss=inp.stop_loss_price,
        portfolio=context.portfolio,
    )

    est_fill = engine.estimate_execution_price(inp.entry_price, OrderSide.BUY)
    nominal = round(qty * est_fill, 4)
    tx_cost = engine.estimate_transaction_cost(nominal)
    est_cost = round(nominal + tx_cost, 4)
    risk_amt = round(qty * max(0.0, est_fill - inp.stop_loss_price), 4)

    equity = context.portfolio.get_state().total_portfolio_value
    risk_pct = round((risk_amt / equity) * 100.0, 4) if equity > 0.0 else 0.0
    pos_exp = round((nominal / equity) * 100.0, 4) if equity > 0.0 else 0.0
    status = "APPROVED" if qty > 0 else "REJECTED"
    reason = (
        None if qty > 0 else "Calculated safe quantity is 0 shares due to risk or capital limits."
    )

    return CalculatePositionSizeOutput(
        target_quantity=qty,
        estimated_execution_price=est_fill,
        estimated_cost=est_cost,
        risk_amount=risk_amt,
        risk_pct_of_portfolio=risk_pct,
        position_exposure_pct=pos_exp,
        status=status,
        reason=reason,
    )


# ==============================================================================
# 8. place_simulated_order
# ==============================================================================


def place_simulated_order(
    context: ToolExecutionContext,
    inp: PlaceSimulatedOrderInput,
) -> PlaceSimulatedOrderOutput:
    """Submit simulated order to authoritative RiskEngine and stage for next candle Open."""
    decision_price = float(context.current_candle.close)

    # 1. Single staged order per candle step enforcement
    if any(o.decision_time == context.virtual_time for o in context.staged_orders):
        return PlaceSimulatedOrderOutput(
            success=False,
            order_id=None,
            status=OrderStatus.REJECTED,
            decision_price=decision_price,
            execution_stage="REJECTED",
            rejection_reason="Order already staged for current candle step.",
        )

    # 2. SL / TP boundary validation for BUY orders
    if inp.side == OrderSide.BUY:
        if inp.stop_loss is not None and inp.stop_loss >= decision_price:
            return PlaceSimulatedOrderOutput(
                success=False,
                order_id=None,
                status=OrderStatus.REJECTED,
                decision_price=decision_price,
                execution_stage="REJECTED",
                rejection_reason=(
                    f"Stop-loss price ({inp.stop_loss}) must be strictly less than "
                    f"decision price ({decision_price}) for BUY orders."
                ),
            )
        if inp.take_profit is not None and inp.take_profit <= decision_price:
            return PlaceSimulatedOrderOutput(
                success=False,
                order_id=None,
                status=OrderStatus.REJECTED,
                decision_price=decision_price,
                execution_stage="REJECTED",
                rejection_reason=(
                    f"Take-profit price ({inp.take_profit}) must be strictly greater than "
                    f"decision price ({decision_price}) for BUY orders."
                ),
            )

    # 3. Construct OrderRequest
    order = OrderRequest(
        symbol=context.symbol,
        side=inp.side,
        order_type=inp.order_type,
        quantity=inp.quantity,
        decision_time=context.virtual_time,
        decision_price=decision_price,
        stop_loss=inp.stop_loss,
        take_profit=inp.take_profit,
        reason=inp.reason,
    )

    # 4. Authoritative RiskEngine validation
    risk_res = context.risk_engine.validate_order(
        order=order,
        portfolio=context.portfolio,
        current_price=decision_price,
    )

    if not risk_res.approved:
        return PlaceSimulatedOrderOutput(
            success=False,
            order_id=order.order_id,
            status=OrderStatus.REJECTED,
            decision_price=decision_price,
            execution_stage="REJECTED",
            rejection_reason=f"Risk check failed: {risk_res.rejection_reason}",
            risk_metrics=risk_res.risk_metrics,
        )

    # 5. Staged for candle t+1 Open execution
    context.staged_orders.append(order)
    return PlaceSimulatedOrderOutput(
        success=True,
        order_id=order.order_id,
        status=OrderStatus.PENDING,
        decision_price=decision_price,
        execution_stage="QUEUED_FOR_NEXT_OPEN",
        rejection_reason=None,
        risk_metrics=risk_res.risk_metrics,
    )


# ==============================================================================
# 9. close_simulated_position
# ==============================================================================


def close_simulated_position(
    context: ToolExecutionContext,
    inp: Optional[CloseSimulatedPositionInput] = None,
) -> CloseSimulatedPositionOutput:
    """Submit close request for an active position through RiskEngine and stage for next candle Open."""
    inp = inp or CloseSimulatedPositionInput()
    decision_price = float(context.current_candle.close)

    # 1. Single staged order per candle step enforcement
    if any(o.decision_time == context.virtual_time for o in context.staged_orders):
        return CloseSimulatedPositionOutput(
            success=False,
            order_id=None,
            status="REJECTED",
            closed_quantity=0,
            remaining_quantity=0,
            rejection_reason="Order already staged for current candle step.",
        )

    # 2. Check active open position
    pos = context.portfolio.get_position(context.symbol)
    if pos is None or not pos.is_open or pos.quantity <= 0:
        return CloseSimulatedPositionOutput(
            success=False,
            order_id=None,
            status="REJECTED",
            closed_quantity=0,
            remaining_quantity=0,
            rejection_reason=f"No active open position to close for {context.symbol}.",
        )

    # 3. Determine quantity
    close_qty = inp.quantity if inp.quantity is not None else pos.quantity
    if close_qty > pos.quantity:
        return CloseSimulatedPositionOutput(
            success=False,
            order_id=None,
            status="REJECTED",
            closed_quantity=0,
            remaining_quantity=pos.quantity,
            rejection_reason=(
                f"Requested close quantity ({close_qty}) exceeds active position quantity ({pos.quantity})."
            ),
        )

    # 4. Construct OrderRequest (SELL to close)
    order = OrderRequest(
        symbol=context.symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=close_qty,
        decision_time=context.virtual_time,
        decision_price=decision_price,
        reason=inp.reason,
    )

    # 5. Authoritative RiskEngine validation
    risk_res = context.risk_engine.validate_order(
        order=order,
        portfolio=context.portfolio,
        current_price=decision_price,
    )

    if not risk_res.approved:
        return CloseSimulatedPositionOutput(
            success=False,
            order_id=order.order_id,
            status="REJECTED",
            closed_quantity=0,
            remaining_quantity=pos.quantity,
            rejection_reason=f"Risk check failed: {risk_res.rejection_reason}",
        )

    # 6. Stage order for candle t+1 Open execution
    context.staged_orders.append(order)
    remaining_qty = pos.quantity - close_qty
    return CloseSimulatedPositionOutput(
        success=True,
        order_id=order.order_id,
        status="QUEUED_FOR_NEXT_OPEN",
        closed_quantity=close_qty,
        remaining_quantity=remaining_qty,
        rejection_reason=None,
    )
