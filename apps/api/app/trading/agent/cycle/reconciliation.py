"""Deterministic AgentDecision and tool activity reconciliation (Phase 8C).

Enforces:
- Exact G1 reconciliation semantics:
  1. A mutating tool in this cycle may successfully stage an order.
  2. If Gemini subsequently returns an AgentDecision describing that same action,
     8C recognizes it was already staged and does NOT submit a duplicate order.
  3. A rejected tool call does NOT count as successful staging.
  4. If an order was NOT staged by tools, 8C dispatches it ONLY through the frozen Phase 7C harness.
  5. One staged order per candle invariant is preserved.
  6. Zero direct OrderRequest instantiation, zero direct staged_orders mutation, zero RiskEngine bypass.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.trading.agent.cycle.schemas import CycleToolExecution, DecisionReconciliation
from app.trading.agent.harness import SafeToolExecutionHarness
from app.trading.agent.mandate.schemas import AgentMandate
from app.trading.agent.schemas import AgentAction, AgentDecision
from app.trading.agent.tools import ToolExecutionContext

logger = logging.getLogger(__name__)


def reconcile_decision_with_tools(
    decision: AgentDecision,
    tool_executions: List[CycleToolExecution],
    context: ToolExecutionContext,
    mandate: AgentMandate,
    harness: SafeToolExecutionHarness,
) -> DecisionReconciliation:
    """Reconcile the final AgentDecision with tool activity from the active cycle."""
    # 1. Identify if a mutating tool successfully staged an order in this cycle
    tool_staged_order_id: Optional[str] = None
    tool_staged_side: Optional[str] = None
    tool_staged_name: Optional[str] = None

    for tex in tool_executions:
        if tex.success and tex.staged_order_id:
            tool_staged_order_id = tex.staged_order_id
            tool_staged_name = tex.tool_name
            if tex.tool_name == "place_simulated_order":
                tool_staged_side = str(tex.arguments.get("side", "BUY")).upper()
            elif tex.tool_name == "close_simulated_position":
                tool_staged_side = "SELL"
            break

    # ==========================================================================
    # Case 1: BUY Decision
    # ==========================================================================
    if decision.action == AgentAction.BUY:
        if tool_staged_order_id is not None:
            if tool_staged_side == "BUY":
                return DecisionReconciliation(
                    action=AgentAction.BUY,
                    order_staged=True,
                    order_id=tool_staged_order_id,
                    order_source="TOOL",
                    status="ALREADY_STAGED_BY_TOOL",
                    reconciliation_notes="BUY order was already successfully staged by tool during this cycle.",
                )
            else:
                return DecisionReconciliation(
                    action=AgentAction.BUY,
                    order_staged=True,
                    order_id=tool_staged_order_id,
                    order_source="TOOL",
                    status="ALREADY_STAGED_BY_TOOL",
                    reconciliation_notes=(
                        f"Conflicting decision: tool already staged {tool_staged_side} order ({tool_staged_name}); "
                        "single-staged-order-per-candle invariant strictly preserved."
                    ),
                )

        # No order staged by tool; submit BUY through Phase 7C harness
        qty = decision.quantity
        if qty is None or qty <= 0:
            # Fallback: calculate risk-compliant size via harness calculate_position_size
            entry_px = float(context.current_candle.close)
            sl_px = (
                decision.stop_loss if decision.stop_loss is not None else round(entry_px * 0.98, 2)
            )
            size_res = harness.dispatch(
                tool_name="calculate_position_size",
                raw_args={
                    "entry_price": entry_px,
                    "stop_loss_price": sl_px,
                    "risk_per_trade": mandate.risk_per_trade,
                },
                context=context,
            )
            if size_res.success and size_res.data and size_res.data.get("target_quantity", 0) > 0:
                qty = int(size_res.data["target_quantity"])
            else:
                qty = 1

        buy_args = {
            "side": "BUY",
            "quantity": qty,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "reason": decision.reason,
        }
        res = harness.dispatch(
            tool_name="place_simulated_order",
            raw_args=buy_args,
            context=context,
        )

        if res.success and res.data:
            staged_id = res.data.get("order_id")
            return DecisionReconciliation(
                action=AgentAction.BUY,
                order_staged=True,
                order_id=staged_id,
                order_source="DECISION",
                status="STAGED_BY_DECISION",
                reconciliation_notes="BUY order successfully staged via Phase 7C harness from AgentDecision.",
            )
        else:
            return DecisionReconciliation(
                action=AgentAction.BUY,
                order_staged=False,
                order_id=None,
                order_source=None,
                status="REJECTED_BY_TOOL",
                reconciliation_notes=f"BUY order rejected by Phase 7C harness: {res.error}",
            )

    # ==========================================================================
    # Case 2: SELL Decision
    # ==========================================================================
    elif decision.action == AgentAction.SELL:
        if tool_staged_order_id is not None:
            if tool_staged_side == "SELL":
                return DecisionReconciliation(
                    action=AgentAction.SELL,
                    order_staged=True,
                    order_id=tool_staged_order_id,
                    order_source="TOOL",
                    status="ALREADY_STAGED_BY_TOOL",
                    reconciliation_notes="SELL/close order was already successfully staged by tool during this cycle.",
                )
            else:
                return DecisionReconciliation(
                    action=AgentAction.SELL,
                    order_staged=True,
                    order_id=tool_staged_order_id,
                    order_source="TOOL",
                    status="ALREADY_STAGED_BY_TOOL",
                    reconciliation_notes=(
                        f"Conflicting decision: tool already staged {tool_staged_side} order ({tool_staged_name}); "
                        "single-staged-order-per-candle invariant strictly preserved."
                    ),
                )

        # No order staged by tool; check if there is an active position to close
        pos = context.portfolio.get_position(context.symbol)
        if pos is None or not pos.is_open or pos.quantity <= 0:
            return DecisionReconciliation(
                action=AgentAction.SELL,
                order_staged=False,
                order_id=None,
                order_source=None,
                status="NO_ACTION_FLAT",
                reconciliation_notes=f"SELL decision skipped: no active open position to close for {context.symbol}.",
            )

        close_args = {
            "quantity": decision.quantity,
            "reason": decision.reason,
        }
        res = harness.dispatch(
            tool_name="close_simulated_position",
            raw_args=close_args,
            context=context,
        )

        if res.success and res.data:
            staged_id = res.data.get("order_id")
            return DecisionReconciliation(
                action=AgentAction.SELL,
                order_staged=True,
                order_id=staged_id,
                order_source="DECISION",
                status="STAGED_BY_DECISION",
                reconciliation_notes="SELL/close order successfully staged via Phase 7C harness from AgentDecision.",
            )
        else:
            return DecisionReconciliation(
                action=AgentAction.SELL,
                order_staged=False,
                order_id=None,
                order_source=None,
                status="REJECTED_BY_TOOL",
                reconciliation_notes=f"SELL/close order rejected by Phase 7C harness: {res.error}",
            )

    # ==========================================================================
    # Case 3: HOLD Decision
    # ==========================================================================
    else:  # decision.action == AgentAction.HOLD
        if tool_staged_order_id is not None:
            return DecisionReconciliation(
                action=AgentAction.HOLD,
                order_staged=True,
                order_id=tool_staged_order_id,
                order_source="TOOL",
                status="ALREADY_STAGED_BY_TOOL",
                reconciliation_notes="Agent decided HOLD, but an order was previously staged by tool during this cycle.",
            )
        else:
            return DecisionReconciliation(
                action=AgentAction.HOLD,
                order_staged=False,
                order_id=None,
                order_source=None,
                status="NO_ORDER_REQUIRED",
                reconciliation_notes="Agent decided HOLD; no trade order required.",
            )
