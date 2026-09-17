"use client";

import React, { useState } from "react";
import {
  Activity,
  Receipt,
  BarChart3,
  ChevronDown,
  ChevronUp,
  Maximize2,
  Minimize2,
} from "lucide-react";
import {
  ActivityItem,
  BottomTerminalTab,
  SimulationPerformanceMetrics,
  TradeLogEntry,
  formatINR,
} from "@/types";
import { ActivityFeed } from "./ActivityFeed";
import { TradeLog } from "./TradeLog";
import { PerformancePanel } from "./PerformancePanel";

export interface BottomTerminalWorkspaceProps {
  activeTab: BottomTerminalTab;
  onTabChange: (tab: BottomTerminalTab) => void;
  activityItems: ActivityItem[];
  trades: TradeLogEntry[];
  metrics?: SimulationPerformanceMetrics | null;
  simulationStatus?: string;
  className?: string;
  defaultExpanded?: boolean;
}

export function BottomTerminalWorkspace({
  activeTab,
  onTabChange,
  activityItems,
  trades,
  metrics,
  simulationStatus = "READY",
  className = "",
  defaultExpanded = true,
}: BottomTerminalWorkspaceProps) {
  const [isExpanded, setIsExpanded] = useState<boolean>(defaultExpanded);

  return (
    <div
      data-testid="bottom-terminal-workspace"
      className={`flex flex-col bg-slate-900 border border-slate-800 rounded-lg shadow-xl overflow-hidden transition-all duration-200 ${className}`}
    >
      {/* Workspace Header & Tab Bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-950/90 border-b border-slate-800 select-none">
        {/* Navigation Tabs */}
        <div className="flex items-center space-x-1">
          {/* Tab 1: Agent Activity */}
          <button
            data-testid="tab-activity"
            onClick={() => {
              onTabChange("activity");
              if (!isExpanded) setIsExpanded(true);
            }}
            className={`flex items-center space-x-1.5 px-3 py-1 text-xs font-mono rounded transition-colors ${
              activeTab === "activity"
                ? "bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            <span>Agent Activity</span>
            {activityItems.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-800 text-cyan-400 font-semibold border border-slate-700">
                {activityItems.length}
              </span>
            )}
          </button>

          {/* Tab 2: Trade Log */}
          <button
            data-testid="tab-trades"
            onClick={() => {
              onTabChange("trades");
              if (!isExpanded) setIsExpanded(true);
            }}
            className={`flex items-center space-x-1.5 px-3 py-1 text-xs font-mono rounded transition-colors ${
              activeTab === "trades"
                ? "bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <Receipt className="w-3.5 h-3.5" />
            <span>Trade Log</span>
            {trades.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-800 text-emerald-400 font-semibold border border-slate-700">
                {trades.length}
              </span>
            )}
          </button>

          {/* Tab 3: Performance */}
          <button
            data-testid="tab-performance"
            onClick={() => {
              onTabChange("performance");
              if (!isExpanded) setIsExpanded(true);
            }}
            className={`flex items-center space-x-1.5 px-3 py-1 text-xs font-mono rounded transition-colors ${
              activeTab === "performance"
                ? "bg-cyan-500/20 text-cyan-300 font-semibold border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Performance</span>
            {metrics && (
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded-full font-semibold ${
                  metrics.netPnl >= 0
                    ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                    : "bg-rose-500/10 text-rose-400 border border-rose-500/30"
                }`}
              >
                {metrics.totalReturnPct >= 0 ? "+" : ""}
                {metrics.totalReturnPct.toFixed(1)}%
              </span>
            )}
          </button>
        </div>

        {/* Right side: Quick stats summary & Collapse toggle */}
        <div className="flex items-center space-x-3 text-xs">
          {metrics && (
            <div className="hidden sm:flex items-center space-x-3 font-mono text-[11px] text-slate-400 mr-1">
              <span>
                Equity:{" "}
                <span className="text-slate-200 font-medium">
                  {formatINR(metrics.finalPortfolioValue)}
                </span>
              </span>
              <span>
                Net P&L:{" "}
                <span
                  className={`font-semibold ${
                    metrics.netPnl > 0
                      ? "text-emerald-400"
                      : metrics.netPnl < 0
                      ? "text-rose-400"
                      : "text-slate-300"
                  }`}
                >
                  {formatINR(metrics.netPnl, true)}
                </span>
              </span>
            </div>
          )}

          {/* Collapse/Expand Toggle Button */}
          <button
            data-testid="workspace-toggle-collapse"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? "Collapse Panel" : "Expand Panel"}
            className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            {isExpanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronUp className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Active Tab View Body */}
      {isExpanded && (
        <div className="p-2 bg-slate-950/60">
          {activeTab === "activity" && (
            <ActivityFeed items={activityItems} maxHeight="max-h-60 min-h-[220px]" />
          )}
          {activeTab === "trades" && (
            <TradeLog
              trades={trades}
              metrics={metrics}
              maxHeight="max-h-60 min-h-[220px]"
            />
          )}

          {activeTab === "performance" && (
            <PerformancePanel
              metrics={metrics}
              status={simulationStatus}
              maxHeight="max-h-60 min-h-[220px]"
            />
          )}
        </div>
      )}
    </div>
  );
}
