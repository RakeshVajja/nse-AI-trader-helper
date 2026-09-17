/**
 * Phase 10D: Types & Schemas for Activity Feed, Trade Log, and Performance Panel.
 * Strictly aligned with Sections 54, 55, and 58 of PROJECT_SPECIFICATION.md.
 */

import {
  SimulationEvent,
  SimulationEventType,
  AgentStartedPayload,
  AgentAnalyzingPayload,
  AgentDecisionPayload,
  RiskCheckPayload,
  OrderExecutedPayload,
  PositionUpdatedPayload,
  PortfolioUpdatedPayload,
  SimulationCompletePayload,
  ErrorPayload,
  InitialStatePayload,
  ToolCallPayload,
  ToolResultPayload,
} from "./websocket";

export type ActivityCategory =
  | "ANALYSIS"
  | "SIGNAL"
  | "RISK"
  | "ORDER"
  | "PORTFOLIO"
  | "SYSTEM";

export type ActivitySeverity = "info" | "success" | "warning" | "error";

export interface ActivityItem {
  id: string;
  sequence: number;
  timestamp: string;
  eventType: SimulationEventType;
  category: ActivityCategory;
  title: string;
  description: string;
  severity: ActivitySeverity;
  details?: Record<string, any>;
}

export interface TradeLogEntry {
  id: string;
  orderId?: string | null;
  tradeId?: string | null;
  timestamp: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  executionPrice: number;
  exitPrice?: number | null;
  netPnl?: number | null;
  grossPnl?: number | null;
  transactionCost: number;
  slippageCost: number;
  status: string;
  isAutoExit: boolean;
  isClosed: boolean;
}

export interface SimulationPerformanceMetrics {
  simulationId: string;
  initialCapital: number;
  finalPortfolioValue: number;
  grossPnl: number;
  netPnl: number;
  totalReturnPct: number;
  transactionCosts: number;
  slippageCost: number;
  totalTrades: number;
  winningTrades: number;
  losingTrades: number;
  winRatePct: number;
  averageWin: number;
  averageLoss: number;
  profitFactor: number;
  maxDrawdownPct: number;
  exposurePct: number;
  openPositionsCount: number;
}

export type BottomTerminalTab = "activity" | "trades" | "performance";

/**
 * Format an ISO timestamp or simulation time string into a concise HH:MM:SS format.
 */
export function formatTimeDisplay(ts?: string | null): string {
  if (!ts) return "--:--:--";
  try {
    if (ts.includes("T")) {
      const timePart = ts.split("T")[1];
      return timePart ? timePart.slice(0, 8) : ts;
    }
    if (ts.includes(" ")) {
      const timePart = ts.split(" ")[1];
      return timePart ? timePart.slice(0, 8) : ts;
    }
    return ts.slice(0, 8);
  } catch {
    return ts;
  }
}


/**
 * Format a numeric amount in INR with commas and optional +/- sign.
 */
export function formatINR(val?: number | null, showSign = false, decimals = 2): string {
  if (val === null || val === undefined || isNaN(val)) return "—";
  const abs = Math.abs(val).toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  if (showSign) {
    if (val > 0) return `+₹${abs}`;
    if (val < 0) return `-₹${abs}`;
  }
  return `₹${abs}`;
}

/**
 * Pure converter function to map an authoritative SimulationEvent into a human-readable ActivityItem.
 * Skips candle_update to avoid flooding the operational activity feed.
 */
export function formatSimulationEventToActivity(
  event: SimulationEvent
): ActivityItem | null {
  const ts = event.virtual_timestamp || event.wall_clock_timestamp;
  const timeStr = formatTimeDisplay(ts);
  const eventId = `act-${event.simulation_id}-${event.sequence}-${event.event_type}`;

  switch (event.event_type) {
    case "agent_started": {
      const p = event.payload as AgentStartedPayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "SYSTEM",
        title: "Agent Started",
        description: `${p.agent_name || "Agent"} initialized with ${p.strategy_style || "quantitative"} mandate`,
        severity: "info",
      };
    }

    case "agent_analyzing": {
      const p = event.payload as AgentAnalyzingPayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "ANALYSIS",
        title: "Market Analysis",
        description: `Evaluating technical indicators for candle #${p.step_index || 0} (${formatTimeDisplay(p.candle_timestamp)})`,
        severity: "info",
      };
    }

    case "tool_call": {
      const p = event.payload as ToolCallPayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "ANALYSIS",
        title: "Tool Invocation",
        description: `Inspecting market state via ${p.tool_name || "tool"}`,
        severity: "info",
      };
    }

    case "tool_result": {
      const p = event.payload as ToolResultPayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "ANALYSIS",
        title: "Indicator Data Retrieved",
        description: `Retrieved quantitative indicators (${p.success ? "success" : "failed"})`,
        severity: p.success ? "info" : "warning",
      };
    }

    case "agent_decision": {
      const p = event.payload as AgentDecisionPayload;
      const confPct = Math.round(p.confidence <= 1.0 ? p.confidence * 100 : p.confidence);
      const isBuy = p.action === "BUY";
      const isSell = p.action === "SELL";
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "SIGNAL",
        title: `Decision: ${p.action}`,
        description: `${p.action} signal emitted with ${confPct}% confidence • ${p.reason || "Quantitative evaluation"}`,
        severity: isBuy ? "success" : isSell ? "warning" : "info",
      };
    }

    case "risk_check": {
      const p = event.payload as RiskCheckPayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "RISK",
        title: `Risk Check: ${p.passed ? "PASSED" : "REJECTED"}`,
        description: p.reason || (p.passed ? "Within risk mandate" : "Violates risk constraints"),
        severity: p.passed ? "success" : "error",
      };
    }

    case "order_executed": {
      const p = event.payload as OrderExecutedPayload;
      const priceStr = formatINR(p.execution_price);
      const sideStr = p.side;
      const exitTag = p.is_auto_exit ? " (SL/TP Triggered)" : "";
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "ORDER",
        title: `Order Executed: ${sideStr}`,
        description: `Filled ${p.quantity} shares @ ${priceStr}${exitTag} • Status: ${p.status}`,
        severity: "success",
      };
    }

    case "position_updated": {
      const p = event.payload as PositionUpdatedPayload;
      const openPos = p.positions?.find((pos) => pos.is_open && pos.quantity > 0);
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "PORTFOLIO",
        title: "Position Updated",
        description: openPos
          ? `Holding ${openPos.symbol}: ${openPos.quantity} shares (P&L: ${formatINR(openPos.unrealized_pnl, true)})`
          : "Position closed. Portfolio is flat.",
        severity: "info",
      };
    }

    case "portfolio_updated": {
      const p = event.payload as PortfolioUpdatedPayload;
      const equityStr = formatINR(p.portfolio_value);
      const netPnlStr = formatINR(p.net_pnl, true);
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "PORTFOLIO",
        title: "Equity Updated",
        description: `Equity: ${equityStr} • Net P&L: ${netPnlStr} (${p.total_return_pct.toFixed(2)}%)`,
        severity: p.net_pnl >= 0 ? "info" : "warning",
      };
    }

    case "simulation_complete": {
      const p = event.payload as SimulationCompletePayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "SYSTEM",
        title: "Simulation Completed",
        description: `Finished ${p.total_steps || 0} candles. Final Equity: ${formatINR(p.final_portfolio_value)} (${p.total_return_pct?.toFixed(2) || "0.00"}%)`,
        severity: "success",
      };
    }

    case "error": {
      const p = event.payload as ErrorPayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "SYSTEM",
        title: `Error: ${p.code || "SIMULATION_ERROR"}`,
        description: p.message || "An unexpected error occurred during playback",
        severity: "error",
      };
    }

    case "initial_state": {
      const p = event.payload as InitialStatePayload;
      return {
        id: eventId,
        sequence: event.sequence,
        timestamp: ts,
        eventType: event.event_type,
        category: "SYSTEM",
        title: "Simulation Session Connected",
        description: `Attached to ${p.symbol || "instrument"} (${p.timeframe || "15m"}) • Status: ${p.status || "READY"}`,
        severity: "info",
      };
    }

    default:
      // candle_update and unknown events are ignored from activity log
      return null;
  }
}

/**
 * Pure converter function to map an authoritative order_executed event into a TradeLogEntry.
 */
export function formatOrderExecutedToTrade(
  event: SimulationEvent,
  symbol = "RELIANCE"
): TradeLogEntry | null {
  if (event.event_type !== "order_executed") return null;
  const p = event.payload as OrderExecutedPayload;
  if (!p || p.status !== "FILLED") return null;

  const ts = event.virtual_timestamp || event.wall_clock_timestamp;
  const tradeId = p.trade_id || p.order_id || `trade-${event.simulation_id}-${event.sequence}`;

  return {
    id: tradeId,
    orderId: p.order_id,
    tradeId: p.trade_id,
    timestamp: ts,
    symbol,
    side: p.side,
    quantity: p.quantity,
    executionPrice: p.execution_price,
    exitPrice: p.is_auto_exit ? p.execution_price : null,
    transactionCost: p.transaction_cost || 0,
    slippageCost: p.slippage_cost || 0,
    status: p.status,
    isAutoExit: p.is_auto_exit || false,
    isClosed: p.is_auto_exit || p.side === "SELL",
  };
}

export interface ApiTradeResponse {
  id: string;
  simulation_id: string;
  order_id?: string | null;
  instrument_id: number;
  symbol: string;
  side: "BUY" | "SELL" | string;
  quantity: number;
  entry_price: number;
  exit_price?: number | null;
  gross_pnl?: number | null;
  net_pnl?: number | null;
  transaction_costs: number;
  slippage_cost: number;
  is_closed: boolean;
  entry_time: string;
  exit_time?: string | null;
}

export interface ApiPerformanceMetricsResponse {
  simulation_id: string;
  initial_capital: number;
  final_portfolio_value: number;
  gross_pnl: number;
  net_pnl: number;
  total_return_pct: number;
  transaction_costs: number;
  slippage_cost: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_pct: number;
  average_win: number;
  average_loss: number;
  profit_factor: number;
  max_drawdown_pct: number;
  exposure_pct: number;
  open_positions_count: number;
}

export function formatApiTradeToLogEntry(trade: ApiTradeResponse): TradeLogEntry {
  return {
    id: trade.id,
    orderId: trade.order_id,
    tradeId: trade.id,
    timestamp: trade.exit_time || trade.entry_time,
    symbol: trade.symbol,
    side: trade.side as "BUY" | "SELL",
    quantity: trade.quantity,
    executionPrice: trade.entry_price,
    exitPrice: trade.exit_price,
    netPnl: trade.net_pnl,
    grossPnl: trade.gross_pnl,
    transactionCost: trade.transaction_costs,
    slippageCost: trade.slippage_cost,
    status: trade.is_closed ? "CLOSED" : "FILLED",
    isAutoExit: false,
    isClosed: trade.is_closed,
  };
}

export function mapApiPerformanceToMetrics(
  res: ApiPerformanceMetricsResponse
): SimulationPerformanceMetrics {
  return {
    simulationId: res.simulation_id,
    initialCapital: res.initial_capital,
    finalPortfolioValue: res.final_portfolio_value,
    grossPnl: res.gross_pnl,
    netPnl: res.net_pnl,
    totalReturnPct: res.total_return_pct,
    transactionCosts: res.transaction_costs,
    slippageCost: res.slippage_cost,
    totalTrades: res.total_trades,
    winningTrades: res.winning_trades,
    losingTrades: res.losing_trades,
    winRatePct: res.win_rate_pct,
    averageWin: res.average_win,
    averageLoss: res.average_loss,
    profitFactor: res.profit_factor,
    maxDrawdownPct: res.max_drawdown_pct,
    exposurePct: res.exposure_pct,
    openPositionsCount: res.open_positions_count,
  };
}

