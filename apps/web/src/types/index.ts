/** Core type definitions for NSE AI Trader frontend. */

export type InstrumentType = "EQUITY" | "INDEX";

export interface Instrument {
  id: number;
  symbol: string;
  name: string;
  exchange: string;
  instrument_type: InstrumentType;
  is_active: boolean;
  created_at?: string;
}

export type InstrumentResponse = Instrument;

export interface InstrumentListResponse {
  instruments: Instrument[];
  total: number;
  count: number;
}

export type Timeframe = "1m" | "3m" | "5m" | "10m" | "15m" | "30m" | "1h" | "1d" | "1w" | "1M";

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface HistoricalDataResponse {
  symbol: string;
  timeframe: string;
  candles: Candle[];
  count: number;
}

export interface LatestCandleResponse {
  symbol: string;
  timeframe: string;
  candle?: Candle | null;
}

/** Phase 4B & 4C Market Regime types */
export type TrendRegime = "BULLISH" | "BEARISH" | "SIDEWAYS";

export type VolatilityRegime = "HIGH" | "NORMAL" | "LOW";

export interface TrendSignalDetails {
  close_vs_sma50?: string | null;
  ema9_vs_ema20?: string | null;
  macd_vs_zero?: string | null;
  rsi14_vs_50?: string | null;
  bullish_votes: number;
  bearish_votes: number;
}

export interface VolatilityMetrics {
  current_atrp14?: number | null;
  p20_threshold?: number | null;
  p80_threshold?: number | null;
  sample_count: number;
}

export interface MarketRegimeSnapshot {
  timestamp: string;
  trend_regime?: TrendRegime | null;
  volatility_regime?: VolatilityRegime | null;
  trend_details?: TrendSignalDetails | null;
  volatility_details?: VolatilityMetrics | null;
}

export interface IndicatorSnapshot {
  timestamp: string;
  close: number;
  volume: number;
  ema9?: number | null;
  ema20?: number | null;
  sma50?: number | null;
  rsi14?: number | null;
  macd?: number | null;
  macd_signal?: number | null;
  macd_histogram?: number | null;
  atr14?: number | null;
  atrp14?: number | null;
  trend_regime?: TrendRegime | null;
  volatility_regime?: VolatilityRegime | null;
  trend_details?: TrendSignalDetails | null;
  volatility_details?: VolatilityMetrics | null;
}

export interface IndicatorSeries {
  symbol: string;
  timeframe: string;
  timestamps: string[];
  closes: number[];
  ema9: (number | null)[];
  ema20: (number | null)[];
  sma50: (number | null)[];
  rsi14: (number | null)[];
  macd_line: (number | null)[];
  macd_signal: (number | null)[];
  macd_histogram: (number | null)[];
  atr14: (number | null)[];
  atrp14: (number | null)[];
  trend_regimes: (TrendRegime | null)[];
  volatility_regimes: (VolatilityRegime | null)[];
  count: number;
}

export interface IndicatorSnapshotResponse {
  symbol: string;
  timeframe: string;
  snapshot?: IndicatorSnapshot | null;
}

export interface MarketRegimeResponse {
  symbol: string;
  timeframe: string;
  regime?: MarketRegimeSnapshot | null;
}

export type AgentAction = "BUY" | "SELL" | "HOLD";

export interface AgentDecision {
  action: AgentAction;
  confidence: number;
  quantity?: number;
  stop_loss?: number;
  take_profit?: number;
  reason: string;
  observations: string[];
  tools_used: string[];
}

export type AgentStatus =
  | "CREATED"
  | "READY"
  | "RUNNING"
  | "ANALYZING"
  | "WAITING"
  | "PAUSED"
  | "ERROR"
  | "COMPLETED";

export interface PortfolioState {
  cash: number;
  portfolioValue: number;
  grossPnl: number;
  netPnl: number;
  realizedPnl: number;
  unrealizedPnl: number;
  totalTrades: number;
  winRate: number;
}

export * from "./agent";
export * from "./websocket";
export * from "./chart";
