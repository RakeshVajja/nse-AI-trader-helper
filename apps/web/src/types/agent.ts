/**
 * Phase 9A Agent Mandate & Configuration Types.
 * Strictly aligned with backend frozen contracts in app.trading.agent.mandate.schemas.
 */

export type StrategyStyle =
  | "momentum"
  | "trend_following"
  | "mean_reversion"
  | "breakout"
  | "scalping"
  | "hybrid"
  | "custom";

export const SUPPORTED_EQUITIES = [
  "RELIANCE",
  "TCS",
  "INFY",
  "HDFCBANK",
  "ICICIBANK",
  "SBIN",
  "ITC",
] as const;

export const SUPPORTED_INDICES = [
  "NIFTY 50",
  "BANK NIFTY",
  "NIFTY IT",
] as const;

export const SUPPORTED_INSTRUMENTS = [
  ...SUPPORTED_EQUITIES,
  ...SUPPORTED_INDICES,
] as const;

export type SupportedInstrument = (typeof SUPPORTED_INSTRUMENTS)[number];

export const SUPPORTED_TIMEFRAMES = [
  "5m",
  "15m",
  "30m",
  "1h",
  "1d",
] as const;

export type SupportedTimeframe = (typeof SUPPORTED_TIMEFRAMES)[number];

export const SUPPORTED_INDICATORS = [
  "EMA9",
  "EMA20",
  "SMA50",
  "RSI14",
  "MACD",
  "ATR14",
] as const;

export type SupportedIndicator = (typeof SUPPORTED_INDICATORS)[number];

export interface AgentMandateCreateRequest {
  agent_name: string;
  strategy_prompt: string;
  instrument: string;
  timeframe: string;
  initial_capital: number;
  max_risk_per_trade: number;
  max_position_exposure: number;
  max_daily_loss: number;
}

export interface AgentMandate {
  strategy_style: string;
  objectives: string[];
  preferred_indicators: string[];
  instrument: string;
  timeframe: string;
  risk_per_trade: number;
  max_position_exposure: number;
  max_daily_loss: number;
  rationale?: string | null;
}

export interface AgentMandateResponse {
  success: boolean;
  mandate?: AgentMandate | null;
  agent_id?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  error?: string | null;
}

export const SUPPORTED_STRATEGY_STYLES: readonly StrategyStyle[] = [
  "momentum",
  "trend_following",
  "mean_reversion",
  "breakout",
  "scalping",
  "hybrid",
  "custom",
] as const;

export interface ConfirmedAgentMandate {
  agent_name: string;
  initial_capital: number;
  mandate: AgentMandate;
}

export interface AgentConfirmResponse {
  agent_id: string;
  status: string;
  message?: string;
}

