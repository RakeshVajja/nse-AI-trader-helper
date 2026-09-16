"use client";

import React from "react";
import { Layers } from "lucide-react";
import { IndicatorSnapshot } from "@/types";

interface IndicatorSummaryCardProps {
  snapshot?: IndicatorSnapshot | null;
  isLoading?: boolean;
}

export function IndicatorSummaryCard({
  snapshot,
  isLoading = false,
}: IndicatorSummaryCardProps) {
  if (isLoading) {
    return (
      <div className="bg-[#0e1420] border border-[#1e293b] rounded-lg p-3.5 space-y-2.5 animate-pulse">
        <div className="h-3 bg-slate-800 rounded w-1/3" />
        <div className="grid grid-cols-2 gap-2">
          <div className="h-10 bg-slate-800 rounded" />
          <div className="h-10 bg-slate-800 rounded" />
          <div className="h-10 bg-slate-800 rounded" />
          <div className="h-10 bg-slate-800 rounded" />
        </div>
      </div>
    );
  }

  const formatVal = (v?: number | null, decimals = 2) => {
    if (v === null || v === undefined) return "WARMUP";
    return v.toFixed(decimals);
  };

  return (
    <div className="bg-[#0e1420] border border-[#1e293b] rounded-lg p-3.5 space-y-2.5">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#1e293b] pb-2">
        <div className="text-[11px] text-slate-400 font-mono flex items-center space-x-1.5">
          <Layers className="w-3.5 h-3.5 text-cyan-400" />
          <span className="font-semibold text-slate-200">QUANTITATIVE INDICATORS</span>
        </div>
        <span className="text-[10px] text-slate-500 font-mono">DETERMINISTIC</span>
      </div>

      {/* Grid of indicators */}
      <div className="grid grid-cols-2 gap-2 text-xs font-mono">
        {/* EMA 9 */}
        <div className="bg-[#131a27] p-2 rounded border border-[#1e293b]/60 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400">EMA 9</span>
          <span className="text-sky-400 font-semibold text-[13px] mt-0.5">
            {formatVal(snapshot?.ema9)}
          </span>
        </div>

        {/* EMA 20 */}
        <div className="bg-[#131a27] p-2 rounded border border-[#1e293b]/60 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400">EMA 20</span>
          <span className="text-amber-400 font-semibold text-[13px] mt-0.5">
            {formatVal(snapshot?.ema20)}
          </span>
        </div>

        {/* SMA 50 */}
        <div className="bg-[#131a27] p-2 rounded border border-[#1e293b]/60 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400">SMA 50</span>
          <span className="text-purple-400 font-semibold text-[13px] mt-0.5">
            {formatVal(snapshot?.sma50)}
          </span>
        </div>

        {/* RSI 14 */}
        <div className="bg-[#131a27] p-2 rounded border border-[#1e293b]/60 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400">RSI 14</span>
          <span
            className={`font-semibold text-[13px] mt-0.5 ${
              (snapshot?.rsi14 ?? 50) > 70
                ? "text-rose-400"
                : (snapshot?.rsi14 ?? 50) < 30
                  ? "text-emerald-400"
                  : "text-cyan-300"
            }`}
          >
            {formatVal(snapshot?.rsi14, 1)}
          </span>
        </div>

        {/* MACD Line & Signal */}
        <div className="bg-[#131a27] p-2 rounded border border-[#1e293b]/60 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400">MACD (12, 26, 9)</span>
          <div className="text-[11px] mt-0.5 space-y-0.5">
            <div className="flex justify-between">
              <span className="text-slate-500">LINE:</span>
              <span className="text-slate-200">{formatVal(snapshot?.macd)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">SIG:</span>
              <span className="text-slate-300">{formatVal(snapshot?.macd_signal)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">HIST:</span>
              <span
                className={`font-semibold ${
                  (snapshot?.macd_histogram ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {formatVal(snapshot?.macd_histogram)}
              </span>
            </div>
          </div>
        </div>

        {/* ATR 14 & ATRP 14 */}
        <div className="bg-[#131a27] p-2 rounded border border-[#1e293b]/60 flex flex-col justify-between">
          <span className="text-[10px] text-slate-400">VOLATILITY (ATR 14)</span>
          <div className="text-[11px] mt-0.5 space-y-0.5">
            <div className="flex justify-between">
              <span className="text-slate-500">ATR:</span>
              <span className="text-slate-200">{formatVal(snapshot?.atr14)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">ATRP:</span>
              <span className="text-cyan-300 font-semibold">
                {snapshot?.atrp14 !== null && snapshot?.atrp14 !== undefined
                  ? `${snapshot.atrp14.toFixed(2)}%`
                  : "WARMUP"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
