/**
 * Phase 10E: Interactive Simulation Controls Types & Specifications.
 * Strictly aligned with Sections 51, 52, and 57 of PROJECT_SPECIFICATION.md.
 */

export type SimulationSpeed = 0.5 | 1.0 | 2.0 | 5.0 | 10.0;

export const VALID_SIMULATION_SPEEDS: readonly SimulationSpeed[] = [
  0.5, 1.0, 2.0, 5.0, 10.0,
] as const;

export type SimulationRunMode = "AGENT" | "BASELINE";

export type SimulationLifecycleStatus =
  | "IDLE"
  | "CREATED"
  | "RUNNING"
  | "PAUSED"
  | "STOPPED"
  | "COMPLETED"
  | "ERROR";

export interface SimulationCreateRequest {
  symbol: string;
  timeframe?: string;
  start_date: string;
  end_date: string;
  initial_capital?: number;
  is_baseline?: boolean;
  speed?: number;
  slippage_pct?: number;
  brokerage_rate?: number;
  fixed_fee_per_order?: number;
  max_risk_per_trade?: number;
  max_position_exposure?: number;
  max_portfolio_exposure?: number;
  max_daily_loss?: number;
}

export interface SimulationResponse {
  id: string;
  instrument_id: number;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_portfolio_value?: number | null;
  total_return_pct?: number | null;
  status: string;
  is_baseline: boolean;
  speed: number;
  current_time?: string | null;
  step_index: number;
  total_candles: number;
  progress_pct: number;
  metrics?: Record<string, any> | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SimulationControlsState {
  simulationId: string | null;
  status: SimulationLifecycleStatus;
  speed: SimulationSpeed;
  runMode: SimulationRunMode;
  stepIndex: number;
  totalCandles: number;
  progressPct: number;
  currentTime: string | null;
  symbol: string;
  timeframe: string;
  isLoadingAction: boolean;
  error: string | null;
}

export interface SimulationControlsBarProps {
  simulationId: string | null;
  status: SimulationLifecycleStatus;
  speed: SimulationSpeed;
  runMode: SimulationRunMode;
  stepIndex: number;
  totalCandles: number;
  progressPct: number;
  currentTime: string | null;
  symbol: string;
  timeframe: string;
  isLoadingAction?: boolean;
  errorMessage?: string | null;
  onStart: () => void | Promise<void>;
  onPause: () => void | Promise<void>;
  onResume: () => void | Promise<void>;
  onStep: () => void | Promise<void>;
  onStop: () => void | Promise<void>;
  onReset: () => void | Promise<void>;
  onSpeedChange: (speed: SimulationSpeed) => void | Promise<void>;
  onRunModeChange?: (mode: SimulationRunMode) => void;
  onClearError?: () => void;
  className?: string;
}

/**
 * Validates if START action is permissible per Section 57 state machine.
 */
export function canStart(status: SimulationLifecycleStatus): boolean {
  return status === "IDLE" || status === "CREATED";
}

/**
 * Validates if PAUSE action is permissible per Section 57 state machine.
 */
export function canPause(status: SimulationLifecycleStatus): boolean {
  return status === "RUNNING";
}

/**
 * Validates if RESUME action is permissible per Section 57 state machine.
 */
export function canResume(status: SimulationLifecycleStatus): boolean {
  return status === "PAUSED";
}

/**
 * Validates if STEP action is permissible.
 * Per Section 57: "STEP is valid only while PAUSED. It advances the simulation clock by exactly 1 completed candle cycle and freezes again in PAUSED."
 */
export function canStep(status: SimulationLifecycleStatus): boolean {
  return status === "PAUSED";
}

/**
 * Validates if STOP action is permissible.
 * Per Section 57: RUNNING or PAUSED -> STOPPED.
 */
export function canStop(status: SimulationLifecycleStatus): boolean {
  return status === "RUNNING" || status === "PAUSED";
}

/**
 * Validates if RESET action is permissible.
 * Reset is allowed on paused, stopped, completed, or errored sessions.
 */
export function canReset(status: SimulationLifecycleStatus): boolean {
  return (
    status === "PAUSED" ||
    status === "STOPPED" ||
    status === "COMPLETED" ||
    status === "ERROR"
  );
}
