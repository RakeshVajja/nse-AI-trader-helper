/**
 * Phase 10B: Quantitative Trading Terminal Chart Types.
 * Trade markers, price line levels, and live candle update interfaces.
 */

export type TradeMarkerType =
  | "BUY_EXECUTION"
  | "SELL_EXECUTION"
  | "SL_EXIT"
  | "TP_EXIT"
  | "SIGNAL_BUY"
  | "SIGNAL_SELL";

export interface ChartTradeMarker {
  /** Optional unique identifier for the marker */
  id?: string;
  /** UTC timestamp in seconds (epoch seconds) */
  time: number;
  /** Semantic type distinguishing execution from signal */
  type: TradeMarkerType;
  /** Execution or signal price level */
  price: number;
  /** Executed quantity (if applicable) */
  quantity?: number;
  /** Custom tooltip or marker label text */
  text?: string;
  /** Detailed reason or rationale (optional) */
  details?: string;
}

export interface PriceLineLevel {
  price: number;
  title: "SL" | "TP";
  color: string;
}

export interface LiveCandleUpdate {
  step_index: number;
  candle: {
    timestamp: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  };
}
