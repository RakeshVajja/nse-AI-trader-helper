"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Shield,
  Cpu,
  Database,
  Radio,
  Bot,
  Plus,
  Link,
  Unlink,
  Wifi,
  WifiOff,
} from "lucide-react";
import { CandlestickChart } from "@/components/CandlestickChart";
import { MarketRegimeCard } from "@/components/MarketRegimeBadge";
import { IndicatorSummaryCard } from "@/components/IndicatorSummaryCard";
import { AgentCreationModal } from "@/components/AgentCreationModal";
import { MandateReviewModal } from "@/components/MandateReviewModal";
import { useSimulationWebSocket } from "@/hooks/useSimulationWebSocket";
import {
  fetchHistoricalCandles,
  fetchIndicatorSeries,
  fetchLatestIndicatorSnapshot,
  fetchInstruments,
  checkBackendHealth,
  generateAgentMandate,
} from "@/lib/api";
import {
  AgentDecisionPayload,
  AgentMandate,
  AgentMandateCreateRequest,
  Candle,
  CandleUpdatePayload,
  ChartTradeMarker,
  ConfirmedAgentMandate,
  IndicatorSeries,
  IndicatorSnapshot,
  InitialStatePayload,
  Instrument,
  LiveCandleUpdate,
  OrderExecutedPayload,
  PositionUpdatedPayload,
  SimulationEvent,
  Timeframe,
  TradeMarkerType,
} from "@/types";

const DEFAULT_SYMBOLS = [
  "RELIANCE",
  "TCS",
  "INFY",
  "HDFCBANK",
  "ICICIBANK",
  "SBIN",
  "ITC",
  "NIFTY 50",
  "BANK NIFTY",
  "NIFTY IT",
];

const TIMEFRAMES: Timeframe[] = ["5m", "15m", "30m", "1h", "1d"];

export default function TerminalPage() {
  const [healthStatus, setHealthStatus] = useState<string>("Connecting...");
  const [isBackendOnline, setIsBackendOnline] = useState<boolean>(false);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("RELIANCE");
  const [selectedTimeframe, setSelectedTimeframe] = useState<Timeframe>("15m");

  const [candles, setCandles] = useState<Candle[]>([]);
  const [indicatorSeries, setIndicatorSeries] = useState<IndicatorSeries | null>(null);
  const [indicatorSnapshot, setIndicatorSnapshot] = useState<IndicatorSnapshot | null>(null);
  const [isLoadingCandles, setIsLoadingCandles] = useState<boolean>(false);
  const [candleError, setCandleError] = useState<string | null>(null);

  // Phase 9 Modals
  const [isAgentModalOpen, setIsAgentModalOpen] = useState<boolean>(false);
  const [isReviewModalOpen, setIsReviewModalOpen] = useState<boolean>(false);
  const [activeMandate, setActiveMandate] = useState<AgentMandate | null>(null);
  const [createdAgentName, setCreatedAgentName] = useState<string>("AI Trading Agent");
  const [createdInitialCapital, setCreatedInitialCapital] = useState<number>(100000);

  // Phase 10B: Live Simulation WebSocket & Visual Terminal State
  const [activeSimulationId, setActiveSimulationId] = useState<string | null>(null);
  const [isAttachModalOpen, setIsAttachModalOpen] = useState<boolean>(false);
  const [attachInputId, setAttachInputId] = useState<string>("");
  const [chartMarkers, setChartMarkers] = useState<ChartTradeMarker[]>([]);
  const [activeStopLoss, setActiveStopLoss] = useState<number | null>(null);
  const [activeTakeProfit, setActiveTakeProfit] = useState<number | null>(null);
  const [liveCandle, setLiveCandle] = useState<LiveCandleUpdate | null>(null);

  // WebSocket Event Handler
  const handleSimulationEvent = useCallback((event: SimulationEvent) => {
    if (activeSimulationId && event.simulation_id !== activeSimulationId) {
      return;
    }

    switch (event.event_type) {
      case "initial_state": {
        const p = event.payload as InitialStatePayload;
        if (p) {
          if (p.symbol && p.symbol !== selectedSymbol) {
            setSelectedSymbol(p.symbol);
          }
          if (p.timeframe && p.timeframe !== selectedTimeframe) {
            setSelectedTimeframe(p.timeframe as Timeframe);
          }
          if (p.positions && p.positions.length > 0) {
            const openPos = p.positions.find((x) => x.is_open);
            if (openPos) {
              setActiveStopLoss(openPos.stop_loss ?? null);
              setActiveTakeProfit(openPos.take_profit ?? null);
            } else {
              setActiveStopLoss(null);
              setActiveTakeProfit(null);
            }
          }
          // Guard against lookahead: filter existing candles so no future replay candles appear
          if (p.current_time) {
            const maxEpochMs = new Date(p.current_time).getTime();
            setCandles((prev) =>
              prev.filter((c) => new Date(c.timestamp).getTime() <= maxEpochMs)
            );
          }
        }
        break;
      }
      case "candle_update": {
        const p = event.payload as CandleUpdatePayload;
        if (p && p.candle) {
          setLiveCandle({
            step_index: p.step_index,
            candle: p.candle,
          });
        }
        break;
      }
      case "order_executed": {
        const p = event.payload as OrderExecutedPayload;
        if (p && p.status === "FILLED") {
          const timeEpoch = event.virtual_timestamp
            ? Math.floor(new Date(event.virtual_timestamp).getTime() / 1000)
            : Math.floor(Date.now() / 1000);

          let markerType: TradeMarkerType = "BUY_EXECUTION";
          if (p.is_auto_exit) {
            markerType = p.execution_price <= (activeStopLoss ?? 0) ? "SL_EXIT" : "TP_EXIT";
          } else if (p.side === "BUY") {
            markerType = "BUY_EXECUTION";
          } else if (p.side === "SELL") {
            markerType = "SELL_EXECUTION";
          }

          const markerId = p.order_id || `order-${event.sequence}`;
          const newMarker: ChartTradeMarker = {
            id: markerId,
            time: timeEpoch,
            type: markerType,
            price: p.execution_price,
            quantity: p.quantity,
            text: `${markerType.replace("_", " ")} @ ₹${p.execution_price.toFixed(2)} (${p.quantity} qty)`,
          };

          setChartMarkers((prev) => {
            if (prev.some((m) => m.id === markerId)) {
              return prev;
            }
            return [...prev, newMarker];
          });
        }
        break;
      }
      case "position_updated": {
        const p = event.payload as PositionUpdatedPayload;
        if (p && p.positions) {
          const openPos = p.positions.find((x) => x.is_open);
          if (openPos) {
            setActiveStopLoss(openPos.stop_loss ?? null);
            setActiveTakeProfit(openPos.take_profit ?? null);
          } else {
            setActiveStopLoss(null);
            setActiveTakeProfit(null);
          }
        }
        break;
      }
      case "agent_decision": {
        const p = event.payload as AgentDecisionPayload;
        if (p && (p.action === "BUY" || p.action === "SELL")) {
          const timeEpoch = event.virtual_timestamp
            ? Math.floor(new Date(event.virtual_timestamp).getTime() / 1000)
            : Math.floor(Date.now() / 1000);
          const signalId = `signal-${event.sequence}`;
          const signalMarker: ChartTradeMarker = {
            id: signalId,
            time: timeEpoch,
            type: p.action === "BUY" ? "SIGNAL_BUY" : "SIGNAL_SELL",
            price: 0,
            text: `SIG: ${p.action} (${(p.confidence * 100).toFixed(0)}%)`,
            details: p.reason,
          };
          setChartMarkers((prev) => {
            if (prev.some((m) => m.id === signalId)) {
              return prev;
            }
            return [...prev, signalMarker];
          });
        }
        break;
      }
      default:
        // Ignore unrelated events safely without breaking
        break;
    }
  }, [activeSimulationId, selectedSymbol, selectedTimeframe, activeStopLoss]);

  // Phase 10A WebSocket Hook Integration
  const { connectionState, isConnected } = useSimulationWebSocket({
    simulationId: activeSimulationId,
    enabled: Boolean(activeSimulationId),
    onEvent: handleSimulationEvent,
  });

  const handleAgentCreateSubmit = async (payload: AgentMandateCreateRequest) => {
    const resp = await generateAgentMandate(payload);
    if (resp.success && resp.mandate) {
      setActiveMandate(resp.mandate);
      setCreatedAgentName(payload.agent_name);
      setCreatedInitialCapital(payload.initial_capital);
      setIsAgentModalOpen(false);
      setIsReviewModalOpen(true);
    } else {
      throw new Error(resp.error || "Failed to generate agent strategy mandate.");
    }
  };

  // 1. Initial backend health check & instrument list fetch
  useEffect(() => {
    checkBackendHealth()
      .then((data) => {
        setIsBackendOnline(true);
        setHealthStatus(`Online (v${data.version})`);
      })
      .catch(() => {
        setIsBackendOnline(false);
        setHealthStatus("Offline (Port 8000)");
      });

    fetchInstruments()
      .then((data) => {
        if (data.instruments && data.instruments.length > 0) {
          setInstruments(data.instruments);
        }
      })
      .catch(() => {
        // Fall back to default static list
      });
  }, []);

  // 2. Fetch historical OHLCV data and calculated indicators
  const loadMarketAndIndicators = useCallback(async (sym: string, tf: Timeframe) => {
    setIsLoadingCandles(true);
    setCandleError(null);

    try {
      const now = new Date();
      let lookbackDays = 60;
      if (tf === "5m") lookbackDays = 15;
      else if (tf === "15m") lookbackDays = 45;
      else if (tf === "30m") lookbackDays = 60;
      else if (tf === "1h") lookbackDays = 90;
      else if (tf === "1d") lookbackDays = 365;

      const startDate = new Date(now.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
      const isIndex = sym.startsWith("NIFTY") || sym.includes("BANK");
      const instType = isIndex ? "INDEX" : "EQUITY";

      // Parallel fetch: historical candles, indicator time series, and latest snapshot
      const [candleResp, indResp, snapResp] = await Promise.all([
        fetchHistoricalCandles(sym, tf, startDate, now, instType),
        fetchIndicatorSeries(sym, tf, startDate, now, instType).catch((err) => {
          console.warn("Indicator series fetch failed:", err);
          return null;
        }),
        fetchLatestIndicatorSnapshot(sym, tf, lookbackDays, instType).catch((err) => {
          console.warn("Indicator snapshot fetch failed:", err);
          return null;
        }),
      ]);

      setCandles(candleResp.candles || []);
      setIndicatorSeries(indResp);
      setIndicatorSnapshot(snapResp?.snapshot || null);
    } catch (err: any) {
      setCandleError(err.message || "Failed to fetch candlestick & indicator data");
      setCandles([]);
      setIndicatorSeries(null);
      setIndicatorSnapshot(null);
    } finally {
      setIsLoadingCandles(false);
    }
  }, []);

  useEffect(() => {
    // Clear instrument-specific chart state when switching symbol or timeframe
    setChartMarkers([]);
    setActiveStopLoss(null);
    setActiveTakeProfit(null);
    setLiveCandle(null);
    loadMarketAndIndicators(selectedSymbol, selectedTimeframe);
  }, [selectedSymbol, selectedTimeframe, loadMarketAndIndicators]);

  const symbolList =
    instruments.length > 0
      ? instruments.map((i) => i.symbol)
      : DEFAULT_SYMBOLS;

  return (
    <div className="flex flex-col h-screen w-screen bg-[#0a0d14] text-slate-200 overflow-hidden select-none">
      {/* Top Header Bar */}
      <header className="h-14 border-b border-[#1e293b] bg-[#131a27] px-4 flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-slate-100 tracking-wide font-mono">
              NSE AI TRADER
            </h1>
            <p className="text-[10px] text-slate-400 font-mono">
              QUANTITATIVE TRADING TERMINAL
            </p>
          </div>
        </div>

        {/* Instrument & Timeframe Selectors */}
        <div className="flex items-center space-x-2">
          {/* Symbol Dropdown */}
          <div className="flex items-center bg-[#0e1420] border border-[#1e293b] rounded-md px-2.5 py-1">
            <span className="text-xs text-slate-400 mr-2 font-mono">SYMBOL:</span>
            <select
              value={selectedSymbol}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="bg-transparent text-xs font-mono text-emerald-400 font-semibold focus:outline-none cursor-pointer"
            >
              {symbolList.map((sym) => (
                <option key={sym} value={sym} className="bg-[#131a27] text-slate-200">
                  {sym}
                </option>
              ))}
            </select>
          </div>

          {/* Timeframe Selector Buttons */}
          <div className="flex items-center bg-[#0e1420] border border-[#1e293b] rounded-md p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setSelectedTimeframe(tf)}
                className={`px-2.5 py-1 text-xs font-mono rounded transition-colors ${
                  selectedTimeframe === tf
                    ? "bg-emerald-500/20 text-emerald-300 font-semibold border border-emerald-500/30"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        {/* Status & WebSocket Controls */}
        <div className="flex items-center space-x-3 text-xs font-mono">
          {/* Backend API Health Status */}
          <div className="flex items-center space-x-1.5 bg-[#0e1420] border border-[#1e293b] px-2.5 py-1 rounded-md">
            <span
              className={`w-2 h-2 rounded-full ${
                isBackendOnline ? "bg-emerald-400 animate-pulse" : "bg-rose-500"
              }`}
            />
            <span className="text-slate-300 text-[11px]">{healthStatus}</span>
          </div>

          {/* Phase 10B Simulation Attachment / Status Pill */}
          {activeSimulationId ? (
            <div className="flex items-center space-x-1.5 bg-[#0e1420] border border-blue-500/30 px-2.5 py-1 rounded-md">
              {isConnected ? (
                <Wifi className="w-3 h-3 text-emerald-400" />
              ) : connectionState === "CONNECTING" ? (
                <Radio className="w-3 h-3 text-amber-400 animate-pulse" />
              ) : (
                <WifiOff className="w-3 h-3 text-rose-400" />
              )}
              <span className="text-[11px] text-blue-300 font-mono">
                SIM: {activeSimulationId.slice(0, 8)}... ({connectionState})
              </span>
              <button
                onClick={() => {
                  setActiveSimulationId(null);
                  setChartMarkers([]);
                  setActiveStopLoss(null);
                  setActiveTakeProfit(null);
                  setLiveCandle(null);
                }}
                title="Detach simulation and return to standalone market view"
                className="text-slate-400 hover:text-rose-400 ml-1 cursor-pointer"
              >
                <Unlink className="w-3 h-3" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setIsAttachModalOpen(true)}
              className="flex items-center space-x-1 bg-[#0e1420] hover:bg-[#182030] border border-[#1e293b] hover:border-blue-500/40 text-slate-300 hover:text-blue-300 px-2.5 py-1 rounded-md text-[11px] font-mono transition-colors cursor-pointer"
              title="Attach to active simulation session to stream live candles and orders"
            >
              <Link className="w-3 h-3 text-blue-400" />
              <span>STREAM SIMULATION</span>
            </button>
          )}

          {/* Initialize Agent Action Button */}
          <button
            onClick={() => setIsAgentModalOpen(true)}
            className="flex items-center space-x-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 px-3 py-1 rounded-md text-xs font-mono font-semibold transition-colors cursor-pointer"
          >
            <Bot className="w-3.5 h-3.5 text-emerald-400" />
            <span>+ NEW AGENT</span>
          </button>
        </div>
      </header>

      {/* Main Terminal Workspace */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left / Center: Candlestick Chart Area */}
        <div className="flex-1 flex flex-col border-r border-[#1e293b] min-w-0">
          <div className="flex-1 w-full h-full min-h-0 bg-[#0a0d14] relative">
            <CandlestickChart
              candles={candles}
              symbol={selectedSymbol}
              timeframe={selectedTimeframe}
              indicatorSeries={indicatorSeries}
              isLoading={isLoadingCandles}
              error={candleError}
              onRetry={() => loadMarketAndIndicators(selectedSymbol, selectedTimeframe)}
              markers={chartMarkers}
              stopLoss={activeStopLoss}
              takeProfit={activeTakeProfit}
              liveCandle={liveCandle}
            />
          </div>

          {/* Bottom Terminal Metric Strip */}
          <div className="h-11 border-t border-[#1e293b] bg-[#0e1420] px-4 flex items-center justify-between text-xs font-mono shrink-0">
            <div className="flex items-center space-x-6 text-slate-400">
              <div>
                CAPITAL: <span className="text-slate-200 font-semibold">₹1,00,000</span>
              </div>
              <div>
                MAX RISK: <span className="text-slate-200 font-semibold">2.0%</span>
              </div>
              <div>
                MAX EXPOSURE: <span className="text-slate-200 font-semibold">25.0%</span>
              </div>
              <div>
                CANDLES: <span className="text-emerald-400 font-semibold">{candles.length}</span>
              </div>
              {chartMarkers.length > 0 && (
                <div>
                  MARKERS: <span className="text-sky-400 font-semibold">{chartMarkers.length}</span>
                </div>
              )}
            </div>
            <div className="flex items-center space-x-1.5 text-slate-500 text-[11px]">
              <Database className="w-3.5 h-3.5 text-slate-400" />
              <span>POSTGRESQL CACHED + DETERMINISTIC QUANT ENGINE</span>
            </div>
          </div>
        </div>

        {/* Right Sidebar: Market Regime & Quantitative Engine Panel */}
        <aside className="w-84 bg-[#131a27] p-3.5 flex flex-col space-y-3.5 shrink-0 overflow-y-auto border-l border-[#1e293b]">
          {/* Market Regime Card */}
          <MarketRegimeCard
            regime={
              indicatorSnapshot
                ? {
                    timestamp: indicatorSnapshot.timestamp,
                    trend_regime: indicatorSnapshot.trend_regime,
                    volatility_regime: indicatorSnapshot.volatility_regime,
                    trend_details: indicatorSnapshot.trend_details,
                    volatility_details: indicatorSnapshot.volatility_details,
                  }
                : null
            }
            isLoading={isLoadingCandles}
          />

          {/* Quantitative Indicator Summary Card */}
          <IndicatorSummaryCard
            snapshot={indicatorSnapshot}
            isLoading={isLoadingCandles}
          />

          {/* Active Mandate Info Card */}
          <div className="bg-[#0e1420] border border-[#1e293b] rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between border-b border-[#1e293b] pb-2">
              <div className="text-[11px] text-slate-400 font-mono flex items-center space-x-1.5">
                <Shield className="w-3.5 h-3.5 text-emerald-400" />
                <span className="font-semibold text-slate-200">STRATEGY MANDATE</span>
              </div>
              <span className="text-[10px] text-emerald-400 font-mono bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.2 rounded">
                ACTIVE
              </span>
            </div>
            <div className="text-xs text-slate-300 font-mono">
              {activeMandate
                ? `${createdAgentName} (${activeMandate.strategy_style.toUpperCase()})`
                : `${selectedSymbol} Quantitative Replay Strategy`}
            </div>
            <div className="text-[11px] text-slate-400 space-y-1 font-mono pt-1">
              <div>
                TIMEFRAME: {activeMandate ? activeMandate.timeframe : selectedTimeframe}
              </div>
              {activeMandate && (
                <>
                  <div>
                    RISK/TRADE: {(activeMandate.risk_per_trade * 100).toFixed(1)}%
                  </div>
                  <div>
                    INDICATORS: {activeMandate.preferred_indicators.join(", ")}
                  </div>
                </>
              )}
              <div>EXECUTION: NEXT CANDLE OPEN</div>
              <div>SLIPPAGE MODEL: 0.05%</div>
            </div>
            <button
              onClick={() => setIsAgentModalOpen(true)}
              className="w-full mt-2 py-1.5 px-2.5 bg-[#182030] hover:bg-[#1e293b] text-emerald-400 border border-emerald-500/30 rounded text-[11px] font-mono flex items-center justify-center space-x-1.5 transition-colors cursor-pointer"
            >
              <Plus className="w-3 h-3" />
              <span>CONFIGURE NEW AGENT</span>
            </button>
          </div>
        </aside>
      </main>

      {/* Attach Simulation Session Modal */}
      {isAttachModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-md bg-[#131a27] border border-[#1e293b] rounded-xl p-5 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#1e293b] pb-3">
              <div className="flex items-center space-x-2 text-sm font-semibold font-mono text-slate-100">
                <Link className="w-4 h-4 text-blue-400" />
                <span>Stream Simulation Run</span>
              </div>
              <button
                onClick={() => setIsAttachModalOpen(false)}
                className="text-slate-400 hover:text-slate-200 text-xs font-mono"
              >
                ✕
              </button>
            </div>
            <p className="text-xs text-slate-400 font-mono leading-relaxed">
              Enter an active or replay Simulation ID to stream live candle updates, executed trade markers, and stop-loss / take-profit price lines via WebSocket.
            </p>
            <div>
              <label className="block text-[11px] font-mono text-slate-300 mb-1">
                SIMULATION ID
              </label>
              <input
                type="text"
                placeholder="e.g. sim_01j7abc123..."
                value={attachInputId}
                onChange={(e) => setAttachInputId(e.target.value)}
                className="w-full bg-[#0a0d14] border border-[#1e293b] focus:border-blue-500/50 rounded px-3 py-2 text-xs font-mono text-slate-100 outline-none"
              />
            </div>
            <div className="flex justify-end space-x-2 pt-2">
              <button
                onClick={() => setIsAttachModalOpen(false)}
                className="px-3 py-1.5 bg-[#182030] hover:bg-[#1e293b] text-slate-300 text-xs font-mono rounded"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (attachInputId.trim()) {
                    setActiveSimulationId(attachInputId.trim());
                    setChartMarkers([]);
                    setIsAttachModalOpen(false);
                    setAttachInputId("");
                  }
                }}
                disabled={!attachInputId.trim()}
                className="px-3.5 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 disabled:opacity-50 text-blue-300 border border-blue-500/40 text-xs font-mono rounded font-semibold cursor-pointer"
              >
                Connect Stream
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 9A: Agent Creation Modal */}
      <AgentCreationModal
        isOpen={isAgentModalOpen}
        onClose={() => setIsAgentModalOpen(false)}
        onSubmit={handleAgentCreateSubmit}
        defaultSymbol={selectedSymbol}
        defaultTimeframe={selectedTimeframe}
      />

      {/* Phase 9B: Mandate Review Modal */}
      <MandateReviewModal
        isOpen={isReviewModalOpen}
        mandate={activeMandate}
        agentName={createdAgentName}
        initialCapital={createdInitialCapital}
        onClose={() => setIsReviewModalOpen(false)}
        onRevisePrompt={() => {
          setIsReviewModalOpen(false);
          setIsAgentModalOpen(true);
        }}
        onConfirm={async (confirmed: ConfirmedAgentMandate) => {
          setActiveMandate(confirmed.mandate);
          setIsReviewModalOpen(false);
        }}
      />
    </div>
  );
}
