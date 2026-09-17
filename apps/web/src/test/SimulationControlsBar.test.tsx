import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { SimulationControlsBar } from "../components/SimulationControlsBar";
import {
  canStart,
  canPause,
  canResume,
  canStep,
  canStop,
  canReset,
  SimulationLifecycleStatus,
} from "../types/simulation-controls";

describe("Phase 10E: Interactive Simulation Controls Bar", () => {
  const defaultProps = {
    simulationId: "sim-test-101",
    status: "CREATED" as SimulationLifecycleStatus,
    speed: 1.0 as const,
    runMode: "BASELINE" as const,
    stepIndex: 0,
    totalCandles: 100,
    progressPct: 0.0,
    currentTime: "2026-01-05T09:15:00Z",
    symbol: "RELIANCE",
    timeframe: "15m",
    isLoadingAction: false,
    errorMessage: null,
    onStart: vi.fn(),
    onPause: vi.fn(),
    onResume: vi.fn(),
    onStep: vi.fn(),
    onStop: vi.fn(),
    onReset: vi.fn(),
    onSpeedChange: vi.fn(),
    onRunModeChange: vi.fn(),
    onClearError: vi.fn(),
  };

  // ---------------------------------------------------------------------------
  // 1. Pure State Machine Transition Predicates
  // ---------------------------------------------------------------------------
  describe("State Machine Transition Predicates (Section 57)", () => {
    it("enforces canStart rules", () => {
      expect(canStart("IDLE")).toBe(true);
      expect(canStart("CREATED")).toBe(true);
      expect(canStart("RUNNING")).toBe(false);
      expect(canStart("PAUSED")).toBe(false);
      expect(canStart("STOPPED")).toBe(false);
      expect(canStart("COMPLETED")).toBe(false);
      expect(canStart("ERROR")).toBe(false);
    });

    it("enforces canPause rules", () => {
      expect(canPause("RUNNING")).toBe(true);
      expect(canPause("PAUSED")).toBe(false);
      expect(canPause("CREATED")).toBe(false);
      expect(canPause("IDLE")).toBe(false);
      expect(canPause("STOPPED")).toBe(false);
    });

    it("enforces canResume rules", () => {
      expect(canResume("PAUSED")).toBe(true);
      expect(canResume("RUNNING")).toBe(false);
      expect(canResume("CREATED")).toBe(false);
      expect(canResume("STOPPED")).toBe(false);
    });

    it("strictly enforces canStep ONLY while PAUSED per Section 57", () => {
      expect(canStep("PAUSED")).toBe(true);
      expect(canStep("RUNNING")).toBe(false);
      expect(canStep("CREATED")).toBe(false);
      expect(canStep("IDLE")).toBe(false);
      expect(canStep("STOPPED")).toBe(false);
      expect(canStep("COMPLETED")).toBe(false);
      expect(canStep("ERROR")).toBe(false);
    });

    it("enforces canStop rules (RUNNING or PAUSED -> STOPPED)", () => {
      expect(canStop("RUNNING")).toBe(true);
      expect(canStop("PAUSED")).toBe(true);
      expect(canStop("CREATED")).toBe(false);
      expect(canStop("IDLE")).toBe(false);
      expect(canStop("STOPPED")).toBe(false);
      expect(canStop("COMPLETED")).toBe(false);
    });

    it("enforces canReset rules", () => {
      expect(canReset("PAUSED")).toBe(true);
      expect(canReset("STOPPED")).toBe(true);
      expect(canReset("COMPLETED")).toBe(true);
      expect(canReset("ERROR")).toBe(true);
      expect(canReset("RUNNING")).toBe(false);
      expect(canReset("IDLE")).toBe(false);
    });
  });

  // ---------------------------------------------------------------------------
  // 2. Control Buttons & Action Dispatching
  // ---------------------------------------------------------------------------
  describe("Control Buttons & Action Dispatching", () => {
    it("renders START enabled and other controls disabled in CREATED state", () => {
      render(<SimulationControlsBar {...defaultProps} status="CREATED" />);

      const startBtn = screen.getByTestId("sim-start-btn");
      expect(startBtn).toBeEnabled();

      const stepBtn = screen.getByTestId("sim-step-btn");
      expect(stepBtn).toBeDisabled();

      const stopBtn = screen.getByTestId("sim-stop-btn");
      expect(stopBtn).toBeDisabled();

      const resetBtn = screen.getByTestId("sim-reset-btn");
      expect(resetBtn).toBeDisabled();
    });

    it("triggers onStart when START button is clicked", () => {
      const onStart = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="CREATED"
          onStart={onStart}
        />
      );

      fireEvent.click(screen.getByTestId("sim-start-btn"));
      expect(onStart).toHaveBeenCalledTimes(1);
    });

    it("renders PAUSE enabled and triggers onPause in RUNNING state", () => {
      const onPause = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="RUNNING"
          onPause={onPause}
        />
      );

      const pauseBtn = screen.getByTestId("sim-pause-btn");
      expect(pauseBtn).toBeEnabled();

      const stopBtn = screen.getByTestId("sim-stop-btn");
      expect(stopBtn).toBeEnabled();

      const stepBtn = screen.getByTestId("sim-step-btn");
      expect(stepBtn).toBeDisabled();

      fireEvent.click(pauseBtn);
      expect(onPause).toHaveBeenCalledTimes(1);
    });

    it("renders RESUME and STEP enabled in PAUSED state", () => {
      const onResume = vi.fn();
      const onStep = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="PAUSED"
          onResume={onResume}
          onStep={onStep}
        />
      );

      const resumeBtn = screen.getByTestId("sim-resume-btn");
      expect(resumeBtn).toBeEnabled();

      const stepBtn = screen.getByTestId("sim-step-btn");
      expect(stepBtn).toBeEnabled();

      fireEvent.click(resumeBtn);
      expect(onResume).toHaveBeenCalledTimes(1);

      fireEvent.click(stepBtn);
      expect(onStep).toHaveBeenCalledTimes(1);
    });

    it("triggers onStop when STOP button is clicked while RUNNING", () => {
      const onStop = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="RUNNING"
          onStop={onStop}
        />
      );

      const stopBtn = screen.getByTestId("sim-stop-btn");
      expect(stopBtn).toBeEnabled();

      fireEvent.click(stopBtn);
      expect(onStop).toHaveBeenCalledTimes(1);
    });

    it("triggers onReset when RESET button is clicked in STOPPED state", () => {
      const onReset = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="STOPPED"
          onReset={onReset}
        />
      );

      const resetBtn = screen.getByTestId("sim-reset-btn");
      expect(resetBtn).toBeEnabled();

      fireEvent.click(resetBtn);
      expect(onReset).toHaveBeenCalledTimes(1);
    });
  });

  // ---------------------------------------------------------------------------
  // 3. Playback Speed Multipliers & Run Mode Controls
  // ---------------------------------------------------------------------------
  describe("Speed & Run Mode Selectors", () => {
    it("renders all 5 supported speed multipliers and dispatches onSpeedChange", () => {
      const onSpeedChange = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          speed={1.0}
          onSpeedChange={onSpeedChange}
        />
      );

      const speed1x = screen.getByTestId("sim-speed-1x");
      expect(speed1x).toHaveClass("bg-cyan-500/20");

      const speed2x = screen.getByTestId("sim-speed-2x");
      fireEvent.click(speed2x);
      expect(onSpeedChange).toHaveBeenCalledWith(2.0);

      const speed05x = screen.getByTestId("sim-speed-0.5x");
      fireEvent.click(speed05x);
      expect(onSpeedChange).toHaveBeenCalledWith(0.5);

      const speed10x = screen.getByTestId("sim-speed-10x");
      fireEvent.click(speed10x);
      expect(onSpeedChange).toHaveBeenCalledWith(10.0);
    });

    it("switches run modes between AI Agent and Baseline when idle / unattached", () => {
      const onRunModeChange = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          simulationId={null}
          status="IDLE"
          runMode="BASELINE"
          onRunModeChange={onRunModeChange}
        />
      );

      const agentBtn = screen.getByTestId("sim-mode-agent");
      const baselineBtn = screen.getByTestId("sim-mode-baseline");

      expect(baselineBtn).toHaveClass("bg-amber-500/20");
      expect(agentBtn).not.toBeDisabled();

      fireEvent.click(agentBtn);
      expect(onRunModeChange).toHaveBeenCalledWith("AGENT");
    });

    it("locks run mode switching when attached to an active simulation session", () => {
      render(
        <SimulationControlsBar
          {...defaultProps}
          simulationId="sim-test-101"
          status="RUNNING"
          runMode="BASELINE"
        />
      );

      expect(screen.getByTestId("sim-mode-agent")).toBeDisabled();
      expect(screen.getByTestId("sim-mode-baseline")).toBeDisabled();
      expect(screen.getByTestId("sim-mode-agent")).toHaveAttribute(
        "title",
        "Strategy mode is determined by active simulation session"
      );
    });
  });

  // ---------------------------------------------------------------------------
  // 4. In-flight Protection & Rapid Action Safety
  // ---------------------------------------------------------------------------
  describe("Concurrency & Double-Click Guarding", () => {
    it("disables control actions and renders loading indicator when isLoadingAction is true", () => {
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="CREATED"
          isLoadingAction={true}
        />
      );

      expect(screen.getByTestId("sim-start-btn")).toBeDisabled();
      expect(screen.getByTestId("sim-step-btn")).toBeDisabled();
      expect(screen.getByTestId("sim-stop-btn")).toBeDisabled();
      expect(screen.getByTestId("sim-reset-btn")).toBeDisabled();
      expect(screen.getByTestId("sim-action-loading")).toBeInTheDocument();
      expect(screen.getByText("Syncing...")).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // 5. Readouts & Progress Bar
  // ---------------------------------------------------------------------------
  describe("Readouts & Visual Progress", () => {
    it("formats virtual clock and step counter correctly", () => {
      render(
        <SimulationControlsBar
          {...defaultProps}
          currentTime="2026-01-05T10:15:00.000Z"
          stepIndex={24}
          totalCandles={96}
          progressPct={25.0}
        />
      );

      const clock = screen.getByTestId("sim-clock-display");
      expect(clock).toHaveTextContent("2026-01-05 10:15:00 UTC");

      const counter = screen.getByTestId("sim-step-counter");
      expect(counter).toHaveTextContent("Bar 24 / 96");
      expect(counter).toHaveTextContent("(25.0%)");

      const progressBar = screen.getByTestId("sim-progress-bar");
      expect(progressBar).toHaveStyle({ width: "25%" });
    });

    it("renders error banner and handles dismissal", () => {
      const onClearError = vi.fn();
      render(
        <SimulationControlsBar
          {...defaultProps}
          status="ERROR"
          errorMessage="Invalid state transition from COMPLETED to RUNNING"
          onClearError={onClearError}
        />
      );

      const banner = screen.getByTestId("sim-error-banner");
      expect(banner).toHaveTextContent("Invalid state transition from COMPLETED to RUNNING");

      const dismissBtn = screen.getByText("✕");
      fireEvent.click(dismissBtn);
      expect(onClearError).toHaveBeenCalledTimes(1);
    });

    it("renders status badges with appropriate styles for all states", () => {
      const { rerender } = render(
        <SimulationControlsBar {...defaultProps} status="IDLE" />
      );
      expect(screen.getByTestId("sim-status-badge")).toHaveTextContent("IDLE");

      rerender(<SimulationControlsBar {...defaultProps} status="RUNNING" />);
      expect(screen.getByTestId("sim-status-badge")).toHaveTextContent("RUNNING");

      rerender(<SimulationControlsBar {...defaultProps} status="PAUSED" />);
      expect(screen.getByTestId("sim-status-badge")).toHaveTextContent("PAUSED");

      rerender(<SimulationControlsBar {...defaultProps} status="COMPLETED" />);
      expect(screen.getByTestId("sim-status-badge")).toHaveTextContent("COMPLETED");

      rerender(<SimulationControlsBar {...defaultProps} status="STOPPED" />);
      expect(screen.getByTestId("sim-status-badge")).toHaveTextContent("STOPPED");

      rerender(<SimulationControlsBar {...defaultProps} status="ERROR" />);
      expect(screen.getByTestId("sim-status-badge")).toHaveTextContent("ERROR");
    });
  });
});
