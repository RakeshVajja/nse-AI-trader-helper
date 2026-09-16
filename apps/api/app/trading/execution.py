"""Deterministic simulated trade execution engine."""

from __future__ import annotations

import logging
from typing import Optional

from app.market_data.schema import CandleData
from app.trading.portfolio import PortfolioTracker
from app.trading.schemas import (
    ExecutionConfig,
    ExecutionResult,
    OrderRequest,
    OrderSide,
    OrderStatus,
)

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Deterministic simulated trade execution model.

    Execution Rules (per Project Specification Sections 31-33):
    1. Market orders execute strictly at the NEXT available candle's OPEN price ($P_{t+1, open}$).
    2. Decisions made at candle $t$ NEVER execute at the close of candle $t$ (eliminates look-ahead bias).
    3. Slippage is applied deterministically:
       - BUY: market_price * (1 + slippage_pct)
       - SELL: market_price * (1 - slippage_pct)
       Default slippage = 0.05% (0.0005).
    4. Transaction costs and slippage impact are calculated deterministically and routed to PortfolioTracker.
    5. If next candle data is unavailable, orders cannot be filled.
    """

    def __init__(self, config: Optional[ExecutionConfig] = None) -> None:
        self.config = config if config is not None else ExecutionConfig()

    def calculate_execution_price(self, market_price: float, side: OrderSide) -> float:
        """Calculate fill price with directional slippage applied.

        Args:
            market_price: Raw open price of the next candle ($P_{t+1, open}$).
            side: BUY or SELL.

        Returns:
            Executed price with slippage.
        """
        if market_price <= 0.0:
            raise ValueError(f"market_price must be > 0.0, got {market_price}")

        slippage = self.config.slippage_pct
        if side == OrderSide.BUY:
            # Buyer pays higher price
            exec_price = market_price * (1.0 + slippage)
        else:
            # Seller receives lower price
            exec_price = market_price * (1.0 - slippage)

        return round(exec_price, 4)

    def calculate_transaction_cost(self, nominal_value: float) -> float:
        """Calculate transaction fees / commissions.

        Args:
            nominal_value: Total traded nominal value (quantity * price).

        Returns:
            Total transaction fee in INR.
        """
        if nominal_value < 0.0:
            raise ValueError(f"nominal_value cannot be negative, got {nominal_value}")

        fee = (nominal_value * self.config.brokerage_rate) + self.config.fixed_fee_per_order
        return round(fee, 4)

    def calculate_slippage_cost(
        self, market_price: float, execution_price: float, quantity: int
    ) -> float:
        """Calculate total slippage cost impact.

        Args:
            market_price: Raw benchmark market price (e.g. Next Candle Open).
            execution_price: Final executed fill price with slippage.
            quantity: Number of units traded.

        Returns:
            Slippage cost impact in INR.
        """
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")

        slippage_per_unit = abs(execution_price - market_price)
        return round(slippage_per_unit * quantity, 4)

    def execute_order(
        self,
        order: OrderRequest,
        next_candle: Optional[CandleData],
        portfolio: PortfolioTracker,
    ) -> ExecutionResult:
        """Execute a simulated order against the next available candle.

        Args:
            order: OrderRequest submitted after decision candle t.
            next_candle: CandleData for candle t+1 (next bar), or None if at end of series.
            portfolio: Active authoritative PortfolioTracker.

        Returns:
            ExecutionResult containing execution status, fill price, costs, and timestamps.
        """
        clean_symbol = order.symbol.strip().upper()

        # 1. Check next candle availability
        if next_candle is None:
            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                decision_time=order.decision_time,
                rejection_reason="Next candle unavailable for execution. Market orders cannot execute at decision candle.",
            )

        # 2. Enforce strict no-look-ahead chronological sequencing
        if next_candle.timestamp <= order.decision_time:
            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                decision_time=order.decision_time,
                rejection_reason=(
                    f"Next candle timestamp ({next_candle.timestamp.isoformat()}) must be strictly "
                    f"after decision timestamp ({order.decision_time.isoformat()})."
                ),
            )

        # 3. Market orders execute at next candle OPEN price
        market_price = float(next_candle.open)
        if market_price <= 0.0:
            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.REJECTED,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                decision_time=order.decision_time,
                rejection_reason=f"Invalid next candle open price: {market_price}",
            )

        execution_price = self.calculate_execution_price(market_price, order.side)
        nominal_val = order.quantity * execution_price
        tx_cost = self.calculate_transaction_cost(nominal_val)
        slip_cost = self.calculate_slippage_cost(market_price, execution_price, order.quantity)
        exec_time = next_candle.timestamp

        # 4. Route execution to portfolio accounting
        if order.side == OrderSide.BUY:
            portfolio.open_or_increase_position(
                symbol=clean_symbol,
                quantity=order.quantity,
                price=execution_price,
                timestamp=exec_time,
                transaction_cost=tx_cost,
                slippage_cost=slip_cost,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
            )
            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.FILLED,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                market_price=market_price,
                execution_price=execution_price,
                transaction_cost=tx_cost,
                slippage_cost=slip_cost,
                executed_at=exec_time,
                decision_time=order.decision_time,
                trade_record=None,
            )

        if order.side == OrderSide.SELL:
            # Check open position exists
            pos = portfolio.get_position(clean_symbol)
            if pos is None or pos.quantity == 0:
                return ExecutionResult(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    decision_time=order.decision_time,
                    rejection_reason=f"Cannot execute SELL order: No open position exists for {clean_symbol}.",
                )

            if order.quantity > pos.quantity:
                return ExecutionResult(
                    order_id=order.order_id,
                    status=OrderStatus.REJECTED,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    decision_time=order.decision_time,
                    rejection_reason=(
                        f"Requested sell quantity ({order.quantity}) exceeds open position quantity ({pos.quantity})."
                    ),
                )

            trade_record = portfolio.close_or_reduce_position(
                symbol=clean_symbol,
                quantity=order.quantity,
                price=execution_price,
                timestamp=exec_time,
                transaction_cost=tx_cost,
                slippage_cost=slip_cost,
                reason=order.reason or "ORDER_EXECUTION",
            )

            return ExecutionResult(
                order_id=order.order_id,
                status=OrderStatus.FILLED,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                market_price=market_price,
                execution_price=execution_price,
                transaction_cost=tx_cost,
                slippage_cost=slip_cost,
                executed_at=exec_time,
                decision_time=order.decision_time,
                trade_record=trade_record,
            )

        return ExecutionResult(
            order_id=order.order_id,
            status=OrderStatus.REJECTED,
            symbol=clean_symbol,
            side=order.side,
            quantity=order.quantity,
            decision_time=order.decision_time,
            rejection_reason=f"Unsupported order side: {order.side}",
        )
