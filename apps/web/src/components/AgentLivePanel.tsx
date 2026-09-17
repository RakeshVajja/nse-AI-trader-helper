"use client";

import React from "react";
import {
  Bot,
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  CheckCircle2,
  AlertCircle,
  Activity,
  Gauge,
  HelpCircle,
  ShieldAlert,
  Clock,
  Briefcase,
  Crosshair,
  Target,
  Percent,
} from "lucide-react";
import { AgentLivePanelState } from "@/types";

export interface AgentLivePanelProps {
  state: AgentLivePanelState;
  className?: string;
}

export function AgentLivePanel({ state, className = "" }: AgentLivePanelProps) {
  const {
    agentName,
    strategyStyle,
    status,
    regime,
    latestDecision,
    activePosition,
    portfolio,
    errorMessage,
    lastUpdated,
  } = state;

  // ---------------------------------------------------------------------------
  // Status Badge Rendering
  // ---------------------------------------------------------------------------
  const renderStatusBadge = () => {
    switch (status) {
      case "ANALYZING":
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-amber-500/15 border border-amber-500/30 text-amber-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping" />
            <span>ANALYZING</span>
          </span>
        );
      case "RUNNING":
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span>ACTIVE</span>
          </span>
        );
      case "PAUSED":
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-yellow-500/15 border border-yellow-500/30 text-yellow-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
            <span>PAUSED</span>
          </span>
        );
      case "ERROR":
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-rose-500/15 border border-rose-500/30 text-rose-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <AlertCircle className="w-2.5 h-2.5 text-rose-400" />
            <span>ERROR</span>
          </span>
        );
      case "COMPLETED":
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-purple-500/15 border border-purple-500/30 text-purple-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
            <span>COMPLETED</span>
          </span>
        );
      case "WAITING":
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-blue-500/15 border border-blue-500/30 text-blue-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            <span>WAITING</span>
          </span>
        );
      case "READY":
      default:
        return (
          <span
            data-testid="agent-status-badge"
            className="flex items-center space-x-1 bg-slate-700/30 border border-slate-600/40 text-slate-300 px-2 py-0.5 rounded text-[10px] font-mono font-semibold"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            <span>READY</span>
          </span>
        );
    }
  };

  // ---------------------------------------------------------------------------
  // Market Regime Badge Rendering
  // ---------------------------------------------------------------------------
  const getTrendStyle = (t?: string | null) => {
    switch (t) {
      case "BULLISH":
        return {
          bg: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
          icon: <TrendingUp className="w-3 h-3 text-emerald-400" />,
          label: "BULLISH",
        };
      case "BEARISH":
        return {
          bg: "bg-rose-500/10 border-rose-500/30 text-rose-400",
          icon: <TrendingDown className="w-3 h-3 text-rose-400" />,
          label: "BEARISH",
        };
      case "SIDEWAYS":
        return {
          bg: "bg-amber-500/10 border-amber-500/30 text-amber-300",
          icon: <Activity className="w-3 h-3 text-amber-400" />,
          label: "SIDEWAYS",
        };
      default:
        return {
          bg: "bg-slate-800/40 border-slate-700/50 text-slate-400",
          icon: <HelpCircle className="w-3 h-3 text-slate-400" />,
          label: "WARMUP / N/A",
        };
    }
  };

  const getVolStyle = (v?: string | null) => {
    switch (v) {
      case "HIGH":
        return {
          bg: "bg-rose-500/15 border-rose-500/30 text-rose-300",
          icon: <AlertCircle className="w-3 h-3 text-rose-400" />,
          label: "HIGH",
        };
      case "NORMAL":
        return {
          bg: "bg-cyan-500/10 border-cyan-500/30 text-cyan-300",
          icon: <Gauge className="w-3 h-3 text-cyan-400" />,
          label: "NORMAL",
        };
      case "LOW":
        return {
          bg: "bg-slate-700/20 border-slate-600/30 text-slate-300",
          icon: <Activity className="w-3 h-3 text-slate-400" />,
          label: "LOW",
        };
      default:
        return {
          bg: "bg-slate-800/40 border-slate-700/50 text-slate-400",
          icon: <HelpCircle className="w-3 h-3 text-slate-400" />,
          label: "WARMUP / N/A",
        };
    }
  };

  const trendStyle = getTrendStyle(regime?.trend);
  const volStyle = getVolStyle(regime?.volatility);

  // ---------------------------------------------------------------------------
  // Signal & Confidence Formatting
  // ---------------------------------------------------------------------------
  const action = latestDecision?.action;
  const confidencePct =
    latestDecision && typeof latestDecision.confidence === "number"
      ? Math.round(
          latestDecision.confidence <= 1.0
            ? latestDecision.confidence * 100
            : latestDecision.confidence
        )
      : null;

  const renderSignalBadge = () => {
    if (!action) {
      return (
        <span
          data-testid="signal-pill"
          className="bg-slate-800/60 border border-slate-700 text-slate-400 px-2.5 py-1 rounded text-xs font-mono font-semibold"
        >
          WAITING FOR SIGNAL
        </span>
      );
    }
    switch (action) {
      case "BUY":
        return (
          <span
            data-testid="signal-pill"
            className="flex items-center space-x-1.5 bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 px-2.5 py-1 rounded text-xs font-mono font-bold tracking-wider"
          >
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
            <span>BUY</span>
          </span>
        );
      case "SELL":
        return (
          <span
            data-testid="signal-pill"
            className="flex items-center space-x-1.5 bg-rose-500/20 border border-rose-500/40 text-rose-300 px-2.5 py-1 rounded text-xs font-mono font-bold tracking-wider"
          >
            <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
            <span>SELL</span>
          </span>
        );
      case "HOLD":
      default:
        return (
          <span
            data-testid="signal-pill"
            className="flex items-center space-x-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-300 px-2.5 py-1 rounded text-xs font-mono font-bold tracking-wider"
          >
            <Minus className="w-3.5 h-3.5 text-amber-400" />
            <span>HOLD</span>
          </span>
        );
    }
  };

  // ---------------------------------------------------------------------------
  // Observations Rendering Helper
  // ---------------------------------------------------------------------------
  const renderObservationItem = (obs: string, index: number) => {
    const trimmed = obs.trim();
    let icon = <span className="text-cyan-400 text-xs font-bold leading-none">•</span>;

    if (
      trimmed.startsWith("✓") ||
      trimmed.startsWith("✔") ||
      trimmed.toLowerCase().includes("passed") ||
      trimmed.toLowerCase().includes("positive")
    ) {
      icon = <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0 mt-0.5" />;
    } else if (
      trimmed.startsWith("⚠") ||
      trimmed.startsWith("!") ||
      trimmed.toLowerCase().includes("elevated") ||
      trimmed.toLowerCase().includes("caution")
    ) {
      icon = <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0 mt-0.5" />;
    } else if (
      trimmed.startsWith("✗") ||
      trimmed.startsWith("✕") ||
      trimmed.toLowerCase().includes("fail") ||
      trimmed.toLowerCase().includes("negative")
    ) {
      icon = <AlertCircle className="w-3 h-3 text-rose-400 shrink-0 mt-0.5" />;
    }

    return (
      <li
        key={index}
        className="flex items-start space-x-2 text-[11px] font-mono text-slate-300 leading-relaxed"
      >
        {icon}
        <span className="flex-1 break-words">{trimmed}</span>
      </li>
    );
  };

  // ---------------------------------------------------------------------------
  // Position Calculations & Formatting
  // ---------------------------------------------------------------------------
  const hasOpenPosition = Boolean(
    activePosition && activePosition.isOpen && activePosition.quantity > 0
  );
  const pnlIsPositive = (activePosition?.unrealizedPnl ?? 0) >= 0;

  const formatPrice = (price?: number | null) => {
    if (price === null || price === undefined) return "—";
    return `₹${price.toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  };

  return (
    <div
      data-testid="agent-live-panel"
      className={`bg-[#0e1420] border border-[#1e293b] rounded-lg p-3.5 space-y-3 font-mono ${className}`}
    >
      {/* 1. Header: Agent Identity & Status */}
      <div className="flex items-center justify-between border-b border-[#1e293b] pb-2.5">
        <div className="flex items-center space-x-2 min-w-0">
          <div className="w-7 h-7 rounded bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 shrink-0">
            <Bot className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3
              data-testid="agent-name"
              className="text-xs font-semibold text-slate-100 truncate"
              title={agentName}
            >
              {agentName}
            </h3>
            <div className="flex items-center space-x-1 text-[10px] text-slate-400">
              <span className="text-emerald-400 font-medium uppercase">
                {strategyStyle || "QUANT"}
              </span>
              <span>•</span>
              <span className="truncate">AUTONOMOUS</span>
            </div>
          </div>
        </div>
        <div>{renderStatusBadge()}</div>
      </div>

      {/* Error Alert Banner (if error state active) */}
      {errorMessage && (
        <div
          data-testid="agent-error-banner"
          className="bg-rose-500/10 border border-rose-500/30 rounded p-2 text-rose-300 text-[11px] flex items-start space-x-2"
        >
          <ShieldAlert className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
          <span className="break-words">{errorMessage}</span>
        </div>
      )}

      {/* 2. Market Regime Section */}
      <div className="bg-[#131a27] p-2.5 rounded border border-[#1e293b]/70 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold text-slate-400 tracking-wider">
            MARKET REGIME
          </span>
          <span className="text-[9px] text-slate-500">AUTHORITATIVE</span>
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          {/* Trend */}
          <div
            data-testid="regime-trend-badge"
            className={`flex items-center justify-between px-2 py-1 rounded border ${trendStyle.bg}`}
          >
            <div className="flex items-center space-x-1.5 min-w-0">
              {trendStyle.icon}
              <span className="truncate font-semibold text-[10px]">{trendStyle.label}</span>
            </div>
          </div>

          {/* Volatility */}
          <div
            data-testid="regime-volatility-badge"
            className={`flex items-center justify-between px-2 py-1 rounded border ${volStyle.bg}`}
          >
            <div className="flex items-center space-x-1.5 min-w-0">
              {volStyle.icon}
              <span className="truncate font-semibold text-[10px]">{volStyle.label}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Current Decision Signal & Confidence Meter */}
      <div className="bg-[#131a27] p-2.5 rounded border border-[#1e293b]/70 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold text-slate-400 tracking-wider">
            CURRENT SIGNAL
          </span>
          {lastUpdated && (
            <div className="flex items-center space-x-1 text-[10px] text-slate-500">
              <Clock className="w-3 h-3 text-slate-500" />
              <span data-testid="decision-timestamp" className="truncate">
                {lastUpdated.includes("T")
                  ? lastUpdated.split("T")[1]?.slice(0, 8) || lastUpdated
                  : lastUpdated}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between">
          <div>{renderSignalBadge()}</div>
          <div className="text-right">
            <span className="text-[10px] text-slate-400 mr-1.5">CONFIDENCE:</span>
            <span
              data-testid="confidence-value"
              className="text-xs font-bold text-slate-100"
            >
              {confidencePct !== null ? `${confidencePct}%` : "—"}
            </span>
          </div>
        </div>

        {/* Confidence Meter Bar */}
        <div className="w-full bg-[#0a0d14] rounded-full h-1.5 overflow-hidden border border-[#1e293b]">
          <div
            data-testid="confidence-bar"
            className={`h-full transition-all duration-300 ${
              action === "BUY"
                ? "bg-emerald-500"
                : action === "SELL"
                  ? "bg-rose-500"
                  : "bg-amber-500"
            }`}
            style={{ width: `${confidencePct ?? 0}%` }}
          />
        </div>
      </div>

      {/* 4. Concise Observations & Decision Rationale */}
      <div className="bg-[#131a27] p-2.5 rounded border border-[#1e293b]/70 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-semibold text-slate-400 tracking-wider">
            OBSERVATIONS & RATIONALE
          </span>
          <span className="text-[9px] text-slate-500">SANITIZED</span>
        </div>

        {latestDecision &&
        ((latestDecision.observations && latestDecision.observations.length > 0) ||
          latestDecision.reason) ? (
          <ul data-testid="observations-list" className="space-y-1.5 pt-0.5">
            {latestDecision.observations && latestDecision.observations.length > 0
              ? latestDecision.observations.map((obs, idx) => renderObservationItem(obs, idx))
              : renderObservationItem(latestDecision.reason, 0)}
          </ul>
        ) : (
          <div className="text-[11px] text-slate-500 italic py-1">
            Awaiting first evaluation cycle...
          </div>
        )}
      </div>

      {/* 5. Authoritative Executed Position & Live SL/TP */}
      <div className="bg-[#131a27] p-2.5 rounded border border-[#1e293b]/70 space-y-2">
        <div className="flex items-center justify-between border-b border-[#1e293b] pb-1.5">
          <div className="flex items-center space-x-1.5">
            <Briefcase className="w-3 h-3 text-cyan-400" />
            <span className="text-[10px] font-semibold text-slate-300 tracking-wider">
              PORTFOLIO POSITION (EXECUTED)
            </span>
          </div>
          {hasOpenPosition ? (
            <span
              data-testid="position-status-badge"
              className="text-[9px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 px-1.5 py-0.2 rounded font-semibold"
            >
              OPEN
            </span>
          ) : (
            <span
              data-testid="position-status-badge"
              className="text-[9px] bg-slate-800 text-slate-400 border border-slate-700 px-1.5 py-0.2 rounded"
            >
              FLAT
            </span>
          )}
        </div>

        {hasOpenPosition && activePosition ? (
          <div data-testid="active-position-details" className="space-y-2 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">SYMBOL & QTY:</span>
              <span className="text-slate-100 font-semibold">
                {activePosition.symbol} • {activePosition.quantity} QTY
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="bg-[#0e1420] p-1.5 rounded border border-[#1e293b]/60">
                <div className="text-[9px] text-slate-400">ENTRY PRICE</div>
                <div data-testid="entry-price" className="text-slate-200 font-semibold">
                  {formatPrice(activePosition.averageEntryPrice)}
                </div>
              </div>
              <div className="bg-[#0e1420] p-1.5 rounded border border-[#1e293b]/60">
                <div className="text-[9px] text-slate-400">CURRENT PRICE</div>
                <div data-testid="current-price" className="text-slate-200 font-semibold">
                  {formatPrice(activePosition.currentPrice)}
                </div>
              </div>
            </div>

            {/* Live SL & TP */}
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="bg-[#0e1420] p-1.5 rounded border border-[#1e293b]/60">
                <div className="flex items-center space-x-1 text-[9px] text-rose-400">
                  <Crosshair className="w-2.5 h-2.5" />
                  <span>STOP LOSS</span>
                </div>
                <div data-testid="live-stop-loss" className="text-rose-300 font-semibold">
                  {formatPrice(activePosition.stopLoss)}
                </div>
              </div>
              <div className="bg-[#0e1420] p-1.5 rounded border border-[#1e293b]/60">
                <div className="flex items-center space-x-1 text-[9px] text-emerald-400">
                  <Target className="w-2.5 h-2.5" />
                  <span>TAKE PROFIT</span>
                </div>
                <div data-testid="live-take-profit" className="text-emerald-300 font-semibold">
                  {formatPrice(activePosition.takeProfit)}
                </div>
              </div>
            </div>

            {/* Unrealized P&L */}
            <div className="flex items-center justify-between pt-0.5 border-t border-[#1e293b]/60">
              <span className="text-slate-400">UNREALIZED P&L:</span>
              <span
                data-testid="unrealized-pnl"
                className={`font-bold ${
                  pnlIsPositive ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {pnlIsPositive ? "+" : ""}
                {formatPrice(activePosition.unrealizedPnl)}
              </span>
            </div>
          </div>
        ) : (
          <div
            data-testid="flat-position-details"
            className="text-[11px] text-slate-400 space-y-1.5 py-1"
          >
            <div className="flex items-center justify-between">
              <span>ACTIVE POSITION:</span>
              <span className="text-slate-300 font-semibold">NONE (FLAT)</span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[10px]">
              <div className="bg-[#0e1420] p-1.5 rounded border border-[#1e293b]/50 flex justify-between">
                <span className="text-slate-500">STOP LOSS</span>
                <span data-testid="live-stop-loss" className="text-slate-400">
                  —
                </span>
              </div>
              <div className="bg-[#0e1420] p-1.5 rounded border border-[#1e293b]/50 flex justify-between">
                <span className="text-slate-500">TAKE PROFIT</span>
                <span data-testid="live-take-profit" className="text-slate-400">
                  —
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 6. Portfolio P&L Summary (if available) */}
      {portfolio && (
        <div className="border-t border-[#1e293b] pt-2 flex items-center justify-between text-[10px] text-slate-400">
          <div>
            PORTFOLIO:{" "}
            <span className="text-slate-200 font-semibold">
              {formatPrice(portfolio.portfolioValue)}
            </span>
          </div>
          <div>
            NET P&L:{" "}
            <span
              className={`font-semibold ${
                portfolio.netPnl >= 0 ? "text-emerald-400" : "text-rose-400"
              }`}
            >
              {portfolio.netPnl >= 0 ? "+" : ""}
              {formatPrice(portfolio.netPnl)} ({portfolio.totalReturnPct.toFixed(2)}%)
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
