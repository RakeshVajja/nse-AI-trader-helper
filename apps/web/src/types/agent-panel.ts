/**
 * Phase 10C: Agent Live Panel State & Reducer Types.
 * Presentation-only models driven authoritatively by Phase 10A WebSocket events.
 */

import {
  AgentAction,
  AgentStatus,
  InitialStatePayload,
  AgentStartedPayload,
  AgentAnalyzingPayload,
  AgentDecisionPayload,
  PositionUpdatedPayload,
  PortfolioUpdatedPayload,
  ErrorPayload,
  SimulationEvent,
  TrendRegime,
  VolatilityRegime,
} from "./index";

export interface AgentLiveDecisionState {
  action: AgentAction;
  confidence: number;
  reason: string;
  observations: string[];
  quantity?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  timestamp?: string | null;
  marketRegime?: string | null;
}

export interface AgentLivePositionState {
  symbol: string;
  quantity: number;
  averageEntryPrice: number;
  currentPrice: number;
  unrealizedPnl: number;
  stopLoss?: number | null;
  takeProfit?: number | null;
  isOpen: boolean;
}

export interface AgentLiveRegimeState {
  trend: TrendRegime | null;
  volatility: VolatilityRegime | null;
  raw?: string | null;
}

export interface AgentLivePortfolioState {
  cash: number;
  portfolioValue: number;
  grossPnl: number;
  netPnl: number;
  totalReturnPct: number;
}

export interface AgentLivePanelState {
  simulationId: string | null;
  agentId: string | null;
  agentName: string;
  strategyStyle: string | null;
  status: AgentStatus;
  regime: AgentLiveRegimeState | null;
  latestDecision: AgentLiveDecisionState | null;
  activePosition: AgentLivePositionState | null;
  portfolio: AgentLivePortfolioState | null;
  errorMessage: string | null;
  lastUpdated: string | null;
  stepIndex: number | null;
  lastSequence?: number | null;
}

/**
 * Creates a clean default AgentLivePanelState.
 */
export function createInitialAgentLiveState(
  options?: Partial<AgentLivePanelState>
): AgentLivePanelState {
  return {
    simulationId: options?.simulationId ?? null,
    agentId: options?.agentId ?? null,
    agentName: options?.agentName ?? "Quantitative Agent",
    strategyStyle: options?.strategyStyle ?? "MOMENTUM",
    status: options?.status ?? "READY",
    regime: options?.regime ?? null,
    latestDecision: options?.latestDecision ?? null,
    activePosition: options?.activePosition ?? null,
    portfolio: options?.portfolio ?? null,
    errorMessage: options?.errorMessage ?? null,
    lastUpdated: options?.lastUpdated ?? null,
    stepIndex: options?.stepIndex ?? null,
    lastSequence: options?.lastSequence ?? null,
  };
}

/**
 * Parses regime string into trend and volatility if formatted as e.g. "BULLISH" or "BULLISH / NORMAL".
 */
export function parseRegimeString(regimeStr?: string | null): AgentLiveRegimeState | null {
  if (!regimeStr || typeof regimeStr !== "string") return null;
  const upper = regimeStr.toUpperCase().trim();
  if (!upper) return null;

  let trend: TrendRegime | null = null;
  let volatility: VolatilityRegime | null = null;

  if (upper.includes("BULLISH")) trend = "BULLISH";
  else if (upper.includes("BEARISH")) trend = "BEARISH";
  else if (upper.includes("SIDEWAYS")) trend = "SIDEWAYS";

  if (upper.includes("HIGH")) volatility = "HIGH";
  else if (upper.includes("NORMAL")) volatility = "NORMAL";
  else if (upper.includes("LOW")) volatility = "LOW";

  return {
    trend,
    volatility,
    raw: regimeStr,
  };
}

/**
 * Sanitizes an observation or reason string to guarantee that no private
 * chain-of-thought, internal tool call traces, stack traces, or credentials enter the UI.
 */
export function sanitizeObservation(obs: string): string | null {
  if (!obs || typeof obs !== "string") return null;
  const trimmed = obs.trim();
  if (!trimmed) return null;

  const lower = trimmed.toLowerCase();
  if (
    lower.includes("chain_of_thought") ||
    lower.includes("thought_tokens") ||
    lower.includes("api_key") ||
    lower.includes("system_instruction") ||
    lower.includes("traceback") ||
    lower.includes("exception in") ||
    trimmed.startsWith("{")
  ) {
    return null;
  }

  return trimmed;
}

/**
 * Pure reducer function that processes authoritative simulation events
 * and returns the updated AgentLivePanelState.
 */
export function reduceAgentLiveState(
  prev: AgentLivePanelState,
  event: SimulationEvent
): AgentLivePanelState {
  // 1. Strict Simulation ID Isolation: discard events from other simulations
  if (prev.simulationId && event.simulation_id && event.simulation_id !== prev.simulationId) {
    return prev;
  }

  // 2. Discard events with an unattached simulation ID if panel is standalone/detached
  if (
    !prev.simulationId &&
    event.simulation_id &&
    event.event_type !== "initial_state" &&
    event.event_type !== "agent_started"
  ) {
    return prev;
  }

  // 3. Reject out-of-order or duplicate sequence frames (initial_state resets sequence counter)
  if (
    event.event_type !== "initial_state" &&
    prev.lastSequence !== null &&
    prev.lastSequence !== undefined &&
    typeof event.sequence === "number" &&
    event.sequence <= prev.lastSequence
  ) {
    return prev;
  }

  const timestamp = event.virtual_timestamp || event.wall_clock_timestamp;
  const currentSequence =
    typeof event.sequence === "number" ? event.sequence : prev.lastSequence;

  switch (event.event_type) {
    case "initial_state": {
      const p = event.payload as InitialStatePayload;
      if (!p) return prev;

      let openPos: AgentLivePositionState | null = null;
      if (p.positions && Array.isArray(p.positions)) {
        const found = p.positions.find((pos) => pos.is_open && pos.quantity > 0);
        if (found) {
          openPos = {
            symbol: found.symbol,
            quantity: found.quantity,
            averageEntryPrice: found.average_entry_price,
            currentPrice: found.current_price,
            unrealizedPnl: found.unrealized_pnl,
            stopLoss: found.stop_loss ?? null,
            takeProfit: found.take_profit ?? null,
            isOpen: true,
          };
        }
      }

      let port: AgentLivePortfolioState | null = prev.portfolio;
      if (p.portfolio) {
        port = {
          cash: p.portfolio.cash,
          portfolioValue: p.portfolio.portfolio_value,
          grossPnl: p.portfolio.gross_pnl,
          netPnl: p.portfolio.net_pnl,
          totalReturnPct: p.portfolio.total_return_pct,
        };
      }

      // If switching simulations on initial_state, clear past decisions
      const isNewSimulation =
        prev.simulationId !== null && prev.simulationId !== event.simulation_id;
      const latestDecision = isNewSimulation ? null : prev.latestDecision;

      return {
        ...prev,
        simulationId: event.simulation_id,
        status: (p.status as AgentStatus) || "READY",
        activePosition: openPos,
        portfolio: port,
        latestDecision,
        errorMessage: null,
        lastUpdated: timestamp || p.current_time || prev.lastUpdated,
        stepIndex: p.step_index ?? prev.stepIndex,
        lastSequence: typeof event.sequence === "number" ? event.sequence : 1,
      };
    }

    case "agent_started": {
      const p = event.payload as AgentStartedPayload;
      if (!p) return prev;

      return {
        ...prev,
        simulationId: event.simulation_id,
        agentId: p.agent_id || prev.agentId,
        agentName: p.agent_name || prev.agentName,
        strategyStyle: p.strategy_style || prev.strategyStyle,
        status: (p.status as AgentStatus) || "RUNNING",
        errorMessage: null,
        lastUpdated: timestamp,
        lastSequence: currentSequence,
      };
    }

    case "agent_analyzing": {
      const p = event.payload as AgentAnalyzingPayload;
      if (!p) return prev;

      return {
        ...prev,
        status: "ANALYZING",
        errorMessage: null,
        lastUpdated: p.candle_timestamp || timestamp,
        stepIndex: p.step_index ?? prev.stepIndex,
        lastSequence: currentSequence,
      };
    }

    case "agent_decision": {
      const p = event.payload as AgentDecisionPayload;
      if (!p) return prev;

      // Extract and sanitize concise observations
      let observations: string[] = [];
      if (Array.isArray(p.observations) && p.observations.length > 0) {
        observations = p.observations
          .map(sanitizeObservation)
          .filter((x): x is string => Boolean(x));
      } else if (p.reason && typeof p.reason === "string") {
        const sanitized = sanitizeObservation(p.reason);
        if (sanitized) {
          observations = [sanitized];
        }
      }

      // Update regime if payload provides one
      let newRegime = prev.regime;
      if (p.market_regime) {
        newRegime = parseRegimeString(p.market_regime);
      }

      const sanitizedReason = sanitizeObservation(p.reason) || "";

      const decision: AgentLiveDecisionState = {
        action: p.action,
        confidence: p.confidence,
        reason: sanitizedReason,
        observations,
        quantity: p.quantity ?? null,
        stopLoss: p.stop_loss ?? null,
        takeProfit: p.take_profit ?? null,
        timestamp,
        marketRegime: p.market_regime ?? null,
      };

      return {
        ...prev,
        latestDecision: decision,
        regime: newRegime,
        status: prev.status === "ANALYZING" ? "RUNNING" : prev.status,
        lastUpdated: timestamp,
        errorMessage: null,
        lastSequence: currentSequence,
      };
    }

    case "position_updated": {
      const p = event.payload as PositionUpdatedPayload;
      if (!p) return prev;

      let openPos: AgentLivePositionState | null = null;
      if (p.positions && Array.isArray(p.positions)) {
        const found = p.positions.find((pos) => pos.is_open && pos.quantity > 0);
        if (found) {
          openPos = {
            symbol: found.symbol,
            quantity: found.quantity,
            averageEntryPrice: found.average_entry_price,
            currentPrice: found.current_price,
            unrealizedPnl: found.unrealized_pnl,
            stopLoss: found.stop_loss ?? null,
            takeProfit: found.take_profit ?? null,
            isOpen: true,
          };
        }
      }

      // If no open position exists, activePosition becomes null (clears stale SL/TP)
      return {
        ...prev,
        activePosition: openPos,
        lastUpdated: timestamp,
        lastSequence: currentSequence,
      };
    }

    case "portfolio_updated": {
      const p = event.payload as PortfolioUpdatedPayload;
      if (!p) return prev;

      return {
        ...prev,
        portfolio: {
          cash: p.cash,
          portfolioValue: p.portfolio_value,
          grossPnl: p.gross_pnl,
          netPnl: p.net_pnl,
          totalReturnPct: p.total_return_pct,
        },
        lastUpdated: timestamp,
        lastSequence: currentSequence,
      };
    }

    case "simulation_complete": {
      return {
        ...prev,
        status: "COMPLETED",
        lastUpdated: timestamp,
        lastSequence: currentSequence,
      };
    }

    case "error": {
      const p = event.payload as ErrorPayload;
      return {
        ...prev,
        status: "ERROR",
        errorMessage: p?.message || p?.code || "Simulation execution error",
        lastUpdated: timestamp,
        lastSequence: currentSequence,
      };
    }

    default:
      // Ignore other events safely (candle_update, tool_call, tool_result, risk_check, order_executed)
      return prev;
  }
}
