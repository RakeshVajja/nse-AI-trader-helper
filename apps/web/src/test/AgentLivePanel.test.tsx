import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { AgentLivePanel } from "../components/AgentLivePanel";
import {
  createInitialAgentLiveState,
  reduceAgentLiveState,
  parseRegimeString,
  AgentLivePanelState,
} from "../types/agent-panel";
import { SimulationEvent } from "../types";

describe("Phase 10C: AgentLivePanel Component & Reducer", () => {
  // ---------------------------------------------------------------------------
  // 1. Initial State Rendering
  // ---------------------------------------------------------------------------
  it("1. renders initial agent state with clean default values", () => {
    const initialState = createInitialAgentLiveState({
      agentName: "Reliance Momentum Agent",
      strategyStyle: "momentum",
      status: "READY",
    });

    render(<AgentLivePanel state={initialState} />);

    expect(screen.getByTestId("agent-live-panel")).toBeInTheDocument();
    expect(screen.getByTestId("agent-name")).toHaveTextContent("Reliance Momentum Agent");
    expect(screen.getByTestId("agent-status-badge")).toHaveTextContent("READY");
    expect(screen.getByTestId("signal-pill")).toHaveTextContent("WAITING FOR SIGNAL");
    expect(screen.getByTestId("confidence-value")).toHaveTextContent("—");
    expect(screen.getByTestId("position-status-badge")).toHaveTextContent("FLAT");
    expect(screen.getByTestId("regime-trend-badge")).toHaveTextContent("WARMUP / N/A");
    expect(screen.getByTestId("regime-volatility-badge")).toHaveTextContent("WARMUP / N/A");
  });

  // ---------------------------------------------------------------------------
  // 2. BUY / SELL / HOLD Decision Display
  // ---------------------------------------------------------------------------
  it("2. renders BUY, SELL, and HOLD decision display correctly", () => {
    // 2a. BUY Decision
    const buyState: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "BUY",
        confidence: 0.82,
        reason: "Golden cross crossover confirmed",
        observations: ["✓ EMA9 crossed above EMA20"],
      },
    };
    const { rerender } = render(<AgentLivePanel state={buyState} />);
    const buyPill = screen.getByTestId("signal-pill");
    expect(buyPill).toHaveTextContent("BUY");
    expect(buyPill.className).toContain("text-emerald-300");

    // 2b. SELL Decision
    const sellState: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "SELL",
        confidence: 0.75,
        reason: "Bearish engulfing pattern detected",
        observations: ["✗ Price rejected at resistance"],
      },
    };
    rerender(<AgentLivePanel state={sellState} />);
    const sellPill = screen.getByTestId("signal-pill");
    expect(sellPill).toHaveTextContent("SELL");
    expect(sellPill.className).toContain("text-rose-300");

    // 2c. HOLD Decision
    const holdState: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "HOLD",
        confidence: 0.6,
        reason: "Market consolidating within range",
        observations: ["• No crossover detected"],
      },
    };
    rerender(<AgentLivePanel state={holdState} />);
    const holdPill = screen.getByTestId("signal-pill");
    expect(holdPill).toHaveTextContent("HOLD");
    expect(holdPill.className).toContain("text-amber-300");
  });

  // ---------------------------------------------------------------------------
  // 3. Confidence Conversion & Display
  // ---------------------------------------------------------------------------
  it("3. converts and displays decimal confidence as percentage and updates meter", () => {
    const state: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "BUY",
        confidence: 0.85,
        reason: "Strong momentum breakout",
        observations: ["✓ Volume surge confirmed"],
      },
    };

    render(<AgentLivePanel state={state} />);

    expect(screen.getByTestId("confidence-value")).toHaveTextContent("85%");
    const bar = screen.getByTestId("confidence-bar");
    expect(bar).toHaveStyle({ width: "85%" });
  });

  // ---------------------------------------------------------------------------
  // 4. Observations Rendering
  // ---------------------------------------------------------------------------
  it("4. renders concise observations with icons and falls back to reason when empty", () => {
    const stateWithObs: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "BUY",
        confidence: 0.78,
        reason: "Multiple indicator alignment",
        observations: [
          "✓ EMA9 above EMA20",
          "✓ MACD positive",
          "⚠ RSI elevated",
        ],
      },
    };

    const { rerender } = render(<AgentLivePanel state={stateWithObs} />);
    const list = screen.getByTestId("observations-list");
    expect(list).toHaveTextContent("✓ EMA9 above EMA20");
    expect(list).toHaveTextContent("✓ MACD positive");
    expect(list).toHaveTextContent("⚠ RSI elevated");

    // Fallback to reason when observations array is empty
    const stateFallback: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "HOLD",
        confidence: 0.5,
        reason: "Waiting for trend clarification",
        observations: [],
      },
    };
    rerender(<AgentLivePanel state={stateFallback} />);
    expect(screen.getByTestId("observations-list")).toHaveTextContent(
      "Waiting for trend clarification"
    );
  });

  // ---------------------------------------------------------------------------
  // 5. Regime Display
  // ---------------------------------------------------------------------------
  it("5. displays authoritative market regime and shows warmup when unavailable", () => {
    const bullishState: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      regime: {
        trend: "BULLISH",
        volatility: "NORMAL",
      },
    };

    const { rerender } = render(<AgentLivePanel state={bullishState} />);
    expect(screen.getByTestId("regime-trend-badge")).toHaveTextContent("BULLISH");
    expect(screen.getByTestId("regime-volatility-badge")).toHaveTextContent("NORMAL");

    // Bearish High Volatility
    const bearishState: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      regime: {
        trend: "BEARISH",
        volatility: "HIGH",
      },
    };
    rerender(<AgentLivePanel state={bearishState} />);
    expect(screen.getByTestId("regime-trend-badge")).toHaveTextContent("BEARISH");
    expect(screen.getByTestId("regime-volatility-badge")).toHaveTextContent("HIGH");

    // Null regime -> explicit warmup state
    const warmupState: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      regime: null,
    };
    rerender(<AgentLivePanel state={warmupState} />);
    expect(screen.getByTestId("regime-trend-badge")).toHaveTextContent("WARMUP / N/A");
    expect(screen.getByTestId("regime-volatility-badge")).toHaveTextContent("WARMUP / N/A");
  });

  // ---------------------------------------------------------------------------
  // 6. Position Display
  // ---------------------------------------------------------------------------
  it("6. displays open position details accurately", () => {
    const stateWithPos: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      activePosition: {
        symbol: "RELIANCE",
        quantity: 20,
        averageEntryPrice: 2450.0,
        currentPrice: 2485.5,
        unrealizedPnl: 710.0,
        stopLoss: 2410.0,
        takeProfit: 2520.0,
        isOpen: true,
      },
    };

    render(<AgentLivePanel state={stateWithPos} />);

    expect(screen.getByTestId("position-status-badge")).toHaveTextContent("OPEN");
    expect(screen.getByTestId("active-position-details")).toHaveTextContent(
      "RELIANCE • 20 QTY"
    );
    expect(screen.getByTestId("entry-price")).toHaveTextContent("₹2,450.00");
    expect(screen.getByTestId("current-price")).toHaveTextContent("₹2,485.50");
    expect(screen.getByTestId("unrealized-pnl")).toHaveTextContent("+₹710.00");
  });

  // ---------------------------------------------------------------------------
  // 7. Live SL / TP Display
  // ---------------------------------------------------------------------------
  it("7. displays live Stop-Loss and Take-Profit prices from active position", () => {
    const state: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      activePosition: {
        symbol: "TCS",
        quantity: 10,
        averageEntryPrice: 3500.0,
        currentPrice: 3520.0,
        unrealizedPnl: 200.0,
        stopLoss: 3450.0,
        takeProfit: 3600.0,
        isOpen: true,
      },
    };

    render(<AgentLivePanel state={state} />);

    expect(screen.getByTestId("live-stop-loss")).toHaveTextContent("₹3,450.00");
    expect(screen.getByTestId("live-take-profit")).toHaveTextContent("₹3,600.00");
  });

  // ---------------------------------------------------------------------------
  // 8. Position Close Clears Stale SL/TP
  // ---------------------------------------------------------------------------
  it("8. clears stale position and SL/TP when position closes", () => {
    const openState: AgentLivePanelState = {
      ...createInitialAgentLiveState({ simulationId: "sim-1" }),
      activePosition: {
        symbol: "RELIANCE",
        quantity: 15,
        averageEntryPrice: 2400.0,
        currentPrice: 2450.0,
        unrealizedPnl: 750.0,
        stopLoss: 2380.0,
        takeProfit: 2500.0,
        isOpen: true,
      },
    };

    // Position updated event indicating position is now closed
    const closeEvent: SimulationEvent = {
      event_type: "position_updated",
      simulation_id: "sim-1",
      sequence: 5,
      wall_clock_timestamp: "2026-09-16T10:30:00Z",
      payload: {
        positions: [
          {
            symbol: "RELIANCE",
            quantity: 0,
            average_entry_price: 2400.0,
            current_price: 2450.0,
            unrealized_pnl: 0.0,
            stop_loss: null,
            take_profit: null,
            is_open: false,
          },
        ],
      },
    };

    const nextState = reduceAgentLiveState(openState, closeEvent);
    expect(nextState.activePosition).toBeNull();

    render(<AgentLivePanel state={nextState} />);
    expect(screen.getByTestId("position-status-badge")).toHaveTextContent("FLAT");
    expect(screen.getByTestId("live-stop-loss")).toHaveTextContent("—");
    expect(screen.getByTestId("live-take-profit")).toHaveTextContent("—");
  });

  // ---------------------------------------------------------------------------
  // 9. New Agent Decision Updates the Panel
  // ---------------------------------------------------------------------------
  it("9. updates panel when a new agent_decision event arrives", () => {
    const initialState = createInitialAgentLiveState({ simulationId: "sim-1" });

    const decisionEvent: SimulationEvent = {
      event_type: "agent_decision",
      simulation_id: "sim-1",
      sequence: 2,
      virtual_timestamp: "2026-09-16T09:45:00Z",
      wall_clock_timestamp: "2026-09-16T09:45:01Z",
      payload: {
        action: "BUY",
        confidence: 0.88,
        quantity: 10,
        stop_loss: 2420.0,
        take_profit: 2500.0,
        reason: "Strong RSI rebound from 45 with volume spike",
        observations: [
          "✓ RSI rebounded from 45",
          "✓ Volume 1.5x 20-period average",
        ],
        market_regime: "BULLISH / NORMAL",
      },
    };

    const updatedState = reduceAgentLiveState(initialState, decisionEvent);

    expect(updatedState.latestDecision?.action).toBe("BUY");
    expect(updatedState.latestDecision?.confidence).toBe(0.88);
    expect(updatedState.latestDecision?.observations).toHaveLength(2);
    expect(updatedState.regime?.trend).toBe("BULLISH");
    expect(updatedState.regime?.volatility).toBe("NORMAL");

    render(<AgentLivePanel state={updatedState} />);
    expect(screen.getByTestId("signal-pill")).toHaveTextContent("BUY");
    expect(screen.getByTestId("confidence-value")).toHaveTextContent("88%");
    expect(screen.getByTestId("observations-list")).toHaveTextContent("✓ RSI rebounded from 45");
  });

  // ---------------------------------------------------------------------------
  // 10. Signal Remains Distinct from Actual Execution
  // ---------------------------------------------------------------------------
  it("10. ensures BUY signal does not fabricate an open position without fill", () => {
    const initialState = createInitialAgentLiveState({ simulationId: "sim-1" });

    const signalEvent: SimulationEvent = {
      event_type: "agent_decision",
      simulation_id: "sim-1",
      sequence: 10,
      wall_clock_timestamp: "2026-09-16T10:00:00Z",
      payload: {
        action: "BUY",
        confidence: 0.95,
        reason: "Aggressive breakout setup",
        observations: ["✓ EMA9 cross"],
      },
    };

    const stateAfterSignal = reduceAgentLiveState(initialState, signalEvent);

    // Decision exists
    expect(stateAfterSignal.latestDecision?.action).toBe("BUY");
    // Position must strictly remain null / FLAT
    expect(stateAfterSignal.activePosition).toBeNull();

    render(<AgentLivePanel state={stateAfterSignal} />);
    expect(screen.getByTestId("signal-pill")).toHaveTextContent("BUY");
    expect(screen.getByTestId("position-status-badge")).toHaveTextContent("FLAT");
    expect(screen.getByTestId("flat-position-details")).toHaveTextContent(
      "ACTIVE POSITION:NONE (FLAT)"
    );
  });

  // ---------------------------------------------------------------------------
  // 11. Simulation ID Mismatch is Ignored
  // ---------------------------------------------------------------------------
  it("11. ignores events belonging to a different simulation ID", () => {
    const stateSim1 = createInitialAgentLiveState({
      simulationId: "sim-100",
      status: "READY",
    });

    const foreignEvent: SimulationEvent = {
      event_type: "agent_decision",
      simulation_id: "sim-OTHER",
      sequence: 1,
      wall_clock_timestamp: "2026-09-16T10:00:00Z",
      payload: {
        action: "SELL",
        confidence: 0.99,
        reason: "Foreign decision",
      },
    };

    const result = reduceAgentLiveState(stateSim1, foreignEvent);
    expect(result).toBe(stateSim1);
    expect(result.latestDecision).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // 12. initial_state Correctly Initializes the Panel
  // ---------------------------------------------------------------------------
  it("12. initializes agent state and active position from initial_state event", () => {
    const emptyState = createInitialAgentLiveState();

    const initialEvent: SimulationEvent = {
      event_type: "initial_state",
      simulation_id: "sim-boot",
      sequence: 1,
      virtual_timestamp: "2026-09-16T09:15:00Z",
      wall_clock_timestamp: "2026-09-16T09:15:01Z",
      payload: {
        simulation_id: "sim-boot",
        status: "RUNNING",
        symbol: "RELIANCE",
        timeframe: "15m",
        step_index: 10,
        total_candles: 100,
        progress_pct: 10.0,
        current_time: "2026-09-16T09:15:00Z",
        positions: [
          {
            symbol: "RELIANCE",
            quantity: 50,
            average_entry_price: 2400.0,
            current_price: 2420.0,
            unrealized_pnl: 1000.0,
            stop_loss: 2360.0,
            take_profit: 2480.0,
            is_open: true,
          },
        ],
        portfolio: {
          cash: 80000.0,
          portfolio_value: 201000.0,
          gross_pnl: 1000.0,
          net_pnl: 950.0,
          total_return_pct: 0.95,
          exposure_pct: 60.0,
          open_positions_count: 1,
        },
      },
    };

    const initializedState = reduceAgentLiveState(emptyState, initialEvent);

    expect(initializedState.simulationId).toBe("sim-boot");
    expect(initializedState.status).toBe("RUNNING");
    expect(initializedState.activePosition?.symbol).toBe("RELIANCE");
    expect(initializedState.activePosition?.quantity).toBe(50);
    expect(initializedState.activePosition?.stopLoss).toBe(2360.0);
    expect(initializedState.portfolio?.netPnl).toBe(950.0);

    render(<AgentLivePanel state={initializedState} />);
    expect(screen.getByTestId("agent-status-badge")).toHaveTextContent("ACTIVE");
    expect(screen.getByTestId("live-stop-loss")).toHaveTextContent("₹2,360.00");
    expect(screen.getByTestId("live-take-profit")).toHaveTextContent("₹2,480.00");
  });

  // ---------------------------------------------------------------------------
  // 13. Connection / Error State Behaves According to Specification
  // ---------------------------------------------------------------------------
  it("13. transitions to ERROR state and displays error banner on error event", () => {
    const state = createInitialAgentLiveState({ simulationId: "sim-1" });

    const errorEvent: SimulationEvent = {
      event_type: "error",
      simulation_id: "sim-1",
      sequence: 8,
      wall_clock_timestamp: "2026-09-16T11:00:00Z",
      payload: {
        code: "SIM_RATE_LIMIT",
        message: "Simulation rate limit reached; agent automatically paused",
      },
    };

    const errorState = reduceAgentLiveState(state, errorEvent);
    expect(errorState.status).toBe("ERROR");
    expect(errorState.errorMessage).toBe(
      "Simulation rate limit reached; agent automatically paused"
    );

    render(<AgentLivePanel state={errorState} />);
    expect(screen.getByTestId("agent-status-badge")).toHaveTextContent("ERROR");
    expect(screen.getByTestId("agent-error-banner")).toHaveTextContent(
      "Simulation rate limit reached; agent automatically paused"
    );
  });

  // ---------------------------------------------------------------------------
  // 14. Malformed / Irrelevant Events Do Not Crash
  // ---------------------------------------------------------------------------
  it("14. safely ignores irrelevant or empty payload events without throwing", () => {
    const state = createInitialAgentLiveState({ simulationId: "sim-1" });

    const candleEvent: SimulationEvent = {
      event_type: "candle_update",
      simulation_id: "sim-1",
      sequence: 3,
      wall_clock_timestamp: "2026-09-16T10:00:00Z",
      payload: { step_index: 5, candle: {} as any },
    };

    const toolCallEvent: SimulationEvent = {
      event_type: "tool_call",
      simulation_id: "sim-1",
      sequence: 4,
      wall_clock_timestamp: "2026-09-16T10:00:01Z",
      payload: { agent_id: "agent-1", tool_name: "get_indicators", tool_args: {} },
    };

    let next = reduceAgentLiveState(state, candleEvent);
    next = reduceAgentLiveState(next, toolCallEvent);

    expect(next).toBe(state);
    expect(() => render(<AgentLivePanel state={next} />)).not.toThrow();
  });

  // ---------------------------------------------------------------------------
  // 15. No Private Reasoning or Tool Internals Rendered
  // ---------------------------------------------------------------------------
  it("15. does not render private reasoning, chain-of-thought, or tool internals", () => {
    const state: AgentLivePanelState = {
      ...createInitialAgentLiveState(),
      latestDecision: {
        action: "BUY",
        confidence: 0.8,
        reason: "Moving average crossover validated",
        observations: ["✓ EMA9 above EMA20"],
      },
    };

    const { container } = render(<AgentLivePanel state={state} />);
    const text = container.textContent || "";

    expect(text).not.toContain("chain_of_thought");
    expect(text).not.toContain("thought_tokens");
    expect(text).not.toContain("api_key");
    expect(text).not.toContain("system_instruction");
    expect(text).not.toContain("Traceback");
  });

  // ---------------------------------------------------------------------------
  // 16. Instrument / Simulation Change Clears Stale State
  // ---------------------------------------------------------------------------
  it("16. resets all stale decisions and positions on simulation/instrument reset", () => {
    const priorState: AgentLivePanelState = {
      simulationId: "old-sim",
      agentId: "agent-1",
      agentName: "Old Agent",
      strategyStyle: "momentum",
      status: "RUNNING",
      regime: { trend: "BULLISH", volatility: "NORMAL" },
      latestDecision: {
        action: "BUY",
        confidence: 0.9,
        reason: "Old signal",
        observations: ["Old observation"],
      },
      activePosition: {
        symbol: "RELIANCE",
        quantity: 50,
        averageEntryPrice: 2400.0,
        currentPrice: 2450.0,
        unrealizedPnl: 2500.0,
        isOpen: true,
      },
      portfolio: {
        cash: 100000,
        portfolioValue: 222500,
        grossPnl: 2500,
        netPnl: 2400,
        totalReturnPct: 2.4,
      },
      errorMessage: "Old error",
      lastUpdated: "2026-09-15T15:30:00Z",
      stepIndex: 50,
    };

    // Resetting for new symbol or new simulation run
    const resetState = createInitialAgentLiveState({
      simulationId: "new-sim",
      agentName: "TCS Quant Agent",
      strategyStyle: "trend_following",
    });

    expect(resetState.simulationId).toBe("new-sim");
    expect(resetState.latestDecision).toBeNull();
    expect(resetState.activePosition).toBeNull();
    expect(resetState.errorMessage).toBeNull();
    expect(resetState.regime).toBeNull();
    expect(resetState.status).toBe("READY");

    render(<AgentLivePanel state={resetState} />);
    expect(screen.getByTestId("agent-name")).toHaveTextContent("TCS Quant Agent");
    expect(screen.getByTestId("signal-pill")).toHaveTextContent("WAITING FOR SIGNAL");
    expect(screen.getByTestId("position-status-badge")).toHaveTextContent("FLAT");
  });

  // ---------------------------------------------------------------------------
  // Helper: parseRegimeString
  // ---------------------------------------------------------------------------
  it("parses market regime string formats correctly", () => {
    expect(parseRegimeString("BULLISH / NORMAL")).toEqual({
      trend: "BULLISH",
      volatility: "NORMAL",
      raw: "BULLISH / NORMAL",
    });

    expect(parseRegimeString("BEARISH / HIGH")).toEqual({
      trend: "BEARISH",
      volatility: "HIGH",
      raw: "BEARISH / HIGH",
    });

    expect(parseRegimeString("SIDEWAYS / LOW")).toEqual({
      trend: "SIDEWAYS",
      volatility: "LOW",
      raw: "SIDEWAYS / LOW",
    });

    expect(parseRegimeString(null)).toBeNull();
    expect(parseRegimeString("")).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // 17. Out-of-Order Sequence Rejection
  // ---------------------------------------------------------------------------
  it("17. rejects out-of-order and duplicate sequence frames within the same simulation", () => {
    const stateSeq10: AgentLivePanelState = {
      ...createInitialAgentLiveState({ simulationId: "sim-1" }),
      status: "RUNNING",
      lastSequence: 10,
      latestDecision: {
        action: "BUY",
        confidence: 0.85,
        reason: "Sequence 10 decision",
        observations: ["Obs 10"],
      },
    };

    // Stale delayed analyzing event with sequence 9
    const delayedAnalyzingEvent: SimulationEvent = {
      event_type: "agent_analyzing",
      simulation_id: "sim-1",
      sequence: 9,
      wall_clock_timestamp: "2026-09-16T10:00:00Z",
      payload: { agent_id: "agent-1", candle_timestamp: "2026-09-16T10:00:00Z", step_index: 8 },
    };

    const resultAnalyzing = reduceAgentLiveState(stateSeq10, delayedAnalyzingEvent);
    expect(resultAnalyzing.status).toBe("RUNNING"); // Not regressed to ANALYZING
    expect(resultAnalyzing.lastSequence).toBe(10);

    // Newer event with sequence 11
    const newerDecisionEvent: SimulationEvent = {
      event_type: "agent_decision",
      simulation_id: "sim-1",
      sequence: 11,
      wall_clock_timestamp: "2026-09-16T10:05:00Z",
      payload: {
        action: "SELL",
        confidence: 0.9,
        reason: "Sequence 11 decision",
        observations: ["Obs 11"],
      },
    };

    const resultNewer = reduceAgentLiveState(stateSeq10, newerDecisionEvent);
    expect(resultNewer.status).toBe("RUNNING");
    expect(resultNewer.latestDecision?.action).toBe("SELL");
    expect(resultNewer.lastSequence).toBe(11);
  });

  // ---------------------------------------------------------------------------
  // 18. Detached / Standalone Panel Rejects Late Simulation Events
  // ---------------------------------------------------------------------------
  it("18. ignores events from a past simulation if the panel is in standalone/detached mode", () => {
    const detachedState = createInitialAgentLiveState({
      simulationId: null,
      status: "READY",
    });

    const strayPositionEvent: SimulationEvent = {
      event_type: "position_updated",
      simulation_id: "old-sim",
      sequence: 25,
      wall_clock_timestamp: "2026-09-16T10:15:00Z",
      payload: {
        positions: [
          {
            symbol: "RELIANCE",
            quantity: 100,
            average_entry_price: 2400,
            current_price: 2450,
            unrealized_pnl: 5000,
            is_open: true,
          },
        ],
      },
    };

    const result = reduceAgentLiveState(detachedState, strayPositionEvent);
    expect(result.simulationId).toBeNull();
    expect(result.activePosition).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // 19. initial_state followed immediately by agent_decision
  // ---------------------------------------------------------------------------
  it("19. transitions cleanly from initial_state to immediate agent_decision", () => {
    const blankState = createInitialAgentLiveState();

    const initialEvent: SimulationEvent = {
      event_type: "initial_state",
      simulation_id: "sim-stream",
      sequence: 1,
      wall_clock_timestamp: "2026-09-16T09:15:00Z",
      payload: {
        simulation_id: "sim-stream",
        status: "RUNNING",
        symbol: "INFY",
        timeframe: "15m",
        step_index: 0,
        total_candles: 50,
        progress_pct: 0,
        positions: [],
      },
    };

    const state1 = reduceAgentLiveState(blankState, initialEvent);
    expect(state1.simulationId).toBe("sim-stream");
    expect(state1.lastSequence).toBe(1);

    const decisionEvent: SimulationEvent = {
      event_type: "agent_decision",
      simulation_id: "sim-stream",
      sequence: 2,
      virtual_timestamp: "2026-09-16T09:30:00Z",
      wall_clock_timestamp: "2026-09-16T09:30:01Z",
      payload: {
        action: "BUY",
        confidence: 0.77,
        reason: "Breakout past resistance",
        observations: ["✓ Volume surge confirmed"],
      },
    };

    const state2 = reduceAgentLiveState(state1, decisionEvent);
    expect(state2.latestDecision?.action).toBe("BUY");
    expect(state2.lastSequence).toBe(2);
    expect(state2.activePosition).toBeNull(); // Position remains flat until position_updated fill
  });

  // ---------------------------------------------------------------------------
  // 20. Observation Sanitization Filters Internal Reasoning & Tokens
  // ---------------------------------------------------------------------------
  it("20. drops observations containing chain_of_thought, api keys, or raw json", () => {
    const state: AgentLivePanelState = {
      ...createInitialAgentLiveState({ simulationId: "sim-1" }),
      latestDecision: null,
    };

    const maliciousEvent: SimulationEvent = {
      event_type: "agent_decision",
      simulation_id: "sim-1",
      sequence: 1,
      wall_clock_timestamp: "2026-09-16T10:00:00Z",
      payload: {
        action: "BUY",
        confidence: 0.8,
        reason: "Valid buy rationale",
        observations: [
          "✓ Valid observation",
          "private chain_of_thought: evaluating user parameters",
          "thought_tokens: 420",
          "api_key: AIzaSyD...",
          "system_instruction: You are an agent",
          "Traceback (most recent call last):",
          '{"internal_state": "dirty"}',
        ],
      },
    };

    const sanitizedState = reduceAgentLiveState(state, maliciousEvent);
    expect(sanitizedState.latestDecision?.observations).toEqual(["✓ Valid observation"]);

    render(<AgentLivePanel state={sanitizedState} />);
    const list = screen.getByTestId("observations-list");
    expect(list).toHaveTextContent("✓ Valid observation");
    expect(list).not.toHaveTextContent("chain_of_thought");
    expect(list).not.toHaveTextContent("thought_tokens");
    expect(list).not.toHaveTextContent("api_key");
    expect(list).not.toHaveTextContent("system_instruction");
    expect(list).not.toHaveTextContent("Traceback");
  });
});

