"""Authoritative deterministic portfolio tracker and position accounting engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.trading.schemas import (
    OrderSide,
    PortfolioState,
    PositionState,
    TradeRecord,
)


class PortfolioTracker:
    """Deterministic in-memory portfolio accounting and position tracking engine.

    Maintains:
    - Exact cash balances with strict conservation of funds.
    - Position average entry prices (weighted cost basis).
    - Mark-to-market valuations and unrealized P&L.
    - Closed trade records and realized gross / net P&L.
    - Cumulative transaction costs and slippage tracking.
    - Portfolio exposure percentages and win rate metrics.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        if initial_capital <= 0.0:
            raise ValueError(f"initial_capital must be positive, got {initial_capital}")

        self.initial_capital: float = float(initial_capital)
        self.cash: float = float(initial_capital)
        self.positions: Dict[str, PositionState] = {}
        self.closed_trades: List[TradeRecord] = []

        self.realized_gross_pnl: float = 0.0
        self.realized_net_pnl: float = 0.0
        self.total_transaction_costs: float = 0.0
        self.total_slippage_cost: float = 0.0

        self.daily_starting_equity: float = float(initial_capital)
        self.daily_realized_pnl: float = 0.0
        self.last_updated: datetime = datetime.now(timezone.utc)

    def open_or_increase_position(
        self,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: Optional[datetime] = None,
        transaction_cost: float = 0.0,
        slippage_cost: float = 0.0,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> PositionState:
        """Open a new long position or add to an existing position.

        Args:
            symbol: Trading symbol (e.g. RELIANCE).
            quantity: Number of shares to buy (integer > 0).
            price: Executed fill price per share (> 0).
            timestamp: Execution timestamp (UTC).
            transaction_cost: Brokerage / commissions incurred.
            slippage_cost: Estimated slippage incurred.
            stop_loss: Optional protective stop-loss price trigger.
            take_profit: Optional take-profit price trigger.

        Returns:
            Updated PositionState.
        """
        clean_symbol = symbol.strip().upper()
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")
        if price <= 0.0:
            raise ValueError(f"price must be > 0.0, got {price}")
        if transaction_cost < 0.0:
            raise ValueError(f"transaction_cost cannot be negative, got {transaction_cost}")
        if slippage_cost < 0.0:
            raise ValueError(f"slippage_cost cannot be negative, got {slippage_cost}")

        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Actual fill price already incorporates directional slippage.
        # slippage_cost is tracked as a cumulative metric, not double-deducted from cash.
        total_cost = (quantity * price) + transaction_cost
        self.cash -= total_cost
        self.total_transaction_costs += transaction_cost
        self.total_slippage_cost += slippage_cost
        self.last_updated = ts

        if clean_symbol not in self.positions:
            # Brand new position
            market_value = quantity * price
            new_pos = PositionState(
                symbol=clean_symbol,
                quantity=quantity,
                average_entry_price=round(price, 4),
                current_price=round(price, 4),
                market_value=round(market_value, 4),
                unrealized_gross_pnl=0.0,
                unrealized_pnl_pct=0.0,
                stop_loss=stop_loss,
                take_profit=take_profit,
                is_open=True,
                entry_time=ts,
                last_updated=ts,
            )
            self.positions[clean_symbol] = new_pos
            return new_pos

        # Add to existing position -> calculate weighted average entry price
        existing = self.positions[clean_symbol]
        old_qty = existing.quantity
        old_avg = existing.average_entry_price
        new_total_qty = old_qty + quantity

        weighted_avg = ((old_qty * old_avg) + (quantity * price)) / new_total_qty
        market_value = new_total_qty * price
        unrealized_gross = (price - weighted_avg) * new_total_qty
        unrealized_pct = (
            ((price - weighted_avg) / weighted_avg) * 100.0 if weighted_avg > 0 else 0.0
        )

        updated_pos = PositionState(
            symbol=clean_symbol,
            quantity=new_total_qty,
            average_entry_price=round(weighted_avg, 4),
            current_price=round(price, 4),
            market_value=round(market_value, 4),
            unrealized_gross_pnl=round(unrealized_gross, 4),
            unrealized_pnl_pct=round(unrealized_pct, 4),
            stop_loss=stop_loss if stop_loss is not None else existing.stop_loss,
            take_profit=take_profit if take_profit is not None else existing.take_profit,
            is_open=True,
            entry_time=existing.entry_time,
            last_updated=ts,
        )
        self.positions[clean_symbol] = updated_pos
        return updated_pos

    def close_or_reduce_position(
        self,
        symbol: str,
        quantity: int,
        price: float,
        timestamp: Optional[datetime] = None,
        transaction_cost: float = 0.0,
        slippage_cost: float = 0.0,
        reason: str = "MANUAL_EXIT",
    ) -> TradeRecord:
        """Close or partially reduce an active long position.

        Args:
            symbol: Trading symbol.
            quantity: Number of shares to close (integer > 0, <= open quantity).
            price: Executed exit fill price per share (> 0).
            timestamp: Execution timestamp (UTC).
            transaction_cost: Brokerage / commissions incurred on exit.
            slippage_cost: Estimated slippage incurred on exit.
            reason: Reason string (e.g. MANUAL_EXIT, STOP_LOSS, TAKE_PROFIT).

        Returns:
            TradeRecord detailing the realized trade.
        """
        clean_symbol = symbol.strip().upper()
        if clean_symbol not in self.positions:
            raise ValueError(f"Cannot close position for {clean_symbol}: No open position exists")

        pos = self.positions[clean_symbol]
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")
        if quantity > pos.quantity:
            raise ValueError(
                f"Cannot close {quantity} units of {clean_symbol}: only {pos.quantity} units open"
            )
        if price <= 0.0:
            raise ValueError(f"price must be > 0.0, got {price}")
        if transaction_cost < 0.0:
            raise ValueError(f"transaction_cost cannot be negative, got {transaction_cost}")
        if slippage_cost < 0.0:
            raise ValueError(f"slippage_cost cannot be negative, got {slippage_cost}")

        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Calculate PnL on closed portion
        # entry_price and exit price are actual fill prices that already incorporate directional slippage.
        # slippage_cost is tracked as a metric and recorded in TradeRecord, but not double-deducted.
        entry_price = pos.average_entry_price
        gross_pnl = quantity * (price - entry_price)
        net_pnl = gross_pnl - transaction_cost

        cash_inflow = (quantity * price) - transaction_cost
        self.cash += cash_inflow

        self.realized_gross_pnl += gross_pnl
        self.realized_net_pnl += net_pnl
        self.daily_realized_pnl += net_pnl
        self.total_transaction_costs += transaction_cost
        self.total_slippage_cost += slippage_cost
        self.last_updated = ts

        trade_record = TradeRecord(
            trade_id=str(uuid.uuid4()),
            symbol=clean_symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            entry_price=round(entry_price, 4),
            exit_price=round(price, 4),
            gross_pnl=round(gross_pnl, 4),
            net_pnl=round(net_pnl, 4),
            transaction_costs=round(transaction_cost, 4),
            slippage_cost=round(slippage_cost, 4),
            entry_time=pos.entry_time,
            exit_time=ts,
            exit_reason=reason,
        )
        self.closed_trades.append(trade_record)

        remaining_qty = pos.quantity - quantity
        if remaining_qty == 0:
            del self.positions[clean_symbol]
        else:
            market_value = remaining_qty * price
            unrealized_gross = remaining_qty * (price - entry_price)
            unrealized_pct = (
                ((price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
            )
            self.positions[clean_symbol] = PositionState(
                symbol=clean_symbol,
                quantity=remaining_qty,
                average_entry_price=round(entry_price, 4),
                current_price=round(price, 4),
                market_value=round(market_value, 4),
                unrealized_gross_pnl=round(unrealized_gross, 4),
                unrealized_pnl_pct=round(unrealized_pct, 4),
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                is_open=True,
                entry_time=pos.entry_time,
                last_updated=ts,
            )

        return trade_record

    def update_market_price(
        self,
        symbol: str,
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[PositionState]:
        """Update mark-to-market valuation for an open position.

        Args:
            symbol: Trading symbol.
            current_price: Latest market price (> 0).
            timestamp: Price update timestamp (UTC).

        Returns:
            Updated PositionState if open, or None if no position exists.
        """
        clean_symbol = symbol.strip().upper()
        if clean_symbol not in self.positions:
            return None

        if current_price <= 0.0:
            raise ValueError(f"current_price must be > 0.0, got {current_price}")

        ts = timestamp or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        pos = self.positions[clean_symbol]
        entry = pos.average_entry_price
        qty = pos.quantity
        market_val = qty * current_price
        unrealized_gross = qty * (current_price - entry)
        unrealized_pct = ((current_price - entry) / entry) * 100.0 if entry > 0 else 0.0

        updated_pos = PositionState(
            symbol=clean_symbol,
            quantity=qty,
            average_entry_price=round(entry, 4),
            current_price=round(current_price, 4),
            market_value=round(market_val, 4),
            unrealized_gross_pnl=round(unrealized_gross, 4),
            unrealized_pnl_pct=round(unrealized_pct, 4),
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            is_open=True,
            entry_time=pos.entry_time,
            last_updated=ts,
        )
        self.positions[clean_symbol] = updated_pos
        self.last_updated = ts
        return updated_pos

    def update_all_market_prices(
        self,
        prices: Dict[str, float],
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Update mark-to-market prices for all matching open positions."""
        for sym, price in prices.items():
            if sym.strip().upper() in self.positions:
                self.update_market_price(sym, price, timestamp=timestamp)

    def reset_daily_stats(self, current_equity: Optional[float] = None) -> None:
        """Reset daily starting baseline and daily realized PnL for a new session day."""
        state = self.get_state()
        self.daily_starting_equity = (
            float(current_equity) if current_equity is not None else state.total_portfolio_value
        )
        self.daily_realized_pnl = 0.0

    def get_position(self, symbol: str) -> Optional[PositionState]:
        """Look up active position state by symbol."""
        return self.positions.get(symbol.strip().upper())

    def get_state(self) -> PortfolioState:
        """Compute and return an authoritative, immutable PortfolioState snapshot."""
        total_market_val = sum(p.market_value for p in self.positions.values())
        unrealized_gross = sum(p.unrealized_gross_pnl for p in self.positions.values())
        total_port_val = self.cash + total_market_val

        total_gross_pnl = self.realized_gross_pnl + unrealized_gross
        # total_gross_pnl already reflects fill prices with economic slippage.
        # Deduct total transaction costs to compute net PnL without double-deducting slippage.
        total_net_pnl = total_gross_pnl - self.total_transaction_costs

        total_return_pct = (
            (total_net_pnl / self.initial_capital) * 100.0 if self.initial_capital > 0 else 0.0
        )

        exposure_pct = (total_market_val / total_port_val) * 100.0 if total_port_val > 0 else 0.0
        # Bound exposure between 0.0 and 100.0 for safety
        exposure_pct = max(0.0, min(100.0, exposure_pct))

        closed_count = len(self.closed_trades)
        winning_trades = sum(1 for t in self.closed_trades if t.net_pnl > 0.0)
        win_rate = (winning_trades / closed_count) * 100.0 if closed_count > 0 else 0.0

        return PortfolioState(
            initial_capital=round(self.initial_capital, 4),
            cash=round(self.cash, 4),
            total_market_value=round(total_market_val, 4),
            total_portfolio_value=round(total_port_val, 4),
            realized_gross_pnl=round(self.realized_gross_pnl, 4),
            realized_net_pnl=round(self.realized_net_pnl, 4),
            unrealized_gross_pnl=round(unrealized_gross, 4),
            total_transaction_costs=round(self.total_transaction_costs, 4),
            total_slippage_cost=round(self.total_slippage_cost, 4),
            gross_pnl=round(total_gross_pnl, 4),
            net_pnl=round(total_net_pnl, 4),
            total_return_pct=round(total_return_pct, 4),
            exposure_pct=round(exposure_pct, 4),
            open_positions_count=len(self.positions),
            closed_trades_count=closed_count,
            win_rate_pct=round(win_rate, 4),
            daily_starting_equity=round(self.daily_starting_equity, 4),
            daily_realized_pnl=round(self.daily_realized_pnl, 4),
            positions=dict(self.positions),
            closed_trades=list(self.closed_trades),
            last_updated=self.last_updated,
        )

    def reset(self) -> None:
        """Reset the portfolio tracker back to initial clean state."""
        self.cash = self.initial_capital
        self.positions.clear()
        self.closed_trades.clear()
        self.realized_gross_pnl = 0.0
        self.realized_net_pnl = 0.0
        self.total_transaction_costs = 0.0
        self.total_slippage_cost = 0.0
        self.daily_starting_equity = self.initial_capital
        self.daily_realized_pnl = 0.0
        self.last_updated = datetime.now(timezone.utc)
