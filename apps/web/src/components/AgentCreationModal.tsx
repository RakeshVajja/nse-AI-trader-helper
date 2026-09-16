"use client";

import React, { useState, useEffect, useCallback, useId } from "react";
import {
  X,
  Bot,
  AlertCircle,
  HelpCircle,
  Loader2,
  Sparkles,
  ShieldAlert,
} from "lucide-react";
import {
  AgentMandateCreateRequest,
  SUPPORTED_EQUITIES,
  SUPPORTED_INDICES,
  SUPPORTED_INSTRUMENTS,
  SUPPORTED_TIMEFRAMES,
} from "@/types";
import { generateAgentMandate } from "@/lib/api";

export interface AgentCreationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit?: (request: AgentMandateCreateRequest) => Promise<void> | void;
  defaultSymbol?: string;
  defaultTimeframe?: string;
}

interface ValidationErrors {
  agentName?: string;
  instrument?: string;
  timeframe?: string;
  initialCapital?: string;
  riskPerTrade?: string;
  positionExposure?: string;
  dailyLoss?: string;
  strategyPrompt?: string;
}

const STRATEGY_PRESETS = [
  {
    label: "EMA Trend Breakout",
    text: "I want a trend-following momentum strategy on 15m candles. Enter long when price closes above EMA20 with RSI above 55 and MACD histogram positive. Exit when price closes below EMA9 or RSI crosses below 45. Strictly preserve capital with 2% risk per trade.",
  },
  {
    label: "RSI Mean Reversion",
    text: "Mean-reversion trading strategy for high volatility regimes. Buy when RSI14 drops below 30 near the lower ATR band. Take profit when RSI recovers to 50 or crosses above EMA20. Cut losses immediately if price breaks support.",
  },
];

export function AgentCreationModal({
  isOpen,
  onClose,
  onSubmit,
  defaultSymbol = "RELIANCE",
  defaultTimeframe = "15m",
}: AgentCreationModalProps) {
  const modalId = useId();

  // Form fields with specification defaults
  const [agentName, setAgentName] = useState<string>("");
  const [instrument, setInstrument] = useState<string>(() =>
    (SUPPORTED_INSTRUMENTS as readonly string[]).includes(defaultSymbol)
      ? defaultSymbol
      : "RELIANCE"
  );
  const [timeframe, setTimeframe] = useState<string>(() =>
    (SUPPORTED_TIMEFRAMES as readonly string[]).includes(defaultTimeframe)
      ? defaultTimeframe
      : "15m"
  );
  const [initialCapital, setInitialCapital] = useState<number | string>(100000);
  const [riskPerTrade, setRiskPerTrade] = useState<number | string>(2.0); // %
  const [positionExposure, setPositionExposure] = useState<number | string>(25.0); // %
  const [dailyLoss, setDailyLoss] = useState<number | string>(5.0); // %
  const [strategyPrompt, setStrategyPrompt] = useState<string>("");

  const [errors, setErrors] = useState<ValidationErrors>({});
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);

  // Synchronize defaults when modal opens
  useEffect(() => {
    if (isOpen) {
      setInstrument(
        (SUPPORTED_INSTRUMENTS as readonly string[]).includes(defaultSymbol)
          ? defaultSymbol
          : "RELIANCE"
      );
      setTimeframe(
        (SUPPORTED_TIMEFRAMES as readonly string[]).includes(defaultTimeframe)
          ? defaultTimeframe
          : "15m"
      );
      setErrors({});
      setSubmissionError(null);
    }
  }, [isOpen, defaultSymbol, defaultTimeframe]);

  // Handle Escape key to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isSubmitting) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isSubmitting, onClose]);

  // Client-side validation adhering to backend contracts
  const validate = useCallback((): boolean => {
    const errs: ValidationErrors = {};

    // 1. Agent Name: 1-100 characters
    const trimmedName = agentName.trim();
    if (!trimmedName) {
      errs.agentName = "Agent name is required.";
    } else if (trimmedName.length > 100) {
      errs.agentName = "Agent name must be 100 characters or fewer.";
    }

    // 2. Instrument: authorized vocabulary
    if (!(SUPPORTED_INSTRUMENTS as readonly string[]).includes(instrument)) {
      errs.instrument = "Please select a supported NSE instrument.";
    }

    // 3. Timeframe: authorized vocabulary
    if (!(SUPPORTED_TIMEFRAMES as readonly string[]).includes(timeframe)) {
      errs.timeframe = "Please select a supported timeframe.";
    }

    // 4. Initial Capital: > 0
    const capNum = Number(initialCapital);
    if (!Number.isFinite(capNum) || capNum <= 0) {
      errs.initialCapital = "Initial capital must be greater than ₹0.";
    }

    // 5. Risk per trade: 0.1% to 10% (0.001 to 0.10)
    const riskNum = Number(riskPerTrade);
    if (!Number.isFinite(riskNum) || riskNum < 0.1 || riskNum > 10.0) {
      errs.riskPerTrade = "Risk per trade must be between 0.1% and 10.0%.";
    }

    // 6. Max position exposure: 1% to 100% (0.01 to 1.0)
    const expNum = Number(positionExposure);
    if (!Number.isFinite(expNum) || expNum < 1.0 || expNum > 100.0) {
      errs.positionExposure = "Position exposure must be between 1.0% and 100.0%.";
    }

    // 7. Max daily loss: 1% to 50% (0.01 to 0.50)
    const lossNum = Number(dailyLoss);
    if (!Number.isFinite(lossNum) || lossNum < 1.0 || lossNum > 50.0) {
      errs.dailyLoss = "Daily loss limit must be between 1.0% and 50.0%.";
    }

    // 8. Strategy Prompt: 3-3000 characters
    const trimmedPrompt = strategyPrompt.trim();
    if (!trimmedPrompt) {
      errs.strategyPrompt = "Natural language strategy prompt is required.";
    } else if (trimmedPrompt.length < 3) {
      errs.strategyPrompt = "Strategy prompt must be at least 3 characters.";
    } else if (trimmedPrompt.length > 3000) {
      errs.strategyPrompt = "Strategy prompt cannot exceed 3000 characters.";
    }

    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [
    agentName,
    instrument,
    timeframe,
    initialCapital,
    riskPerTrade,
    positionExposure,
    dailyLoss,
    strategyPrompt,
  ]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmissionError(null);

    if (!validate()) {
      return;
    }

    const payload: AgentMandateCreateRequest = {
      agent_name: agentName.trim(),
      instrument,
      timeframe,
      initial_capital: Number(initialCapital),
      max_risk_per_trade: Number(riskPerTrade) / 100,
      max_position_exposure: Number(positionExposure) / 100,
      max_daily_loss: Number(dailyLoss) / 100,
      strategy_prompt: strategyPrompt.trim(),
    };

    setIsSubmitting(true);
    try {
      if (onSubmit) {
        await onSubmit(payload);
      } else {
        await generateAgentMandate(payload);
      }
      onClose();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to submit agent creation request.";
      setSubmissionError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${modalId}-title`}
      aria-describedby={`${modalId}-desc`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSubmitting) {
          onClose();
        }
      }}
    >
      <div className="relative w-full max-w-2xl bg-[#0e1420] border border-[#1e293b] rounded-xl shadow-2xl flex flex-col overflow-hidden text-slate-200 font-mono my-8 animate-in fade-in zoom-in-95 duration-150">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-4 bg-[#131a27] border-b border-[#1e293b]">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Bot className="w-4 h-4" />
            </div>
            <div>
              <h2
                id={`${modalId}-title`}
                className="text-sm font-bold text-slate-100 tracking-wide font-mono flex items-center gap-2"
              >
                INITIALIZE AI TRADING AGENT
                <span className="text-[10px] bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded border border-emerald-500/30">
                  PHASE 9A
                </span>
              </h2>
              <p id={`${modalId}-desc`} className="text-[11px] text-slate-400">
                Define the natural-language strategy mandate and deterministic risk parameters.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            aria-label="Close modal"
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSubmit} noValidate className="flex flex-col flex-1">
          <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
            {/* Global Submission Error Alert */}
            {submissionError && (
              <div
                role="alert"
                className="bg-rose-500/10 border border-rose-500/30 rounded-lg p-3 flex items-start space-x-2.5 text-xs text-rose-300"
              >
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <span className="font-semibold">Creation Error: </span>
                  {submissionError}
                </div>
              </div>
            )}

            {/* Section 1: Agent Name */}
            <div>
              <label
                htmlFor={`${modalId}-agent-name`}
                className="block text-xs font-semibold text-slate-300 mb-1"
              >
                AGENT NAME <span className="text-rose-400">*</span>
              </label>
              <input
                id={`${modalId}-agent-name`}
                type="text"
                autoFocus
                value={agentName}
                onChange={(e) => {
                  setAgentName(e.target.value);
                  if (errors.agentName) setErrors((prev) => ({ ...prev, agentName: undefined }));
                }}
                disabled={isSubmitting}
                placeholder="e.g. Reliance Momentum Trend Agent"
                className={`w-full bg-[#131a27] border ${
                  errors.agentName ? "border-rose-500" : "border-[#1e293b]"
                } rounded-md px-3 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-emerald-500 transition-colors font-mono`}
              />
              {errors.agentName && (
                <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  {errors.agentName}
                </p>
              )}
            </div>

            {/* Section 2: Market Instrument & Timeframe Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {/* Instrument Select */}
              <div>
                <label
                  htmlFor={`${modalId}-instrument`}
                  className="block text-xs font-semibold text-slate-300 mb-1"
                >
                  TARGET INSTRUMENT <span className="text-rose-400">*</span>
                </label>
                <select
                  id={`${modalId}-instrument`}
                  value={instrument}
                  onChange={(e) => {
                    setInstrument(e.target.value);
                    if (errors.instrument) setErrors((prev) => ({ ...prev, instrument: undefined }));
                  }}
                  disabled={isSubmitting}
                  className={`w-full bg-[#131a27] border ${
                    errors.instrument ? "border-rose-500" : "border-[#1e293b]"
                  } rounded-md px-3 py-2 text-xs text-emerald-400 font-semibold focus:outline-none focus:border-emerald-500 transition-colors font-mono cursor-pointer`}
                >
                  <optgroup label="NSE Equities">
                    {SUPPORTED_EQUITIES.map((eq) => (
                      <option key={eq} value={eq} className="bg-[#131a27] text-slate-200">
                        {eq}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="NSE Indices">
                    {SUPPORTED_INDICES.map((idx) => (
                      <option key={idx} value={idx} className="bg-[#131a27] text-slate-200">
                        {idx}
                      </option>
                    ))}
                  </optgroup>
                </select>
                {errors.instrument && (
                  <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {errors.instrument}
                  </p>
                )}
              </div>

              {/* Timeframe Select */}
              <div>
                <label
                  htmlFor={`${modalId}-timeframe`}
                  className="block text-xs font-semibold text-slate-300 mb-1"
                >
                  EXECUTION TIMEFRAME <span className="text-rose-400">*</span>
                </label>
                <select
                  id={`${modalId}-timeframe`}
                  value={timeframe}
                  onChange={(e) => {
                    setTimeframe(e.target.value);
                    if (errors.timeframe) setErrors((prev) => ({ ...prev, timeframe: undefined }));
                  }}
                  disabled={isSubmitting}
                  className={`w-full bg-[#131a27] border ${
                    errors.timeframe ? "border-rose-500" : "border-[#1e293b]"
                  } rounded-md px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 transition-colors font-mono cursor-pointer`}
                >
                  {SUPPORTED_TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf} className="bg-[#131a27] text-slate-200">
                      {tf}
                    </option>
                  ))}
                </select>
                {errors.timeframe && (
                  <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {errors.timeframe}
                  </p>
                )}
              </div>
            </div>

            {/* Section 3: Capital & Risk Parameters (Deterministic Sandbox Limits) */}
            <div className="bg-[#131a27]/60 border border-[#1e293b] rounded-lg p-3.5 space-y-3">
              <div className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider flex items-center gap-1.5 border-b border-[#1e293b] pb-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-emerald-400" />
                DETERMINISTIC RISK & CAPITAL BOUNDARIES
              </div>

              {/* Initial Capital */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label
                    htmlFor={`${modalId}-capital`}
                    className="text-xs font-semibold text-slate-300"
                  >
                    INITIAL VIRTUAL CAPITAL (INR ₹)
                  </label>
                  <span className="text-[10px] text-slate-400">Default: ₹1,00,000</span>
                </div>
                <input
                  id={`${modalId}-capital`}
                  type="number"
                  min="1"
                  step="1000"
                  value={initialCapital}
                  onChange={(e) => {
                    setInitialCapital(e.target.value);
                    if (errors.initialCapital)
                      setErrors((prev) => ({ ...prev, initialCapital: undefined }));
                  }}
                  disabled={isSubmitting}
                  className={`w-full bg-[#0e1420] border ${
                    errors.initialCapital ? "border-rose-500" : "border-[#1e293b]"
                  } rounded-md px-3 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-emerald-500 font-mono`}
                />
                {errors.initialCapital && (
                  <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    {errors.initialCapital}
                  </p>
                )}
              </div>

              {/* 3-Column Risk Limits */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1">
                {/* Max Risk Per Trade */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label
                      htmlFor={`${modalId}-risk`}
                      className="text-[11px] text-slate-300 font-semibold"
                    >
                      RISK / TRADE (%)
                    </label>
                  </div>
                  <input
                    id={`${modalId}-risk`}
                    type="number"
                    min="0.1"
                    max="10.0"
                    step="0.1"
                    value={riskPerTrade}
                    onChange={(e) => {
                      setRiskPerTrade(e.target.value);
                      if (errors.riskPerTrade)
                        setErrors((prev) => ({ ...prev, riskPerTrade: undefined }));
                    }}
                    disabled={isSubmitting}
                    className={`w-full bg-[#0e1420] border ${
                      errors.riskPerTrade ? "border-rose-500" : "border-[#1e293b]"
                    } rounded-md px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-emerald-500 font-mono`}
                  />
                  <p className="text-[10px] text-slate-400 mt-0.5">Bound: 0.1% – 10.0%</p>
                  {errors.riskPerTrade && (
                    <p className="text-[10px] text-rose-400 mt-0.5">{errors.riskPerTrade}</p>
                  )}
                </div>

                {/* Max Position Exposure */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label
                      htmlFor={`${modalId}-exposure`}
                      className="text-[11px] text-slate-300 font-semibold"
                    >
                      MAX EXPOSURE (%)
                    </label>
                  </div>
                  <input
                    id={`${modalId}-exposure`}
                    type="number"
                    min="1.0"
                    max="100.0"
                    step="1.0"
                    value={positionExposure}
                    onChange={(e) => {
                      setPositionExposure(e.target.value);
                      if (errors.positionExposure)
                        setErrors((prev) => ({ ...prev, positionExposure: undefined }));
                    }}
                    disabled={isSubmitting}
                    className={`w-full bg-[#0e1420] border ${
                      errors.positionExposure ? "border-rose-500" : "border-[#1e293b]"
                    } rounded-md px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-emerald-500 font-mono`}
                  />
                  <p className="text-[10px] text-slate-400 mt-0.5">Bound: 1.0% – 100.0%</p>
                  {errors.positionExposure && (
                    <p className="text-[10px] text-rose-400 mt-0.5">{errors.positionExposure}</p>
                  )}
                </div>

                {/* Max Daily Loss */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label
                      htmlFor={`${modalId}-loss`}
                      className="text-[11px] text-slate-300 font-semibold"
                    >
                      DAILY LOSS LIMIT (%)
                    </label>
                  </div>
                  <input
                    id={`${modalId}-loss`}
                    type="number"
                    min="1.0"
                    max="50.0"
                    step="0.5"
                    value={dailyLoss}
                    onChange={(e) => {
                      setDailyLoss(e.target.value);
                      if (errors.dailyLoss)
                        setErrors((prev) => ({ ...prev, dailyLoss: undefined }));
                    }}
                    disabled={isSubmitting}
                    className={`w-full bg-[#0e1420] border ${
                      errors.dailyLoss ? "border-rose-500" : "border-[#1e293b]"
                    } rounded-md px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-emerald-500 font-mono`}
                  />
                  <p className="text-[10px] text-slate-400 mt-0.5">Bound: 1.0% – 50.0%</p>
                  {errors.dailyLoss && (
                    <p className="text-[10px] text-rose-400 mt-0.5">{errors.dailyLoss}</p>
                  )}
                </div>
              </div>
            </div>

            {/* Section 4: Natural-Language Strategy Prompt */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label
                  htmlFor={`${modalId}-strategy-prompt`}
                  className="text-xs font-semibold text-slate-300 flex items-center gap-1.5"
                >
                  <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                  NATURAL LANGUAGE STRATEGY PROMPT <span className="text-rose-400">*</span>
                </label>
                <span
                  className={`text-[10px] ${
                    strategyPrompt.length > 2800 ? "text-amber-400" : "text-slate-400"
                  }`}
                >
                  {strategyPrompt.length} / 3000 chars
                </span>
              </div>
              <textarea
                id={`${modalId}-strategy-prompt`}
                rows={5}
                value={strategyPrompt}
                onChange={(e) => {
                  setStrategyPrompt(e.target.value);
                  if (errors.strategyPrompt)
                    setErrors((prev) => ({ ...prev, strategyPrompt: undefined }));
                }}
                disabled={isSubmitting}
                placeholder="e.g. I want a momentum strategy on 15m candles. Enter long when price closes above EMA20 with RSI above 55. Exit when price closes below EMA9. Strictly limit risk per trade to 2%."
                className={`w-full bg-[#131a27] border ${
                  errors.strategyPrompt ? "border-rose-500" : "border-[#1e293b]"
                } rounded-md p-3 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-emerald-500 transition-colors font-mono resize-y`}
              />
              {errors.strategyPrompt && (
                <p className="text-[11px] text-rose-400 mt-1 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  {errors.strategyPrompt}
                </p>
              )}

              {/* Quick Strategy Presets */}
              <div className="mt-2 flex items-center space-x-2 text-[11px]">
                <span className="text-slate-500">Quick Presets:</span>
                {STRATEGY_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => {
                      setStrategyPrompt(p.text);
                      if (errors.strategyPrompt)
                        setErrors((prev) => ({ ...prev, strategyPrompt: undefined }));
                    }}
                    className="px-2 py-0.5 bg-[#182030] hover:bg-[#1e293b] text-slate-300 hover:text-emerald-400 border border-[#1e293b] rounded transition-colors text-[10px]"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Modal Footer */}
          <div className="px-5 py-3.5 bg-[#131a27] border-t border-[#1e293b] flex items-center justify-between shrink-0">
            <div className="text-[10px] text-slate-400 flex items-center gap-1">
              <HelpCircle className="w-3.5 h-3.5 text-slate-400" />
              <span>Gemini compiles prompt to structured mandate</span>
            </div>
            <div className="flex items-center space-x-2.5">
              <button
                type="button"
                onClick={onClose}
                disabled={isSubmitting}
                className="px-3.5 py-1.5 text-xs font-mono rounded-md text-slate-300 hover:text-slate-100 hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="px-4 py-1.5 text-xs font-mono font-semibold rounded-md bg-emerald-600 hover:bg-emerald-500 text-slate-950 flex items-center space-x-1.5 transition-colors disabled:opacity-50 cursor-pointer"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Compiling Mandate...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Generate Strategy Mandate</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
