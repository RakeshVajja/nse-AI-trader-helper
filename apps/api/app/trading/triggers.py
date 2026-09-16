"""Deterministic Stop-Loss & Take-Profit Auto-Triggers (Phase 5D).

Enforces automatic position protection per Project Specification Sections 34-35:
1. Completed-candle SL/TP trigger detection via intrabar extremes (Low <= SL, High >= TP).
2. STOP_LOSS takes strict precedence on dual-touch candles (conservative deterministic rule).
3. Deterministic per-timestamp sequencing:
   - Step 1: Execute pending orders scheduled for current candle OPEN.
   - Step 2: Update authoritative portfolio state from those executions.
   - Step 3: Evaluate completed candle SL/TP trigger conditions against remaining active positions.
   - Step 4: Queue newly generated automatic exit orders for next available candle OPEN.
4. Pending automatic-exit deduplication: a position with an in-flight exit cannot emit duplicate exits.
5. Closed-position terminal behavior: once closed, no further triggers can be generated.
6. Trigger candle ($t$) and execution/fill candle ($t+1$) remain strictly separate.
7. decision_price on an automatic exit order is metadata only; fill price is determined at next candle OPEN with directional slippage.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

from app.market_data.schema import CandleData
from app.trading.execution import ExecutionEngine
from app.trading.portfolio import PortfolioTracker
from app.trading.schemas import (
    ExecutionResult,
    OrderRequest,
    OrderSide,
    OrderType,
    PositionState,
)

logger = logging.getLogger(__name__)

EXIT_REASON_STOP_LOSS = "STOP_LOSS"
EXIT_REASON_TAKE_PROFIT = "TAKE_PROFIT"


def check_position_trigger(
    candle: CandleData,
    position: PositionState,
) -> Optional[str]:
    """Evaluate completed candle OHLC extremes against a position's SL and TP levels.

    Rules (per Project Specification Sections 34-35):
    1. Long position: candle.low <= position.stop_loss triggers STOP_LOSS.
    2. Long position: candle.high >= position.take_profit triggers TAKE_PROFIT.
    3. Dual-touch: if both SL and TP are touched in the same completed candle,
       STOP_LOSS takes strict precedence (conservative deterministic rule).
    4. If position is closed (quantity <= 0 or not open), returns None.

    Args:
        candle: Completed CandleData.
        position: Active PositionState.

    Returns:
        "STOP_LOSS", "TAKE_PROFIT", or None.
    """
    if not position.is_open or position.quantity <= 0:
        return None

    low = float(candle.low)
    high = float(candle.high)

    if low <= 0.0 or high <= 0.0:
        raise ValueError(f"Candle high ({high}) and low ({low}) must be strictly positive.")
    if high < low:
        raise ValueError(f"Candle high ({high}) cannot be less than low ({low}).")

    sl_hit = position.stop_loss is not None and low <= position.stop_loss
    tp_hit = position.take_profit is not None and high >= position.take_profit

    if sl_hit and tp_hit:
        # Dual-touch: STOP_LOSS takes strict precedence
        return EXIT_REASON_STOP_LOSS

    if sl_hit:
        return EXIT_REASON_STOP_LOSS

    if tp_hit:
        return EXIT_REASON_TAKE_PROFIT

    return None


def create_exit_order(
    position: PositionState,
    candle: CandleData,
    reason: str,
) -> OrderRequest:
    """Create an automatic simulated market exit OrderRequest.

    Rules:
    - Side is strictly SELL.
    - Quantity is full active position quantity (liquidates position).
    - decision_time is candle.timestamp (trigger candle timestamp).
    - decision_price is the trigger threshold (metadata only, NOT the fill price).
    - reason is exactly "STOP_LOSS" or "TAKE_PROFIT".

    Args:
        position: PositionState to liquidate.
        candle: The trigger candle.
        reason: "STOP_LOSS" or "TAKE_PROFIT".

    Returns:
        Constructed OrderRequest.
    """
    clean_symbol = position.symbol.strip().upper()
    decision_price = position.stop_loss if reason == EXIT_REASON_STOP_LOSS else position.take_profit
    return OrderRequest(
        symbol=clean_symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=position.quantity,
        decision_time=candle.timestamp,
        decision_price=decision_price,
        reason=reason,
    )


class TriggerMonitor:
    r"""Deterministic monitor and orchestrator for automated Stop-Loss and Take-Profit exits.

    Enforces deterministic per-timestamp sequencing:
    1. Execute pending orders scheduled for the current candle OPEN ($P_{t, open}$).
    2. Update portfolio/position state from those executions.
    3. Process the newly completed candle's SL/TP trigger conditions ($Low \le SL$, $High \ge TP$).
    4. Queue newly generated automatic exit orders for the next available candle OPEN ($t+1$).

    Enforces deduplication invariants:
    - A position with a pending automatic exit MUST NOT generate duplicate exits.
    - Once closed, terminal state is reached: no further triggers can be emitted for that position.
    """

    def __init__(self, execution_engine: Optional[ExecutionEngine] = None) -> None:
        self.execution_engine = (
            execution_engine if execution_engine is not None else ExecutionEngine()
        )
        self.pending_exits: Dict[str, OrderRequest] = {}

    def is_exit_pending(self, symbol: str) -> bool:
        """Return True if an automatic exit order is currently queued for symbol."""
        return symbol.strip().upper() in self.pending_exits

    def get_pending_symbols(self) -> Set[str]:
        """Return set of symbols currently having an in-flight pending exit."""
        return set(self.pending_exits.keys())

    def get_pending_order(self, symbol: str) -> Optional[OrderRequest]:
        """Return queued OrderRequest for symbol if present."""
        return self.pending_exits.get(symbol.strip().upper())

    def execute_pending_exits(
        self,
        current_candle: Optional[CandleData],
        portfolio: PortfolioTracker,
        symbol: Optional[str] = None,
    ) -> List[ExecutionResult]:
        """Execute pending automatic exits against current candle OPEN (Step 1 & 2).

        Args:
            current_candle: The candle whose OPEN price executes the orders ($t$).
                           If None (end of series), orders are rejected gracefully.
            portfolio: Authoritative PortfolioTracker.
            symbol: Optional symbol filter. When provided, only pending exits for
                    this symbol are executed; pending exits for other symbols
                    remain queued. If None and portfolio holds a single position,
                    infers the symbol.

        Returns:
            List of ExecutionResult.
        """
        results: List[ExecutionResult] = []
        if not self.pending_exits:
            return results

        target_symbol = (
            symbol.strip().upper() if symbol else getattr(current_candle, "symbol", None)
        )
        if isinstance(target_symbol, str):
            target_symbol = target_symbol.strip().upper()

        if target_symbol is not None:
            if target_symbol not in self.pending_exits:
                return results
            orders_to_execute = [self.pending_exits.pop(target_symbol)]
        else:
            # Fallback when symbol is not provided:
            if len(portfolio.positions) == 1:
                target_symbol = next(iter(portfolio.positions.keys()))
                if target_symbol not in self.pending_exits:
                    return results
                orders_to_execute = [self.pending_exits.pop(target_symbol)]
            else:
                # If symbol is omitted on a multi-position portfolio, process in deterministic sorted order
                queued_symbols = sorted(self.pending_exits.keys())
                orders_to_execute = [self.pending_exits.pop(sym) for sym in queued_symbols]

        for order in orders_to_execute:
            res = self.execution_engine.execute_order(order, current_candle, portfolio)
            results.append(res)

        return results

    def evaluate_completed_candle(
        self,
        completed_candle: CandleData,
        portfolio: PortfolioTracker,
        symbol: Optional[str] = None,
    ) -> List[OrderRequest]:
        """Evaluate SL/TP trigger conditions on completed candle t (Step 3 & 4).

        Args:
            completed_candle: Completed candle t whose OHLC extremes are tested.
            portfolio: Authoritative PortfolioTracker.
            symbol: Optional symbol filter. If None, safely infers symbol for
                    single-position portfolios or from candle.symbol. For
                    multi-position portfolios without an identifiable symbol,
                    raises ValueError to prevent cross-symbol trigger evaluation.

        Returns:
            List of newly generated and queued OrderRequest.
        """
        target_symbol = (
            symbol.strip().upper() if symbol else getattr(completed_candle, "symbol", None)
        )
        if isinstance(target_symbol, str):
            target_symbol = target_symbol.strip().upper()

        if target_symbol is None:
            if len(portfolio.positions) == 1:
                # Safely infer single position's symbol (preserves single-symbol workflows)
                target_symbol = next(iter(portfolio.positions.keys()))
            elif len(portfolio.positions) > 1:
                raise ValueError(
                    "Symbol must be specified when portfolio holds multiple positions "
                    f"({list(portfolio.positions.keys())}) to prevent cross-symbol trigger evaluation."
                )
            else:
                return []

        # Target symbol must be an active position in portfolio
        if target_symbol not in portfolio.positions:
            return []

        pos = portfolio.positions[target_symbol]
        if not pos.is_open or pos.quantity <= 0:
            return []

        # Deduplication: do not generate another exit if one is already pending
        if target_symbol in self.pending_exits:
            return []

        trigger_reason = check_position_trigger(completed_candle, pos)
        if trigger_reason is not None:
            order = create_exit_order(pos, completed_candle, trigger_reason)
            self.pending_exits[target_symbol] = order
            return [order]

        return []

    def process_simulation_cycle(
        self,
        current_candle: CandleData,
        portfolio: PortfolioTracker,
        symbol: Optional[str] = None,
    ) -> Tuple[List[ExecutionResult], List[OrderRequest]]:
        """Run the authoritative 4-step event sequence for simulation timestamp t.

        Sequence:
        1. Execute pending orders scheduled for current candle OPEN (queued from t-1).
        2. Portfolio/position state is updated by execution.
        3. Process newly completed candle t's SL/TP trigger conditions against remaining positions.
        4. Queue newly generated automatic exit orders for next available candle OPEN (t+1).

        Args:
            current_candle: CandleData for current simulation step.
            portfolio: Active PortfolioTracker.
            symbol: Optional symbol filter.

        Returns:
            Tuple of (executions_at_current_open, queued_exits_for_next_open).
        """
        # Resolve target symbol: explicit symbol > candle.symbol > single position
        target_symbol = (
            symbol.strip().upper() if symbol else getattr(current_candle, "symbol", None)
        )
        if isinstance(target_symbol, str):
            target_symbol = target_symbol.strip().upper()
        if target_symbol is None and len(portfolio.positions) == 1:
            target_symbol = next(iter(portfolio.positions.keys()))

        # Step 1 & 2: Execute pending orders at current candle OPEN (filtered by symbol)
        executions = self.execute_pending_exits(
            current_candle=current_candle,
            portfolio=portfolio,
            symbol=target_symbol,
        )

        # Step 3 & 4: Evaluate completed candle triggers and queue new exits
        queued_exits = self.evaluate_completed_candle(
            completed_candle=current_candle,
            portfolio=portfolio,
            symbol=target_symbol,
        )

        return executions, queued_exits

    def reset(self) -> None:
        """Clear all pending exit orders and reset state."""
        self.pending_exits.clear()
