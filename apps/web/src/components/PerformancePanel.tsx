"use client";

import React from "react";
import {
  TrendingUp,
  TrendingDown,
  Percent,
  DollarSign,
  BarChart3,
  ShieldAlert,
  ArrowDownRight,
  ArrowUpRight,
  PieChart,
  CheckCircle2,
  Activity,
  Layers,
} from "lucide-react";
import { SimulationPerformanceMetrics, formatINR } from "@/types";

export interface PerformancePanelProps {
  metrics?: SimulationPerformanceMetrics | null;
  status?: string;
  className?: string;
  maxHeight?: string;
}

export function PerformancePanel({
  metrics,
  status = "READY",
  className = "",
  maxHeight = "h-64",
}: PerformancePanelProps) {
  if (!metrics) {
    return (
      <div
        data-testid="performance-panel"
        className={`flex flex-col items-center justify-center py-10 bg-slate-950/80 border border-slate-800/80 rounded-lg text-slate-500 font-mono text-xs ${className} ${maxHeight}`}
      >
        <BarChart3 className="w-8 h-8 mb-2 opacity-30 text-slate-400" />
        <p className="font-sans font-medium text-slate-400">No performance data available</p>
        <p className="text-[11px] text-slate-600 mt-1">
          Performance metrics will populate as simulation executes trades and updates equity.
        </p>
      </div>
    );
  }

  const isCompleted = status === "COMPLETED";
  const netPnl = metrics.netPnl ?? 0;
  const isProfitable = netPnl > 0;
  const isNegative = netPnl < 0;
  const totalReturnPct = metrics.totalReturnPct ?? 0;
  const winRatePct = metrics.winRatePct ?? 0;
  const maxDrawdownPct = metrics.maxDrawdownPct ?? 0;
  const exposurePct = metrics.exposurePct ?? 0;

  const pf = metrics.profitFactor;
  const pfDisplay =
    pf === null || pf === undefined || isNaN(pf)
      ? "—"
      : !isFinite(pf) || pf > 99
      ? "∞"
      : pf.toFixed(2);

  const avgWin = metrics.averageWin ?? 0;
  const avgLoss = metrics.averageLoss ?? 0;
  const winLossSpread =
    avgLoss > 0 ? (avgWin / avgLoss).toFixed(2) + "x" : "—";

  return (
    <div
      data-testid="performance-panel"
      className={`flex flex-col bg-slate-950/80 border border-slate-800/80 rounded-lg overflow-hidden ${className}`}
    >
      {/* Top Header: Tracking Mode & High-level Net Return */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 bg-slate-900/90 border-b border-slate-800 text-xs select-none">
        <div className="flex items-center space-x-2">
          <BarChart3 className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-semibold text-slate-300">Authoritative Performance Metrics</span>
          <span
            className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
              isCompleted
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                : "bg-cyan-500/10 text-cyan-400 border-cyan-500/30"
            }`}
          >
            {isCompleted ? "Settled / Final" : "Real-Time Tracking"}
          </span>
        </div>

        {/* Highlight Net Return */}
        <div className="flex items-center space-x-3 font-mono">
          <div className="text-[11px] text-slate-400">
            Net Return:{" "}
            <span
              className={`font-bold ${
                isProfitable
                  ? "text-emerald-400"
                  : isNegative
                  ? "text-rose-400"
                  : "text-slate-300"
              }`}
            >
              {totalReturnPct >= 0 ? "+" : ""}
              {totalReturnPct.toFixed(2)}%
            </span>
          </div>
          <div className="text-[11px] text-slate-400">
            Net P&L:{" "}
            <span
              className={`font-bold ${
                isProfitable
                  ? "text-emerald-400"
                  : isNegative
                  ? "text-rose-400"
                  : "text-slate-300"
              }`}
            >
              {formatINR(netPnl, true)}
            </span>
          </div>
        </div>
      </div>


      {/* Grid of Metric Cards */}
      <div
        className={`p-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 overflow-y-auto font-mono text-xs ${maxHeight}`}
      >
        {/* Card 1: Capital & Returns */}
        <div className="p-2.5 rounded bg-slate-900/50 border border-slate-800/80 space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-[11px] font-sans font-medium border-b border-slate-800 pb-1">
            <span>CAPITAL & EQUITY</span>
            <DollarSign className="w-3.5 h-3.5 text-cyan-400" />
          </div>
          <div className="space-y-1.5 text-[11px]">
            <div className="flex justify-between">
              <span className="text-slate-500">Initial Capital</span>
              <span className="text-slate-200">{formatINR(metrics.initialCapital)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Current Equity</span>
              <span className="text-slate-200 font-semibold">
                {formatINR(metrics.finalPortfolioValue)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Gross P&L</span>
              <span
                className={
                  metrics.grossPnl > 0
                    ? "text-emerald-400"
                    : metrics.grossPnl < 0
                    ? "text-rose-400"
                    : "text-slate-400"
                }
              >
                {formatINR(metrics.grossPnl, true)}
              </span>
            </div>
            <div className="flex justify-between font-semibold">
              <span className="text-slate-400">Net P&L</span>
              <span
                className={
                  metrics.netPnl > 0
                    ? "text-emerald-400"
                    : metrics.netPnl < 0
                    ? "text-rose-400"
                    : "text-slate-400"
                }
              >
                {formatINR(metrics.netPnl, true)}
              </span>
            </div>
          </div>
        </div>

        {/* Card 2: Trade Performance */}
        <div className="p-2.5 rounded bg-slate-900/50 border border-slate-800/80 space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-[11px] font-sans font-medium border-b border-slate-800 pb-1">
            <span>TRADE PERFORMANCE</span>
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="space-y-1.5 text-[11px]">
            <div className="flex justify-between">
              <span className="text-slate-500">Total Trades</span>
              <span className="text-slate-200 font-semibold">{metrics.totalTrades}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Wins / Losses</span>
              <span className="text-slate-200">
                <span className="text-emerald-400 font-medium">
                  {metrics.winningTrades}W
                </span>{" "}
                /{" "}
                <span className="text-rose-400 font-medium">
                  {metrics.losingTrades}L
                </span>
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Win Rate</span>
              <span
                className={`font-semibold ${
                  winRatePct >= 50
                    ? "text-emerald-400"
                    : (metrics.totalTrades || 0) > 0
                    ? "text-amber-400"
                    : "text-slate-400"
                }`}
              >
                {winRatePct.toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Profit Factor</span>
              <span
                className={`font-semibold ${
                  pf !== null && pf !== undefined && pf >= 1.5
                    ? "text-emerald-400"
                    : pf !== null && pf !== undefined && pf >= 1.0
                    ? "text-amber-400"
                    : "text-rose-400"
                }`}
              >
                {pfDisplay}
              </span>
            </div>
          </div>
        </div>

        {/* Card 3: Expectancy & Averages */}
        <div className="p-2.5 rounded bg-slate-900/50 border border-slate-800/80 space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-[11px] font-sans font-medium border-b border-slate-800 pb-1">
            <span>TRADE EXPECTANCY</span>
            <PieChart className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <div className="space-y-1.5 text-[11px]">
            <div className="flex justify-between">
              <span className="text-slate-500">Average Win</span>
              <span className="text-emerald-400">
                {avgWin > 0 ? `+${formatINR(avgWin)}` : "₹0.00"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Average Loss</span>
              <span className="text-rose-400">
                {avgLoss > 0 ? `-${formatINR(avgLoss)}` : "₹0.00"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Open Positions</span>
              <span className="text-slate-200">{metrics.openPositionsCount || 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Win/Loss Spread</span>
              <span className="text-slate-300">{winLossSpread}</span>
            </div>
          </div>
        </div>

        {/* Card 4: Risk & Friction Costs */}
        <div className="p-2.5 rounded bg-slate-900/50 border border-slate-800/80 space-y-2">
          <div className="flex items-center justify-between text-slate-400 text-[11px] font-sans font-medium border-b border-slate-800 pb-1">
            <span>RISK & COSTS</span>
            <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
          </div>
          <div className="space-y-1.5 text-[11px]">
            <div className="flex justify-between">
              <span className="text-slate-500">Max Drawdown</span>
              <span className="text-rose-400 font-semibold">
                {maxDrawdownPct.toFixed(2)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Portfolio Exposure</span>
              <span className="text-slate-300">{exposurePct.toFixed(1)}%</span>
            </div>

            <div className="flex justify-between">
              <span className="text-slate-500">Transaction Costs</span>
              <span className="text-slate-400">{formatINR(metrics.transactionCosts)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Slippage Impact</span>
              <span className="text-slate-400">{formatINR(metrics.slippageCost)}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
