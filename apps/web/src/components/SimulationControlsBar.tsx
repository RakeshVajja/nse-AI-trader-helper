"use client";

import React from "react";
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  StepForward,
  FastForward,
  Radio,
  AlertTriangle,
  XCircle,
  Clock,
  Layers,
  Cpu,
  TrendingUp,
} from "lucide-react";
import {
  SimulationSpeed,
  SimulationRunMode,
  SimulationLifecycleStatus,
  SimulationControlsBarProps,
  VALID_SIMULATION_SPEEDS,
  canStart,
  canPause,
  canResume,
  canStep,
  canStop,
  canReset,
} from "@/types";

export function SimulationControlsBar({
  simulationId,
  status,
  speed,
  runMode,
  stepIndex,
  totalCandles,
  progressPct,
  currentTime,
  symbol,
  timeframe,
  isLoadingAction = false,
  errorMessage = null,
  onStart,
  onPause,
  onResume,
  onStep,
  onStop,
  onReset,
  onSpeedChange,
  onRunModeChange,
  onClearError,
  className = "",
}: SimulationControlsBarProps) {
  // Determine actionable capabilities
  const startAllowed = canStart(status) && !isLoadingAction;
  const pauseAllowed = canPause(status) && !isLoadingAction;
  const resumeAllowed = canResume(status) && !isLoadingAction;
  const stepAllowed = canStep(status) && !isLoadingAction;
  const stopAllowed = canStop(status) && !isLoadingAction;
  const resetAllowed = canReset(status) && !isLoadingAction;
  const isModeLocked = Boolean(simulationId) || status !== "IDLE";

  // Status Badge Styling
  const getStatusBadge = () => {
    switch (status) {
      case "RUNNING":
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span>RUNNING</span>
          </span>
        );
      case "PAUSED":
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/30"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span>PAUSED</span>
          </span>
        );
      case "COMPLETED":
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-purple-500/15 text-purple-400 border border-purple-500/30"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
            <span>COMPLETED</span>
          </span>
        );
      case "STOPPED":
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            <span>STOPPED</span>
          </span>
        );
      case "ERROR":
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-rose-500/20 text-rose-300 border border-rose-500/40"
          >
            <XCircle className="w-3 h-3 text-rose-400" />
            <span>ERROR</span>
          </span>
        );
      case "CREATED":
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-cyan-500/15 text-cyan-400 border border-cyan-500/30"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
            <span>READY</span>
          </span>
        );
      default:
        return (
          <span
            data-testid="sim-status-badge"
            className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-slate-800 text-slate-400 border border-slate-700"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
            <span>IDLE</span>
          </span>
        );
    }
  };

  // Format virtual timestamp display
  const formatVirtualClock = (ts?: string | null) => {
    if (!ts) return "--:--:-- UTC";
    try {
      if (ts.includes("T")) {
        const parts = ts.split("T");
        const datePart = parts[0];
        const timePart = parts[1].slice(0, 8);
        return `${datePart} ${timePart} UTC`;
      }
      return ts;
    } catch {
      return ts;
    }
  };

  return (
    <div
      data-testid="simulation-controls-bar"
      className={`bg-[#0d131f] border-b border-[#1e293b] px-3.5 py-2 flex flex-col space-y-1.5 select-none ${className}`}
    >
      {/* Top Row: Playback Action Buttons, Mode & Speed Selectors, Status Badge */}
      <div className="flex items-center justify-between flex-wrap gap-2 text-xs">
        {/* Left: Primary Playback Controls */}
        <div className="flex items-center space-x-1.5">
          {/* START or RESUME button */}
          {status === "PAUSED" ? (
            <button
              data-testid="sim-resume-btn"
              onClick={onResume}
              disabled={!resumeAllowed}
              title="Resume simulation playback"
              className={`flex items-center space-x-1.5 px-3 py-1 rounded font-mono font-semibold transition-all ${
                resumeAllowed
                  ? "bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 hover:border-emerald-400 shadow-sm cursor-pointer"
                  : "bg-slate-800/60 text-slate-500 border border-slate-800 cursor-not-allowed"
              }`}
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>RESUME</span>
            </button>
          ) : status === "RUNNING" ? (
            <button
              data-testid="sim-pause-btn"
              onClick={onPause}
              disabled={!pauseAllowed}
              title="Pause active simulation playback"
              className={`flex items-center space-x-1.5 px-3 py-1 rounded font-mono font-semibold transition-all ${
                pauseAllowed
                  ? "bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 hover:border-amber-400 shadow-sm cursor-pointer"
                  : "bg-slate-800/60 text-slate-500 border border-slate-800 cursor-not-allowed"
              }`}
            >
              <Pause className="w-3.5 h-3.5 fill-current" />
              <span>PAUSE</span>
            </button>
          ) : (
            <button
              data-testid="sim-start-btn"
              onClick={onStart}
              disabled={!startAllowed}
              title={
                status === "STOPPED" || status === "COMPLETED"
                  ? "Simulation has reached a terminal state. Click Reset to run again."
                  : "Start historical simulation playback"
              }
              className={`flex items-center space-x-1.5 px-3 py-1 rounded font-mono font-semibold transition-all ${
                startAllowed
                  ? "bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 hover:border-cyan-400 shadow-sm cursor-pointer"
                  : "bg-slate-800/60 text-slate-500 border border-slate-800 cursor-not-allowed opacity-60"
              }`}
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>START</span>
            </button>
          )}

          {/* STEP button (strictly enabled when PAUSED per Section 57) */}
          <button
            data-testid="sim-step-btn"
            onClick={onStep}
            disabled={!stepAllowed}
            title={
              status === "PAUSED"
                ? "Step forward by exactly 1 candle"
                : "Step is only permitted while simulation is paused"
            }
            className={`flex items-center space-x-1 px-2.5 py-1 rounded font-mono transition-all ${
              stepAllowed
                ? "bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-500/30 hover:border-sky-400 cursor-pointer"
                : "bg-slate-800/40 text-slate-600 border border-slate-800/60 cursor-not-allowed opacity-50"
            }`}
          >
            <StepForward className="w-3 h-3" />
            <span>STEP</span>
          </button>

          {/* STOP button (terminal transition) */}
          <button
            data-testid="sim-stop-btn"
            onClick={onStop}
            disabled={!stopAllowed}
            title="Stop simulation playback and finalize portfolio"
            className={`flex items-center space-x-1 px-2.5 py-1 rounded font-mono transition-all ${
              stopAllowed
                ? "bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 hover:border-rose-400 cursor-pointer"
                : "bg-slate-800/40 text-slate-600 border border-slate-800/60 cursor-not-allowed opacity-50"
            }`}
          >
            <Square className="w-3 h-3 fill-current" />
            <span>STOP</span>
          </button>

          {/* RESET button */}
          <button
            data-testid="sim-reset-btn"
            onClick={onReset}
            disabled={!resetAllowed}
            title={
              status === "RUNNING"
                ? "Cannot reset while running. Pause or stop first."
                : "Reset simulation back to bar 0"
            }
            className={`flex items-center space-x-1 px-2.5 py-1 rounded font-mono transition-all ${
              resetAllowed
                ? "bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 hover:border-slate-600 cursor-pointer"
                : "bg-slate-800/40 text-slate-600 border border-slate-800/60 cursor-not-allowed opacity-50"
            }`}
          >
            <RotateCcw className="w-3 h-3" />
            <span>RESET</span>
          </button>

          {/* Vertical Separator */}
          <div className="h-4 w-px bg-slate-800 mx-1" />

          {/* Playback Speed Multiplier Pills */}
          <div className="flex items-center space-x-1 bg-slate-900/90 border border-slate-800 p-0.5 rounded">
            <span className="text-[10px] font-mono text-slate-500 px-1.5">SPEED:</span>
            {VALID_SIMULATION_SPEEDS.map((spd) => {
              const isActive = speed === spd;
              return (
                <button
                  key={spd}
                  data-testid={`sim-speed-${spd}x`}
                  onClick={() => onSpeedChange(spd)}
                  disabled={isLoadingAction}
                  className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium transition-all ${
                    isActive
                      ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50 font-bold"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
                  }`}
                >
                  {spd}x
                </button>
              );
            })}
          </div>

          {/* Run Mode Selector: AI Agent vs Baseline Benchmark */}
          <div className="flex items-center space-x-1 bg-slate-900/90 border border-slate-800 p-0.5 rounded ml-1">
            <span className="text-[10px] font-mono text-slate-500 px-1.5">MODE:</span>
            <button
              data-testid="sim-mode-agent"
              onClick={() => onRunModeChange && onRunModeChange("AGENT")}
              disabled={isLoadingAction || isModeLocked}
              title={
                isModeLocked
                  ? "Strategy mode is determined by active simulation session"
                  : "Configure simulation to run AI Agent"
              }
              className={`flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-mono transition-all ${
                runMode === "AGENT"
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-semibold"
                  : isModeLocked
                  ? "text-slate-500 cursor-not-allowed opacity-60"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
              }`}
            >
              <Cpu className="w-2.5 h-2.5" />
              <span>AI AGENT</span>
            </button>
            <button
              data-testid="sim-mode-baseline"
              onClick={() => onRunModeChange && onRunModeChange("BASELINE")}
              disabled={isLoadingAction || isModeLocked}
              title={
                isModeLocked
                  ? "Strategy mode is determined by active simulation session"
                  : "Configure simulation to run EMA Baseline"
              }
              className={`flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-mono transition-all ${
                runMode === "BASELINE"
                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 font-semibold"
                  : isModeLocked
                  ? "text-slate-500 cursor-not-allowed opacity-60"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
              }`}
            >
              <TrendingUp className="w-2.5 h-2.5" />
              <span>EMA BASELINE</span>
            </button>
          </div>
        </div>

        {/* Right: State Badge, Clock & Step Readouts */}
        <div className="flex items-center space-x-3 text-xs font-mono">
          {/* Status Badge */}
          {getStatusBadge()}

          {/* Simulation Virtual Clock */}
          <div
            data-testid="sim-clock-display"
            className="flex items-center space-x-1 text-slate-300 bg-slate-900/60 px-2 py-0.5 rounded border border-slate-800"
            title="Current virtual simulation time"
          >
            <Clock className="w-3 h-3 text-slate-400" />
            <span className="text-[11px] font-semibold">
              {formatVirtualClock(currentTime)}
            </span>
          </div>

          {/* Candle Step Counter */}
          <div
            data-testid="sim-step-counter"
            className="flex items-center space-x-1 text-slate-400 bg-slate-900/60 px-2 py-0.5 rounded border border-slate-800"
            title="Completed candle steps / Total candles"
          >
            <Layers className="w-3 h-3 text-slate-400" />
            <span className="text-[11px]">
              Bar <span className="text-slate-200 font-semibold">{stepIndex}</span>
              {totalCandles > 0 ? ` / ${totalCandles}` : ""}
            </span>
            <span className="text-[10px] text-cyan-400 font-bold ml-1">
              ({progressPct.toFixed(1)}%)
            </span>
          </div>

          {/* In-flight Loading Indicator */}
          {isLoadingAction && (
            <div
              data-testid="sim-action-loading"
              className="flex items-center space-x-1 text-cyan-400 animate-pulse text-[11px]"
            >
              <Radio className="w-3 h-3 animate-spin" />
              <span>Syncing...</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Progress Bar Strip */}
      <div className="w-full bg-slate-800/80 rounded-full h-1 overflow-hidden">
        <div
          data-testid="sim-progress-bar"
          className="bg-gradient-to-r from-cyan-500 to-emerald-400 h-1 transition-all duration-300"
          style={{ width: `${Math.min(Math.max(progressPct, 0), 100)}%` }}
        />
      </div>

      {/* Error Notification Banner (if any transition rejected) */}
      {errorMessage && (
        <div
          data-testid="sim-error-banner"
          className="flex items-center justify-between bg-rose-950/80 border border-rose-800/80 text-rose-300 text-[11px] font-mono px-3 py-1 rounded"
        >
          <div className="flex items-center space-x-1.5">
            <AlertTriangle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />
            <span>{errorMessage}</span>
          </div>
          {onClearError && (
            <button
              onClick={onClearError}
              className="text-rose-400 hover:text-rose-200 text-xs font-bold px-1"
            >
              ✕
            </button>
          )}
        </div>
      )}
    </div>
  );
}
