"""Prompt and system instruction generation for Phase 8C Decision Cycle.

Enforces:
- Strict no-lookahead (only data <= t is visible)
- Direct consumption of validated AgentMandate (frozen 8B)
- Clear guidance on Phase 7 tool usage and structured output constraints
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.trading.agent.mandate.schemas import AgentMandate
from app.trading.agent.tools import ToolExecutionContext

if TYPE_CHECKING:
    from app.trading.agent.memory.schemas import AgentMemory


def build_system_instruction(mandate: AgentMandate) -> str:
    """Build authoritative system instruction constraining Gemini to the agent mandate."""
    objectives_str = "\n".join(f"- {obj}" for obj in mandate.objectives)
    indicators_str = ", ".join(mandate.preferred_indicators)

    return (
        "You are an autonomous intraday trading agent executing a disciplined algorithmic strategy.\n"
        "Your decisions are governed by an authoritative Strategy Mandate that you must strictly obey.\n\n"
        "=== STRATEGY MANDATE ===\n"
        f"Instrument: {mandate.instrument}\n"
        f"Timeframe: {mandate.timeframe}\n"
        f"Strategy Style: {mandate.strategy_style}\n"
        f"Objectives:\n{objectives_str}\n"
        f"Preferred Indicators: {indicators_str}\n"
        f"Max Risk Per Trade: {mandate.risk_per_trade * 100:.2f}%\n"
        f"Max Position Exposure: {mandate.max_position_exposure * 100:.2f}%\n"
        f"Max Daily Loss: {mandate.max_daily_loss * 100:.2f}%\n\n"
        "=== OPERATING RULES & TOOL USAGE ===\n"
        "1. NO LOOKAHEAD: You only observe data up to the current completed candle t. No future data exists.\n"
        "2. TOOLS: You have access to authorized Phase 7 tools (get_market_data, get_indicators, get_market_regime, "
        "get_position, get_portfolio, get_trade_history, calculate_position_size, place_simulated_order, close_simulated_position).\n"
        "3. ORDER STAGING: Any order placed via place_simulated_order or close_simulated_position is staged for execution "
        "at the next candle OPEN (t+1). At most ONE order can be staged per candle bar.\n"
        "4. FINAL DECISION: You must return a final structured AgentDecision adhering to the schema:\n"
        "   - action: 'BUY', 'SELL', or 'HOLD'\n"
        "   - confidence: float between 0.0 and 1.0\n"
        "   - quantity: positive integer if trading (optional for HOLD)\n"
        "   - stop_loss: protective stop price if BUY\n"
        "   - take_profit: profit target price if BUY\n"
        "   - reason: concise non-empty rationale\n"
        "   - observations: key technical/regime observations\n"
        "   - tools_used: list of tools you invoked\n"
        "5. DISCIPLINE: If conditions do not warrant a high-probability entry or exit, choose 'HOLD'. Do not force trades."
    )


def build_cycle_prompt(
    context: ToolExecutionContext,
    mandate: AgentMandate,
    memory: Optional[AgentMemory] = None,
) -> str:
    """Build bounded per-cycle prompt from authoritative simulation state at candle t."""
    candle = context.current_candle
    pos = context.portfolio.get_position(context.symbol)
    port_state = context.portfolio.get_state()

    pos_desc = "FLAT (no active position)"
    if pos is not None and pos.is_open and pos.quantity > 0:
        pos_desc = (
            f"LONG {pos.quantity} shares @ avg entry {pos.average_entry_price:.2f}, "
            f"current price {float(candle.close):.2f}, "
            f"unrealized PnL: {pos.unrealized_gross_pnl:.2f} ({pos.unrealized_pnl_pct * 100:.2f}%)"
        )

    prompt = (
        f"=== NEW COMPLETED CANDLE EVENT (t = {candle.timestamp.isoformat()}) ===\n"
        f"Symbol: {context.symbol}\n"
        f"Timeframe: {context.timeframe}\n"
        f"Candle OHLCV: Open={float(candle.open):.2f}, High={float(candle.high):.2f}, "
        f"Low={float(candle.low):.2f}, Close={float(candle.close):.2f}, Volume={float(candle.volume):.0f}\n\n"
        f"=== CURRENT ACCOUNT STATE AT t ===\n"
        f"Cash: ₹{port_state.cash:,.2f}\n"
        f"Total Portfolio Value: ₹{port_state.total_portfolio_value:,.2f}\n"
        f"Position: {pos_desc}\n"
        f"Closed Trades Count: {len(context.portfolio.closed_trades)}\n\n"
        f"Total visible historical candles up to t: {len(context.visible_candles)}\n\n"
    )

    if memory is not None and not memory.is_empty:
        prompt += memory.format_prompt_block() + "\n"

    prompt += (
        "Inspect market indicators and regimes using your tools if needed, "
        "then produce your structured AgentDecision."
    )
    return prompt
