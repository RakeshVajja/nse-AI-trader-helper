"use client";

import React, { useMemo } from "react";
import {
  TrendingUp,
  TrendingDown,
  Receipt,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  Clock,
} from "lucide-react";
import {
  SimulationPerformanceMetrics,
  TradeLogEntry,
  formatINR,
  formatTimeDisplay,
} from "@/types";

export interface TradeLogProps {
  trades: TradeLogEntry[];
  metrics?: SimulationPerformanceMetrics | null;
  className?: string;
  maxHeight?: string;
}

export function TradeLog({
  trades,
  metrics,
  className = "",
  maxHeight = "h-64",
}: TradeLogProps) {
  // Aggregate statistics for the trade summary header, prioritizing authoritative backend metrics
  const summary = useMemo(() => {
    if (metrics) {
      return {
        totalFills: trades.length,
        closedCount: metrics.totalTrades,
        winCount: metrics.winningTrades,
        lossCount: metrics.losingTrades,
        totalRealizedNetPnl: metrics.netPnl,
        totalCosts: (metrics.transactionCosts || 0) + (metrics.slippageCost || 0),
      };
    }

    let closedCount = 0;
    let winCount = 0;
    let lossCount = 0;
    let totalRealizedNetPnl = 0;
    let totalCosts = 0;

    for (const t of trades) {
      totalCosts += (t.transactionCost || 0) + (t.slippageCost || 0);
      if (t.isClosed && t.netPnl !== null && t.netPnl !== undefined) {
        closedCount++;
        totalRealizedNetPnl += t.netPnl;
        if (t.netPnl > 0) winCount++;
        else if (t.netPnl < 0) lossCount++;
      }
    }

    return {
      totalFills: trades.length,
      closedCount,
      winCount,
      lossCount,
      totalRealizedNetPnl,
      totalCosts,
    };
  }, [trades, metrics]);


  return (
    <div
      data-testid="trade-log"
      className={`flex flex-col bg-slate-950/80 border border-slate-800/80 rounded-lg overflow-hidden ${className}`}
    >
      {/* Execution Integrity Header / Demarcation notice */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 bg-slate-900/90 border-b border-slate-800 text-xs select-none">
        <div className="flex items-center space-x-2">
          <Receipt className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-semibold text-slate-300">Authoritative Executed Trades</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
            Fills Only (No Unfilled Signals)
          </span>
        </div>

        {/* Quick summary stats */}
        <div className="flex items-center space-x-4 font-mono text-[11px] text-slate-400">
          <div>
            Total Fills:{" "}
            <span className="text-slate-200 font-semibold">{summary.totalFills}</span>
          </div>
          <div>
            Closed:{" "}
            <span className="text-slate-200 font-semibold">{summary.closedCount}</span>{" "}
            <span className="text-[10px] text-slate-500">
              ({summary.winCount}W / {summary.lossCount}L)
            </span>
          </div>
          <div>
            Realized P&L:{" "}
            <span
              className={`font-semibold ${
                summary.totalRealizedNetPnl > 0
                  ? "text-emerald-400"
                  : summary.totalRealizedNetPnl < 0
                  ? "text-rose-400"
                  : "text-slate-300"
              }`}
            >
              {formatINR(summary.totalRealizedNetPnl, true)}
            </span>
          </div>
        </div>
      </div>

      {/* Trade Log Table */}
      <div className={`overflow-y-auto overflow-x-auto font-mono text-xs ${maxHeight}`}>
        {trades.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-slate-500 text-xs">
            <Receipt className="w-7 h-7 mb-2 opacity-30 text-slate-400" />
            <p className="font-sans font-medium text-slate-400">No trades executed yet</p>
            <p className="text-[11px] text-slate-600 mt-1">
              Authoritative order fills from the simulation will appear here.
            </p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse min-w-[700px]">
            <thead className="sticky top-0 bg-slate-900/95 text-[10px] text-slate-400 border-b border-slate-800 select-none z-10">
              <tr>
                <th className="py-2 px-3 font-semibold">TIME</th>
                <th className="py-2 px-3 font-semibold">SYMBOL</th>
                <th className="py-2 px-3 font-semibold">SIDE</th>
                <th className="py-2 px-3 font-semibold text-right">QTY</th>
                <th className="py-2 px-3 font-semibold text-right">FILL PRICE</th>
                <th className="py-2 px-3 font-semibold text-right">EXIT PRICE</th>
                <th className="py-2 px-3 font-semibold text-right">NET P&L</th>
                <th className="py-2 px-3 font-semibold text-right">COSTS</th>
                <th className="py-2 px-3 font-semibold text-center">STATUS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {trades.map((trade) => {
                const isBuy = trade.side === "BUY";
                const isProfitable = (trade.netPnl ?? 0) > 0;
                const isLoss = (trade.netPnl ?? 0) < 0;

                return (
                  <tr
                    key={trade.id}
                    data-testid="trade-log-entry"
                    className="hover:bg-slate-900/60 transition-colors"
                  >
                    {/* Timestamp */}
                    <td className="py-2 px-3 text-slate-400 text-[11px] whitespace-nowrap">
                      {formatTimeDisplay(trade.timestamp)}
                    </td>

                    {/* Symbol */}
                    <td className="py-2 px-3 font-semibold text-slate-200">
                      {trade.symbol}
                    </td>

                    {/* Side Badge */}
                    <td className="py-2 px-3">
                      <span
                        className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          isBuy
                            ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                            : "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                        }`}
                      >
                        {trade.side}
                      </span>
                    </td>

                    {/* Quantity */}
                    <td className="py-2 px-3 text-right text-slate-200">
                      {trade.quantity.toLocaleString()}
                    </td>

                    {/* Fill Price */}
                    <td className="py-2 px-3 text-right text-slate-200">
                      {formatINR(trade.executionPrice)}
                    </td>

                    {/* Exit Price */}
                    <td className="py-2 px-3 text-right text-slate-400">
                      {trade.exitPrice !== null && trade.exitPrice !== undefined
                        ? formatINR(trade.exitPrice)
                        : "—"}
                    </td>

                    {/* Net P&L */}
                    <td
                      className={`py-2 px-3 text-right font-semibold ${
                        isProfitable
                          ? "text-emerald-400"
                          : isLoss
                          ? "text-rose-400"
                          : "text-slate-400"
                      }`}
                    >
                      {trade.netPnl !== null && trade.netPnl !== undefined
                        ? formatINR(trade.netPnl, true)
                        : "—"}
                    </td>

                    {/* Transaction & Slippage Costs */}
                    <td className="py-2 px-3 text-right text-slate-500 text-[11px]">
                      {formatINR(trade.transactionCost + trade.slippageCost)}
                    </td>

                    {/* Status Badge */}
                    <td className="py-2 px-3 text-center whitespace-nowrap">
                      {trade.isAutoExit ? (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
                          SL/TP EXIT
                        </span>
                      ) : trade.isClosed ? (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                          CLOSED
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                          FILLED
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
