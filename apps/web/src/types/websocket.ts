/**
 * Phase 10A: WebSocket Event Types & Schemas.
 * Strictly aligned with Sections 51 & 52 of PROJECT_SPECIFICATION.md.
 */

export type SimulationEventType =
  | "candle_update"
  | "agent_started"
  | "agent_analyzing"
  | "tool_call"
  | "tool_result"
  | "agent_decision"
  | "risk_check"
  | "order_executed"
  | "position_updated"
  | "portfolio_updated"
  | "simulation_complete"
  | "error"
  | "initial_state";

export const VALID_SIMULATION_EVENT_TYPES: ReadonlySet<string> = new Set([
  "candle_update",
  "agent_started",
  "agent_analyzing",
  "tool_call",
  "tool_result",
  "agent_decision",
  "risk_check",
  "order_executed",
  "position_updated",
  "portfolio_updated",
  "simulation_complete",
  "error",
  "initial_state",
]);

export interface SimulationEvent<T = any> {
  event_type: SimulationEventType;
  simulation_id: string;
  sequence: number;
  virtual_timestamp?: string | null;
  wall_clock_timestamp: string;
  payload: T;
}

export function isValidSimulationEvent(data: unknown): data is SimulationEvent {
  if (!data || typeof data !== "object") {
    return false;
  }
  const obj = data as Record<string, unknown>;

  if (
    typeof obj.event_type !== "string" ||
    !VALID_SIMULATION_EVENT_TYPES.has(obj.event_type)
  ) {
    return false;
  }

  if (typeof obj.simulation_id !== "string" || obj.simulation_id.trim() === "") {
    return false;
  }

  if (
    typeof obj.sequence !== "number" ||
    !Number.isInteger(obj.sequence) ||
    obj.sequence < 1
  ) {
    return false;
  }

  if (
    typeof obj.wall_clock_timestamp !== "string" ||
    obj.wall_clock_timestamp.trim() === ""
  ) {
    return false;
  }

  if (obj.payload === undefined || typeof obj.payload !== "object" || obj.payload === null) {
    return false;
  }

  return true;
}

export interface WsCandle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandleUpdatePayload {
  step_index: number;
  candle: WsCandle;
}

export interface AgentStartedPayload {
  agent_id: string;
  agent_name: string;
  status: string;
  strategy_style?: string | null;
}

export interface AgentAnalyzingPayload {
  agent_id: string;
  candle_timestamp: string;
  step_index: number;
}

export interface ToolCallPayload {
  agent_id: string;
  tool_name: string;
  tool_args: Record<string, any>;
}

export interface ToolResultPayload {
  agent_id: string;
  tool_name: string;
  success: boolean;
  data?: Record<string, any> | null;
  error?: string | null;
}

export interface AgentDecisionPayload {
  agent_id?: string | null;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  quantity?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  reason: string;
  market_regime?: string | null;
}

export interface RiskCheckPayload {
  order_id: string;
  passed: boolean;
  reason: string;
  side?: string | null;
  quantity?: number | null;
  risk_parameters?: Record<string, any> | null;
}

export interface OrderExecutedPayload {
  order_id: string;
  trade_id?: string | null;
  side: "BUY" | "SELL";
  quantity: number;
  execution_price: number;
  market_price?: number | null;
  slippage_cost: number;
  transaction_cost: number;
  status: string;
  rejection_reason?: string | null;
  is_auto_exit: boolean;
}

export interface PositionItemPayload {
  symbol: string;
  quantity: number;
  average_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  stop_loss?: number | null;
  take_profit?: number | null;
  is_open: boolean;
}

export interface PositionUpdatedPayload {
  positions: PositionItemPayload[];
}

export interface PortfolioUpdatedPayload {
  cash: number;
  portfolio_value: number;
  gross_pnl: number;
  net_pnl: number;
  total_return_pct: number;
  exposure_pct: number;
  open_positions_count: number;
}

export interface SimulationCompletePayload {
  status: string;
  total_steps: number;
  final_portfolio_value: number;
  total_return_pct: number;
  metrics: Record<string, any>;
}

export interface ErrorPayload {
  code: string;
  message: string;
}

export interface InitialStatePayload {
  simulation_id: string;
  status: string;
  symbol: string;
  timeframe: string;
  step_index: number;
  total_candles: number;
  progress_pct: number;
  current_time?: string | null;
  portfolio?: PortfolioUpdatedPayload | null;
  positions: PositionItemPayload[];
}

export type WebSocketConnectionState =
  | "CONNECTING"
  | "CONNECTED"
  | "DISCONNECTED"
  | "ERROR";
