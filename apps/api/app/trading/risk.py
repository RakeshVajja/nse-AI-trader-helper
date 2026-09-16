"""Authoritative deterministic risk engine and order validation layer."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from app.trading.portfolio import PortfolioTracker
from app.trading.schemas import (
    ExecutionConfig,
    OrderRequest,
    OrderSide,
    RiskCheckResult,
    RiskConfig,
)

logger = logging.getLogger(__name__)


class RiskEngine:
    """Authoritative deterministic risk engine.

    Enforces risk controls per Project Specification Section 36:
    1. Order Validity (symbol, quantity > 0, price > 0, SELL position sufficiency).
    2. Available Cash Sufficiency (cash required including slippage and fees <= available cash).
    3. Maximum Daily Loss Limit (intraday loss <= max_daily_loss * daily_starting_equity).
    4. Stop-Loss & Take-Profit Validity (SL < entry, TP > entry for BUY, SL > 0, TP > 0).
    5. Maximum Risk Per Trade (quantity * (entry - SL) <= equity * max_risk_per_trade).
    6. Maximum Position Exposure ((existing_qty + new_qty) * entry <= equity * max_position_exposure).
    7. Maximum Portfolio Exposure (total_market_value <= equity * max_portfolio_exposure).

    Also provides:
    - calculate_position_size(): Deterministically sizes orders based on capital, risk, and entry/SL.
    """

    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        execution_config: Optional[ExecutionConfig] = None,
    ) -> None:
        self.config = config if config is not None else RiskConfig()
        self.execution_config = (
            execution_config if execution_config is not None else ExecutionConfig()
        )

    def estimate_execution_price(self, price: float, side: OrderSide) -> float:
        """Estimate execution fill price using directional slippage convention."""
        if price <= 0.0:
            raise ValueError(f"price must be > 0.0, got {price}")
        if side == OrderSide.BUY:
            return round(price * (1.0 + self.execution_config.slippage_pct), 4)
        return round(price * (1.0 - self.execution_config.slippage_pct), 4)

    def estimate_transaction_cost(self, nominal: float) -> float:
        """Estimate transaction fees for a nominal traded amount."""
        if nominal < 0.0:
            raise ValueError(f"nominal cannot be negative, got {nominal}")
        fee = (
            nominal * self.execution_config.brokerage_rate
        ) + self.execution_config.fixed_fee_per_order
        return round(fee, 4)

    def validate_order(
        self,
        order: OrderRequest,
        portfolio: PortfolioTracker,
        current_price: Optional[float] = None,
    ) -> RiskCheckResult:
        """Validate an order against all authoritative risk controls.

        Args:
            order: OrderRequest to validate.
            portfolio: Authoritative active PortfolioTracker.
            current_price: Optional current reference market price (defaults to order.decision_price).

        Returns:
            RiskCheckResult indicating approval or rejection with diagnostic details.
        """
        clean_symbol = order.symbol.strip().upper() if order.symbol else ""
        price = current_price if current_price is not None else order.decision_price

        # ------------------------------------------------------------------
        # 1. Order Validity
        # ------------------------------------------------------------------
        if not clean_symbol:
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=0.0,
                rejection_reason="Order symbol cannot be empty.",
            )

        if price is None or price <= 0.0:
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=0.0,
                rejection_reason=f"Valid positive reference price required for risk validation, got {price}.",
            )

        if order.quantity <= 0:
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason=f"Order quantity must be strictly positive, got {order.quantity}.",
            )

        if order.quantity < self.config.min_order_quantity:
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason=(
                    f"Order quantity {order.quantity} is below minimum allowed quantity of "
                    f"{self.config.min_order_quantity}."
                ),
            )

        if (
            self.config.max_order_quantity is not None
            and order.quantity > self.config.max_order_quantity
        ):
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason=(
                    f"Order quantity {order.quantity} exceeds maximum allowed single order quantity ceiling of "
                    f"{self.config.max_order_quantity}."
                ),
            )

        # ------------------------------------------------------------------
        # 2. SELL Order Specific Controls
        # ------------------------------------------------------------------
        if order.side == OrderSide.SELL:
            pos = portfolio.get_position(clean_symbol)
            if pos is None or pos.quantity == 0:
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=price,
                    rejection_reason=f"Cannot execute SELL order: No open position exists for {clean_symbol}.",
                )

            if order.quantity > pos.quantity:
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=price,
                    rejection_reason=(
                        f"Requested sell quantity ({order.quantity}) exceeds open position quantity ({pos.quantity}) "
                        f"for {clean_symbol}."
                    ),
                )

            # Selling decreases portfolio risk and liquidates position -> APPROVED
            est_fill_price = self.estimate_execution_price(price, OrderSide.SELL)
            nominal = round(order.quantity * est_fill_price, 4)
            est_tx_cost = self.estimate_transaction_cost(nominal)
            est_inflow = round(nominal - est_tx_cost, 4)

            return RiskCheckResult(
                approved=True,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=est_fill_price,
                risk_metrics={
                    "estimated_fill_price": est_fill_price,
                    "estimated_nominal": nominal,
                    "estimated_transaction_cost": est_tx_cost,
                    "estimated_cash_inflow": est_inflow,
                    "remaining_quantity_after_sell": float(pos.quantity - order.quantity),
                },
            )

        # ------------------------------------------------------------------
        # 3. BUY Order Controls: Portfolio State & Daily Loss Limit
        # ------------------------------------------------------------------
        portfolio_state = portfolio.get_state()
        current_equity = portfolio_state.total_portfolio_value

        if current_equity <= 0.0:
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason=f"Cannot execute BUY order: Portfolio equity is non-positive (₹{current_equity:.2f}).",
            )

        # Maximum daily loss check
        daily_starting = portfolio_state.daily_starting_equity
        if daily_starting <= 0.0:
            daily_starting = portfolio.initial_capital

        daily_loss = daily_starting - current_equity
        max_allowed_loss = daily_starting * self.config.max_daily_loss

        if round(daily_loss, 4) > round(max_allowed_loss, 4):
            daily_loss_pct = (daily_loss / daily_starting) * 100.0
            max_loss_pct = self.config.max_daily_loss * 100.0
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason=(
                    f"Maximum daily loss limit breached: current daily loss is ₹{daily_loss:.2f} ({daily_loss_pct:.2f}%), "
                    f"exceeding allowed limit of {max_loss_pct:.2f}% (₹{max_allowed_loss:.2f}). "
                    f"New BUY orders are halted for this session."
                ),
                risk_metrics={
                    "daily_starting_equity": daily_starting,
                    "current_equity": current_equity,
                    "daily_loss": daily_loss,
                    "max_allowed_loss": max_allowed_loss,
                },
            )

        # ------------------------------------------------------------------
        # 4. Stop-Loss & Take-Profit Validity
        # ------------------------------------------------------------------
        if order.stop_loss is not None:
            if order.stop_loss <= 0.0:
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=price,
                    rejection_reason=f"Stop loss must be strictly positive, got {order.stop_loss}.",
                )
            if order.stop_loss >= price:
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=price,
                    rejection_reason=(
                        f"Stop loss ({order.stop_loss}) must be strictly below entry price ({price}) for BUY order."
                    ),
                )
        elif self.config.require_stop_loss:
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason="Stop loss is mandatory for BUY orders under current risk configuration.",
            )

        if order.take_profit is not None:
            if order.take_profit <= 0.0:
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=price,
                    rejection_reason=f"Take profit must be strictly positive, got {order.take_profit}.",
                )
            if order.take_profit <= price:
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=price,
                    rejection_reason=(
                        f"Take profit ({order.take_profit}) must be strictly above entry price ({price}) for BUY order."
                    ),
                )

        if (
            order.stop_loss is not None
            and order.take_profit is not None
            and order.stop_loss >= order.take_profit
        ):
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=price,
                rejection_reason=(
                    f"Stop loss ({order.stop_loss}) must be strictly below take profit ({order.take_profit})."
                ),
            )

        # ------------------------------------------------------------------
        # 5. Estimated Fill Price & Available Cash Sufficiency
        # ------------------------------------------------------------------
        est_fill_price = self.estimate_execution_price(price, OrderSide.BUY)
        nominal = round(order.quantity * est_fill_price, 4)
        est_tx_cost = self.estimate_transaction_cost(nominal)
        cash_required = round(nominal + est_tx_cost, 4)

        if cash_required > round(portfolio.cash, 4):
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=est_fill_price,
                rejection_reason=(
                    f"Insufficient available cash: order requires ₹{cash_required:.2f} (nominal ₹{nominal:.2f} + "
                    f"fees ₹{est_tx_cost:.2f}), but available cash is ₹{portfolio.cash:.2f}."
                ),
                risk_metrics={
                    "cash_required": cash_required,
                    "available_cash": portfolio.cash,
                    "estimated_fill_price": est_fill_price,
                },
            )

        # ------------------------------------------------------------------
        # 6. Maximum Risk Per Trade
        # ------------------------------------------------------------------
        trade_risk = 0.0
        max_allowed_risk = round(current_equity * self.config.max_risk_per_trade, 4)

        if order.stop_loss is not None:
            per_share_risk = est_fill_price - order.stop_loss
            trade_risk = round(order.quantity * per_share_risk, 4)

            if trade_risk > max_allowed_risk:
                trade_risk_pct = (trade_risk / current_equity) * 100.0
                max_risk_pct = self.config.max_risk_per_trade * 100.0
                return RiskCheckResult(
                    approved=False,
                    order_id=order.order_id,
                    symbol=clean_symbol,
                    side=order.side,
                    quantity=order.quantity,
                    estimated_price=est_fill_price,
                    rejection_reason=(
                        f"Trade risk of ₹{trade_risk:.2f} ({trade_risk_pct:.2f}%) exceeds maximum allowed risk "
                        f"per trade of {max_risk_pct:.2f}% (₹{max_allowed_risk:.2f})."
                    ),
                    risk_metrics={
                        "trade_risk": trade_risk,
                        "max_allowed_risk": max_allowed_risk,
                        "trade_risk_pct": trade_risk_pct,
                    },
                )

        # ------------------------------------------------------------------
        # 7. Maximum Position Exposure (Aggregating Existing Position)
        # ------------------------------------------------------------------
        existing_pos = portfolio.get_position(clean_symbol)
        existing_qty = existing_pos.quantity if existing_pos is not None else 0
        new_total_qty = existing_qty + order.quantity
        new_position_value = round(new_total_qty * est_fill_price, 4)
        max_allowed_pos_val = round(current_equity * self.config.max_position_exposure, 4)

        if new_position_value > max_allowed_pos_val:
            new_pos_pct = (new_position_value / current_equity) * 100.0
            max_pos_pct = self.config.max_position_exposure * 100.0
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=est_fill_price,
                rejection_reason=(
                    f"Position exposure for {clean_symbol} would be ₹{new_position_value:.2f} ({new_pos_pct:.2f}%), "
                    f"exceeding maximum allowed position exposure of {max_pos_pct:.2f}% (₹{max_allowed_pos_val:.2f})."
                ),
                risk_metrics={
                    "existing_quantity": float(existing_qty),
                    "new_total_quantity": float(new_total_qty),
                    "new_position_value": new_position_value,
                    "max_allowed_position_value": max_allowed_pos_val,
                },
            )

        # ------------------------------------------------------------------
        # 8. Maximum Portfolio Exposure
        # ------------------------------------------------------------------
        other_positions_val = sum(
            p.market_value for s, p in portfolio.positions.items() if s != clean_symbol
        )
        new_total_market_val = round(other_positions_val + new_position_value, 4)
        max_allowed_port_val = round(current_equity * self.config.max_portfolio_exposure, 4)

        if new_total_market_val > max_allowed_port_val:
            port_exp_pct = (new_total_market_val / current_equity) * 100.0
            max_port_pct = self.config.max_portfolio_exposure * 100.0
            return RiskCheckResult(
                approved=False,
                order_id=order.order_id,
                symbol=clean_symbol,
                side=order.side,
                quantity=order.quantity,
                estimated_price=est_fill_price,
                rejection_reason=(
                    f"Total portfolio exposure would be ₹{new_total_market_val:.2f} ({port_exp_pct:.2f}%), "
                    f"exceeding maximum allowed portfolio exposure of {max_port_pct:.2f}% (₹{max_allowed_port_val:.2f})."
                ),
                risk_metrics={
                    "new_total_market_value": new_total_market_val,
                    "max_allowed_portfolio_value": max_allowed_port_val,
                },
            )

        # ------------------------------------------------------------------
        # 9. All Controls Passed -> Approved
        # ------------------------------------------------------------------
        risk_metrics: Dict[str, float] = {
            "current_equity": current_equity,
            "available_cash": portfolio.cash,
            "estimated_fill_price": est_fill_price,
            "estimated_nominal": nominal,
            "estimated_transaction_cost": est_tx_cost,
            "cash_required": cash_required,
            "new_position_value": new_position_value,
            "max_allowed_position_value": max_allowed_pos_val,
            "position_exposure_pct": (new_position_value / current_equity) * 100.0,
            "new_portfolio_exposure_pct": (new_total_market_val / current_equity) * 100.0,
        }
        if order.stop_loss is not None:
            risk_metrics["trade_risk"] = trade_risk
            risk_metrics["max_allowed_risk"] = max_allowed_risk
            risk_metrics["trade_risk_pct"] = (trade_risk / current_equity) * 100.0

        return RiskCheckResult(
            approved=True,
            order_id=order.order_id,
            symbol=clean_symbol,
            side=order.side,
            quantity=order.quantity,
            estimated_price=est_fill_price,
            risk_metrics=risk_metrics,
        )

    def calculate_position_size(
        self,
        symbol: str,
        price: float,
        stop_loss: Optional[float] = None,
        portfolio: Optional[PortfolioTracker] = None,
        capital: Optional[float] = None,
    ) -> int:
        """Deterministically calculate maximum safe position size respecting all risk limits.

        Args:
            symbol: Trading symbol.
            price: Current reference market price (> 0.0).
            stop_loss: Optional planned stop-loss price trigger.
            portfolio: Active PortfolioTracker (preferred).
            capital: Optional total capital (used if portfolio is not provided).

        Returns:
            Maximum integer quantity of shares/units allowed.
        """
        if price <= 0.0:
            raise ValueError(f"price must be > 0.0, got {price}")

        clean_symbol = symbol.strip().upper()
        if portfolio is not None:
            state = portfolio.get_state()
            equity = state.total_portfolio_value
            available_cash = portfolio.cash
            existing_pos = portfolio.get_position(clean_symbol)
            existing_qty = existing_pos.quantity if existing_pos is not None else 0
        else:
            equity = float(capital) if capital is not None else 100000.0
            available_cash = equity
            existing_qty = 0

        if equity <= 0.0 or available_cash <= 0.0:
            return 0

        est_price = self.estimate_execution_price(price, OrderSide.BUY)

        # 1. Limit by Maximum Position Exposure (25%)
        max_pos_val = equity * self.config.max_position_exposure
        max_qty_by_exposure = int(max_pos_val // est_price) - existing_qty
        max_qty_by_exposure = max(0, max_qty_by_exposure)

        # 2. Limit by Maximum Risk Per Trade (2%) if stop-loss provided
        if stop_loss is not None and 0.0 < stop_loss < est_price:
            per_share_risk = est_price - stop_loss
            max_risk_val = equity * self.config.max_risk_per_trade
            max_qty_by_risk = int(max_risk_val // per_share_risk)
            safe_qty = min(max_qty_by_exposure, max_qty_by_risk)
        else:
            safe_qty = max_qty_by_exposure

        # 3. Limit by Available Cash (including estimated transaction fee and fixed fee)
        fee_rate = self.execution_config.brokerage_rate
        fixed_fee = self.execution_config.fixed_fee_per_order
        effective_cash = available_cash - fixed_fee
        if effective_cash <= 0.0:
            return 0
        cash_per_unit = est_price * (1.0 + fee_rate)
        max_qty_by_cash = int(effective_cash // cash_per_unit)
        safe_qty = min(safe_qty, max_qty_by_cash)

        # 4. Limit by Max Single Order Quantity if configured
        if self.config.max_order_quantity is not None:
            safe_qty = min(safe_qty, self.config.max_order_quantity)

        return max(0, safe_qty)
