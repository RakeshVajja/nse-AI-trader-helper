"use client";

import React from "react";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Gauge,
  CheckCircle2,
  XCircle,
  HelpCircle,
  AlertCircle,
} from "lucide-react";
import { MarketRegimeSnapshot, TrendRegime, VolatilityRegime } from "@/types";

interface MarketRegimeCardProps {
  regime?: MarketRegimeSnapshot | null;
  isLoading?: boolean;
}

export function MarketRegimeCard({ regime, isLoading = false }: MarketRegimeCardProps) {
  if (isLoading) {
    return (
      <div className="bg-[#0e1420] border border-[#1e293b] rounded-lg p-3.5 space-y-3 animate-pulse">
        <div className="h-3 bg-slate-800 rounded w-1/3" />
        <div className="h-8 bg-slate-800 rounded" />
        <div className="h-16 bg-slate-800 rounded" />
      </div>
    );
  }

  const trend = regime?.trend_regime;
  const vol = regime?.volatility_regime;
  const trendDetails = regime?.trend_details;
  const volDetails = regime?.volatility_details;

  // Trend Badge styles
  const getTrendStyle = (t?: TrendRegime | null) => {
    switch (t) {
      case "BULLISH":
        return {
          bg: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
          icon: <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />,
          label: "BULLISH",
        };
      case "BEARISH":
        return {
          bg: "bg-rose-500/10 border-rose-500/30 text-rose-400",
          icon: <TrendingDown className="w-3.5 h-3.5 text-rose-400" />,
          label: "BEARISH",
        };
      case "SIDEWAYS":
        return {
          bg: "bg-amber-500/10 border-amber-500/30 text-amber-300",
          icon: <Activity className="w-3.5 h-3.5 text-amber-400" />,
          label: "SIDEWAYS",
        };
      default:
        return {
          bg: "bg-slate-800/50 border-slate-700 text-slate-400",
          icon: <HelpCircle className="w-3.5 h-3.5 text-slate-400" />,
          label: "WARMUP (SMA50)",
        };
    }
  };

  // Volatility Badge styles
  const getVolStyle = (v?: VolatilityRegime | null) => {
    switch (v) {
      case "HIGH":
        return {
          bg: "bg-rose-500/15 border-rose-500/30 text-rose-300",
          icon: <AlertCircle className="w-3.5 h-3.5 text-rose-400" />,
          label: "HIGH VOLATILITY",
        };
      case "NORMAL":
        return {
          bg: "bg-cyan-500/10 border-cyan-500/30 text-cyan-300",
          icon: <Gauge className="w-3.5 h-3.5 text-cyan-400" />,
          label: "NORMAL VOLATILITY",
        };
      case "LOW":
        return {
          bg: "bg-slate-700/20 border-slate-600/30 text-slate-300",
          icon: <Activity className="w-3.5 h-3.5 text-slate-400" />,
          label: "LOW VOLATILITY",
        };
      default:
        return {
          bg: "bg-slate-800/50 border-slate-700 text-slate-400",
          icon: <HelpCircle className="w-3.5 h-3.5 text-slate-400" />,
          label: "WARMUP (100-BAR)",
        };
    }
  };

  const trendStyle = getTrendStyle(trend);
  const volStyle = getVolStyle(vol);

  const renderVoteSignal = (signalName: string, value?: string | null) => {
    let icon = <HelpCircle className="w-3 h-3 text-slate-500" />;
    let textStyle = "text-slate-400";

    if (value === "BULLISH") {
      icon = <CheckCircle2 className="w-3 h-3 text-emerald-400" />;
      textStyle = "text-emerald-400 font-medium";
    } else if (value === "BEARISH") {
      icon = <XCircle className="w-3 h-3 text-rose-400" />;
      textStyle = "text-rose-400 font-medium";
    } else if (value === "NEUTRAL") {
      icon = <Activity className="w-3 h-3 text-amber-400" />;
      textStyle = "text-amber-400";
    }

    return (
      <div className="flex items-center justify-between text-[11px] font-mono py-0.5">
        <span className="text-slate-400">{signalName}</span>
        <div className="flex items-center space-x-1">
          {icon}
          <span className={textStyle}>{value || "N/A"}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="bg-[#0e1420] border border-[#1e293b] rounded-lg p-3.5 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#1e293b] pb-2">
        <div className="text-[11px] text-slate-400 font-mono flex items-center space-x-1.5">
          <Activity className="w-3.5 h-3.5 text-emerald-400" />
          <span className="font-semibold text-slate-200">MARKET STATE REGIME</span>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">DETERMINISTIC</span>
      </div>

      {/* Primary Regime Badges */}
      <div className="grid grid-cols-2 gap-2">
        {/* Trend Regime Badge */}
        <div
          className={`px-2.5 py-2 rounded-md border flex flex-col justify-between ${trendStyle.bg}`}
        >
          <span className="text-[9px] uppercase tracking-wider font-mono opacity-80">
            TREND REGIME
          </span>
          <div className="flex items-center space-x-1.5 mt-1 font-mono font-bold text-xs">
            {trendStyle.icon}
            <span>{trendStyle.label}</span>
          </div>
        </div>

        {/* Volatility Regime Badge */}
        <div
          className={`px-2.5 py-2 rounded-md border flex flex-col justify-between ${volStyle.bg}`}
        >
          <span className="text-[9px] uppercase tracking-wider font-mono opacity-80">
            VOLATILITY REGIME
          </span>
          <div className="flex items-center space-x-1.5 mt-1 font-mono font-bold text-xs">
            {volStyle.icon}
            <span>{volStyle.label}</span>
          </div>
        </div>
      </div>

      {/* Quantitative Evidence Accordion / Details */}
      <div className="space-y-2 pt-1">
        {/* 3-of-4 Voting Breakdown */}
        <div className="bg-[#131a27] rounded-md p-2 border border-[#1e293b]/60">
          <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono pb-1 border-b border-[#1e293b]/60 mb-1">
            <span>TREND EVIDENCE (3-of-4)</span>
            <span className="text-slate-300 font-semibold">
              {trendDetails?.bullish_votes ?? 0} Bullish / {trendDetails?.bearish_votes ?? 0} Bearish
            </span>
          </div>
          <div className="space-y-0.5">
            {renderVoteSignal("Close > SMA50", trendDetails?.close_vs_sma50)}
            {renderVoteSignal("EMA9 > EMA20", trendDetails?.ema9_vs_ema20)}
            {renderVoteSignal("MACD > 0", trendDetails?.macd_vs_zero)}
            {renderVoteSignal("RSI14 > 50", trendDetails?.rsi14_vs_50)}
          </div>
        </div>

        {/* Historical Rolling Volatility Metrics */}
        <div className="bg-[#131a27] rounded-md p-2 border border-[#1e293b]/60">
          <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono pb-1 border-b border-[#1e293b]/60 mb-1">
            <span>VOLATILITY EVIDENCE (100-BAR)</span>
            <span className="text-slate-300">
              N={volDetails?.sample_count ?? 0}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1 text-center font-mono text-[10px] pt-0.5">
            <div className="bg-[#0e1420] p-1 rounded border border-[#1e293b]/40">
              <div className="text-slate-500 text-[9px]">CURRENT</div>
              <div className="text-slate-200 font-semibold">
                {volDetails?.current_atrp14 !== null && volDetails?.current_atrp14 !== undefined
                  ? `${volDetails.current_atrp14.toFixed(2)}%`
                  : "N/A"}
              </div>
            </div>
            <div className="bg-[#0e1420] p-1 rounded border border-[#1e293b]/40">
              <div className="text-slate-500 text-[9px]">P20 (LOW)</div>
              <div className="text-cyan-400 font-semibold">
                {volDetails?.p20_threshold !== null && volDetails?.p20_threshold !== undefined
                  ? `${volDetails.p20_threshold.toFixed(2)}%`
                  : "N/A"}
              </div>
            </div>
            <div className="bg-[#0e1420] p-1 rounded border border-[#1e293b]/40">
              <div className="text-slate-500 text-[9px]">P80 (HIGH)</div>
              <div className="text-rose-400 font-semibold">
                {volDetails?.p80_threshold !== null && volDetails?.p80_threshold !== undefined
                  ? `${volDetails.p80_threshold.toFixed(2)}%`
                  : "N/A"}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
