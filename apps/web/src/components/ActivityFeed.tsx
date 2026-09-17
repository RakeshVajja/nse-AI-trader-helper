"use client";

import React, { useState, useMemo, useRef, useEffect } from "react";
import {
  Activity,
  ArrowDownUp,
  Bot,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Zap,
  ShieldAlert,
  Clock,
  Filter,
} from "lucide-react";
import { ActivityCategory, ActivityItem, formatTimeDisplay } from "@/types";

export interface ActivityFeedProps {
  items: ActivityItem[];
  className?: string;
  maxHeight?: string;
}

type FilterCategory = "ALL" | "SIGNAL" | "ORDER" | "RISK" | "SYSTEM";

export function ActivityFeed({
  items,
  className = "",
  maxHeight = "h-64",
}: ActivityFeedProps) {
  const [activeFilter, setActiveFilter] = useState<FilterCategory>("ALL");
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const filteredItems = useMemo(() => {
    if (activeFilter === "ALL") return items;
    if (activeFilter === "SYSTEM") {
      return items.filter(
        (it) => it.category === "SYSTEM" || it.category === "ANALYSIS"
      );
    }
    return items.filter((it) => it.category === activeFilter);
  }, [items, activeFilter]);

  // Handle auto-scroll to latest item
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filteredItems, autoScroll]);

  const getSeverityBadge = (item: ActivityItem) => {
    switch (item.severity) {
      case "success":
        return (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            {item.category}
          </span>
        );
      case "warning":
        return (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
            {item.category}
          </span>
        );
      case "error":
        return (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
            {item.category}
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            {item.category}
          </span>
        );
    }
  };

  const getEventIcon = (item: ActivityItem) => {
    switch (item.category) {
      case "SIGNAL":
        return <Zap className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />;
      case "ORDER":
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />;
      case "RISK":
        return <ShieldAlert className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />;
      case "PORTFOLIO":
        return <Activity className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />;
      case "ANALYSIS":
        return <Bot className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />;
      default:
        if (item.severity === "error") {
          return <AlertCircle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />;
        }
        return <Clock className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />;
    }
  };

  return (
    <div
      data-testid="activity-feed"
      className={`flex flex-col bg-slate-950/80 border border-slate-800/80 rounded-lg overflow-hidden ${className}`}
    >
      {/* Control Bar: Filters & Auto-scroll Toggle */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-900/90 border-b border-slate-800 text-xs select-none">
        <div className="flex items-center space-x-1">
          <Filter className="w-3 h-3 text-slate-400 mr-1" />
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mr-2">
            Filter:
          </span>
          {(
            [
              { id: "ALL", label: "All" },
              { id: "SIGNAL", label: "Signals" },
              { id: "ORDER", label: "Orders" },
              { id: "RISK", label: "Risk" },
              { id: "SYSTEM", label: "System" },
            ] as const
          ).map((filter) => {
            const isSelected = activeFilter === filter.id;
            return (
              <button
                key={filter.id}
                data-testid={`activity-filter-${filter.id.toLowerCase()}`}
                onClick={() => setActiveFilter(filter.id)}
                className={`px-2 py-0.5 text-[10px] font-mono rounded transition-colors ${
                  isSelected
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 font-semibold"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                }`}
              >
                {filter.label}
              </button>
            );
          })}
        </div>

        <div className="flex items-center space-x-3 text-slate-400">
          <label className="flex items-center space-x-1 cursor-pointer hover:text-slate-200 text-[11px] font-mono">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0 focus:ring-offset-0 w-3 h-3 cursor-pointer"
            />
            <span>Auto-scroll</span>
          </label>
          <span className="text-[10px] font-mono text-slate-500">
            {filteredItems.length} / {items.length} events
          </span>
        </div>
      </div>

      {/* Activity Items List */}
      <div
        ref={scrollRef}
        className={`overflow-y-auto divide-y divide-slate-800/50 p-2 space-y-1 font-mono ${maxHeight}`}
      >
        {filteredItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-500 text-xs">
            <Activity className="w-6 h-6 mb-2 opacity-40 text-slate-400" />
            <p>No activity events recorded yet.</p>
            <p className="text-[11px] text-slate-600 mt-0.5">
              Live simulation operational events will stream here.
            </p>
          </div>
        ) : (
          filteredItems.map((item) => (
            <div
              key={item.id}
              data-testid="activity-item"
              className="group flex items-start space-x-2.5 px-2.5 py-1.5 rounded hover:bg-slate-900/60 transition-colors text-xs"
            >
              {/* Event Icon */}
              <div className="pt-0.5">{getEventIcon(item)}</div>

              {/* Timestamp & Sequence */}
              <div className="flex flex-col flex-shrink-0 w-16 text-[10px] text-slate-400">
                <span className="font-semibold text-slate-300">
                  {formatTimeDisplay(item.timestamp)}
                </span>
                <span className="text-[9px] text-slate-600">#{item.sequence}</span>
              </div>

              {/* Category Badge */}
              <div className="flex-shrink-0 pt-0.5">{getSeverityBadge(item)}</div>

              {/* Message Content */}
              <div className="flex-1 min-w-0 pr-2">
                <div className="flex items-center space-x-2">
                  <span className="font-semibold text-slate-200 truncate">
                    {item.title}
                  </span>
                </div>
                <p className="text-slate-400 text-[11px] leading-tight break-words mt-0.5">
                  {item.description}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
