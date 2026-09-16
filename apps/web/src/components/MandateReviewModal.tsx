"use client";

import React, { useState, useEffect, useId, useCallback } from "react";
import {
  Shield,
  Lock,
  Edit3,
  CheckCircle2,
  AlertTriangle,
  ArrowLeft,
  X,
  Plus,
  Trash2,
  RefreshCw,
  Percent,
  Clock,
  Layers,
  Activity,
  Zap,
} from "lucide-react";
import {
  AgentMandate,
  ConfirmedAgentMandate,
  StrategyStyle,
  SUPPORTED_INDICATORS,
  SUPPORTED_STRATEGY_STYLES,
  SUPPORTED_TIMEFRAMES,
} from "@/types";
import { confirmAgentMandate } from "@/lib/api";

export interface MandateReviewModalProps {
  isOpen: boolean;
  mandate: AgentMandate | null;
  agentName?: string;
  initialCapital?: number;
  onClose: () => void;
  onRevisePrompt?: () => void;
  onConfirm?: (confirmed: ConfirmedAgentMandate) => Promise<void> | void;
}

interface ValidationErrors {
  riskPerTrade?: string;
  positionExposure?: string;
  dailyLoss?: string;
  preferredIndicators?: string;
  objectives?: string;
  strategyStyle?: string;
  timeframe?: string;
}

export function MandateReviewModal({
  isOpen,
  mandate,
  agentName = "AI Trading Agent",
  initialCapital = 100000,
  onClose,
  onRevisePrompt,
  onConfirm,
}: MandateReviewModalProps) {
  const modalId = useId();

  // Mode: review (read-only presentation) vs edit (fine-tuning editable fields)
  const [isEditing, setIsEditing] = useState<boolean>(false);

  // Editable fields initialized from generated mandate
  const [strategyStyle, setStrategyStyle] = useState<StrategyStyle>("momentum");
  const [objectives, setObjectives] = useState<string[]>([]);
  const [preferredIndicators, setPreferredIndicators] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState<string>("15m");
  const [riskPerTrade, setRiskPerTrade] = useState<number | string>(2.0); // %
  const [positionExposure, setPositionExposure] = useState<number | string>(25.0); // %
  const [dailyLoss, setDailyLoss] = useState<number | string>(5.0); // %

  // New objective input draft in edit mode
  const [newObjectiveDraft, setNewObjectiveDraft] = useState<string>("");

  // Validation & async submission states
  const [errors, setErrors] = useState<ValidationErrors>({});
  const [isConfirming, setIsConfirming] = useState<boolean>(false);
  const [confirmationError, setConfirmationError] = useState<string | null>(null);

  // Synchronize state whenever a new mandate is received or modal opens
  useEffect(() => {
    if (mandate && isOpen) {
      const style = (
        SUPPORTED_STRATEGY_STYLES as readonly string[]
      ).includes(mandate.strategy_style)
        ? (mandate.strategy_style as StrategyStyle)
        : "momentum";

      const tf = (SUPPORTED_TIMEFRAMES as readonly string[]).includes(
        mandate.timeframe
      )
        ? mandate.timeframe
        : "15m";

      const validIndicators = (mandate.preferred_indicators || []).filter((ind) =>
        (SUPPORTED_INDICATORS as readonly string[]).includes(ind)
      );

      setStrategyStyle(style);
      setObjectives(
        mandate.objectives && mandate.objectives.length > 0
          ? [...mandate.objectives]
          : ["Capture directional momentum setups"]
      );
      setPreferredIndicators(
        validIndicators.length > 0
          ? validIndicators
          : ["EMA9", "EMA20", "RSI14"]
      );
      setTimeframe(tf);
      setRiskPerTrade(
        Number.isFinite(mandate.risk_per_trade)
          ? +(mandate.risk_per_trade * 100).toFixed(2)
          : 2.0
      );
      setPositionExposure(
        Number.isFinite(mandate.max_position_exposure)
          ? +(mandate.max_position_exposure * 100).toFixed(2)
          : 25.0
      );
      setDailyLoss(
        Number.isFinite(mandate.max_daily_loss)
          ? +(mandate.max_daily_loss * 100).toFixed(2)
          : 5.0
      );

      setIsEditing(false);
      setErrors({});
      setConfirmationError(null);
      setNewObjectiveDraft("");
    }
  }, [mandate, isOpen]);

  // Keyboard shortcut: Escape closes review modal if not currently submitting
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isConfirming) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isConfirming, onClose]);

  // Client-side validation enforcing frozen backend contract constraints
  const validateEdits = useCallback((): boolean => {
    const errs: ValidationErrors = {};

    // 1. Strategy Style validation
    if (
      !(SUPPORTED_STRATEGY_STYLES as readonly string[]).includes(strategyStyle)
    ) {
      errs.strategyStyle = "Please select a supported strategy style.";
    }

    // 2. Timeframe validation
    if (!(SUPPORTED_TIMEFRAMES as readonly string[]).includes(timeframe)) {
      errs.timeframe = "Please select an authorized timeframe.";
    }

    // 3. Preferred Indicators: at least one supported indicator required
    if (preferredIndicators.length === 0) {
      errs.preferredIndicators = "At least one preferred indicator must be selected.";
    } else {
      const invalid = preferredIndicators.filter(
        (ind) => !(SUPPORTED_INDICATORS as readonly string[]).includes(ind)
      );
      if (invalid.length > 0) {
        errs.preferredIndicators = `Unsupported indicator: ${invalid.join(", ")}`;
      }
    }

    // 4. Objectives: 1 to 10 non-empty strings
    const cleanedObjs = objectives.map((o) => o.trim()).filter(Boolean);
    if (cleanedObjs.length === 0) {
      errs.objectives = "At least one strategic objective is required.";
    } else if (cleanedObjs.length > 10) {
      errs.objectives = "Maximum 10 strategic objectives allowed.";
    }

    // 5. Risk per trade: 0.1% to 10.0% (fraction 0.001 to 0.10)
    const riskNum = Number(riskPerTrade);
    if (!Number.isFinite(riskNum) || riskNum < 0.1 || riskNum > 10.0) {
      errs.riskPerTrade = "Risk per trade must be between 0.1% and 10.0%.";
    }

    // 6. Max position exposure: 1.0% to 100.0% (fraction 0.01 to 1.0)
    const expNum = Number(positionExposure);
    if (!Number.isFinite(expNum) || expNum < 1.0 || expNum > 100.0) {
      errs.positionExposure = "Position exposure must be between 1.0% and 100.0%.";
    }

    // 7. Max daily loss: 1.0% to 50.0% (fraction 0.01 to 0.50)
    const lossNum = Number(dailyLoss);
    if (!Number.isFinite(lossNum) || lossNum < 1.0 || lossNum > 50.0) {
      errs.dailyLoss = "Daily loss limit must be between 1.0% and 50.0%.";
    }

    setErrors(errs);
    return Object.keys(errs).length === 0;
  }, [
    strategyStyle,
    timeframe,
    preferredIndicators,
    objectives,
    riskPerTrade,
    positionExposure,
    dailyLoss,
  ]);

  // Indicator toggle handler for edit mode
  const handleToggleIndicator = (indicator: string) => {
    setPreferredIndicators((prev) => {
      if (prev.includes(indicator)) {
        return prev.filter((i) => i !== indicator);
      } else {
        return [...prev, indicator];
      }
    });
  };

  // Objective management
  const handleAddObjective = () => {
    const trimmed = newObjectiveDraft.trim();
    if (!trimmed) return;
    if (objectives.length >= 10) {
      setErrors((prev) => ({
        ...prev,
        objectives: "Maximum 10 strategic objectives allowed.",
      }));
      return;
    }
    setObjectives((prev) => [...prev, trimmed]);
    setNewObjectiveDraft("");
    setErrors((prev) => ({ ...prev, objectives: undefined }));
  };

  const handleRemoveObjective = (index: number) => {
    setObjectives((prev) => prev.filter((_, idx) => idx !== index));
  };

  // Apply edits and return to review mode
  const handleApplyEdits = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateEdits()) {
      setIsEditing(false);
      setErrors({});
    }
  };

  // Discard edits and restore originally received mandate
  const handleDiscardEdits = () => {
    if (!mandate) return;
    const style = (
      SUPPORTED_STRATEGY_STYLES as readonly string[]
    ).includes(mandate.strategy_style)
      ? (mandate.strategy_style as StrategyStyle)
      : "momentum";

    setStrategyStyle(style);
    setObjectives([...(mandate.objectives || [])]);
    setPreferredIndicators([...(mandate.preferred_indicators || [])]);
    setTimeframe(mandate.timeframe || "15m");
    setRiskPerTrade(
      Number.isFinite(mandate.risk_per_trade)
        ? +(mandate.risk_per_trade * 100).toFixed(2)
        : 2.0
    );
    setPositionExposure(
      Number.isFinite(mandate.max_position_exposure)
        ? +(mandate.max_position_exposure * 100).toFixed(2)
        : 25.0
    );
    setDailyLoss(
      Number.isFinite(mandate.max_daily_loss)
        ? +(mandate.max_daily_loss * 100).toFixed(2)
        : 5.0
    );
    setIsEditing(false);
    setErrors({});
  };

  // Explicit confirmation action: confirms reviewed mandate & transitions to simulation
  const handleConfirmAndStart = async () => {
    if (!mandate) return;
    setConfirmationError(null);

    // Validate current mandate configuration
    if (!validateEdits()) {
      setIsEditing(true); // Switch to edit mode to display errors clearly
      return;
    }

    const confirmedMandate: AgentMandate = {
      strategy_style: strategyStyle,
      objectives: objectives.map((o) => o.trim()).filter(Boolean),
      preferred_indicators: [...preferredIndicators],
      instrument: mandate.instrument, // strictly immutable
      timeframe: timeframe,
      risk_per_trade: Number(riskPerTrade) / 100, // convert % back to decimal fraction
      max_position_exposure: Number(positionExposure) / 100,
      max_daily_loss: Number(dailyLoss) / 100,
      rationale: mandate.rationale ?? null, // strictly immutable
    };

    const confirmedPayload: ConfirmedAgentMandate = {
      agent_name: agentName,
      initial_capital: initialCapital,
      mandate: confirmedMandate,
    };

    setIsConfirming(true);
    try {
      if (onConfirm) {
        await onConfirm(confirmedPayload);
      } else {
        await confirmAgentMandate(confirmedPayload);
      }
      onClose();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to confirm agent mandate.";
      setConfirmationError(message);
    } finally {
      setIsConfirming(false);
    }
  };

  if (!isOpen || !mandate) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${modalId}-title`}
      aria-describedby={`${modalId}-desc`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto"
    >
      <div className="relative w-full max-w-2xl bg-[#0e1420] border border-[#1e293b] rounded-xl shadow-2xl overflow-hidden font-mono my-8">
        {/* Top Header Bar */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#1e293b] bg-[#131a27]">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <Shield className="w-4 h-4" />
            </div>
            <div>
              <h2
                id={`${modalId}-title`}
                className="text-sm font-semibold text-slate-100 tracking-wider flex items-center gap-2"
              >
                <span>AGENT MANDATE REVIEW</span>
                {isEditing && (
                  <span className="text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/30 px-2 py-0.5 rounded font-normal">
                    EDIT MODE
                  </span>
                )}
              </h2>
              <p id={`${modalId}-desc`} className="text-[11px] text-slate-400">
                Review and verify declarative strategy parameters before simulation
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            disabled={isConfirming}
            aria-label="Close review modal"
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg hover:bg-[#1e293b] transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Identity & Asset Context Bar */}
        <div className="px-6 py-3 bg-[#0a0d14] border-b border-[#1e293b] flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center space-x-2">
            <span className="text-slate-500">AGENT:</span>
            <span className="text-emerald-400 font-semibold">{agentName}</span>
          </div>
          <div className="flex items-center space-x-4">
            <div>
              <span className="text-slate-500 mr-1.5">CAPITAL:</span>
              <span className="text-slate-200">
                ₹{initialCapital.toLocaleString("en-IN")}
              </span>
            </div>
            <div className="flex items-center text-slate-400 bg-[#131a27] border border-[#1e293b] px-2 py-0.5 rounded text-[11px]">
              <Lock className="w-3 h-3 text-slate-500 mr-1" />
              <span>ASSET:</span>
              <span className="text-slate-200 font-bold ml-1">
                {mandate.instrument}
              </span>
            </div>
          </div>
        </div>

        {/* API Error Notification */}
        {confirmationError && (
          <div
            role="alert"
            className="mx-6 mt-4 p-3 bg-red-950/40 border border-red-500/40 rounded-lg flex items-start space-x-2.5 text-xs text-red-300"
          >
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="font-semibold text-red-200">Confirmation Failed</div>
              <div>{confirmationError}</div>
              <div className="text-[10px] text-red-400">
                Your reviewed configuration has been preserved. Please try again.
              </div>
            </div>
          </div>
        )}

        {/* Modal Body */}
        <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
          {/* SECTION 1: Execution & Strategy Classification */}
          <div className="bg-[#131a27] border border-[#1e293b] rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400 border-b border-[#1e293b] pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-emerald-400" />
                STRATEGY ARCHITECTURE
              </span>
              <span className="text-[10px] text-slate-500">
                DECLARATIVE SPECIFICATION
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              {/* Target Instrument: Strictly Immutable */}
              <div>
                <label className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1 flex items-center">
                  <span>Instrument</span>
                  <Lock className="w-2.5 h-2.5 text-slate-500 ml-1 inline" />
                </label>
                <div className="px-2.5 py-1.5 bg-[#0a0d14] border border-[#1e293b] rounded text-xs text-slate-300 flex items-center justify-between">
                  <span className="font-bold text-emerald-400">
                    {mandate.instrument}
                  </span>
                  <span className="text-[9px] bg-slate-800 text-slate-400 px-1 py-0.5 rounded">
                    LOCKED
                  </span>
                </div>
              </div>

              {/* Timeframe: Editable */}
              <div>
                <label
                  htmlFor={`${modalId}-timeframe`}
                  className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1"
                >
                  Timeframe
                </label>
                {isEditing ? (
                  <select
                    id={`${modalId}-timeframe`}
                    value={timeframe}
                    onChange={(e) => setTimeframe(e.target.value)}
                    className="w-full px-2.5 py-1.5 bg-[#0a0d14] border border-emerald-500/40 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  >
                    {SUPPORTED_TIMEFRAMES.map((tf) => (
                      <option key={tf} value={tf}>
                        {tf}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="px-2.5 py-1.5 bg-[#0a0d14] border border-[#1e293b] rounded text-xs text-slate-200 flex items-center space-x-1.5">
                    <Clock className="w-3 h-3 text-cyan-400" />
                    <span>{timeframe}</span>
                  </div>
                )}
                {errors.timeframe && (
                  <p className="text-[10px] text-red-400 mt-1">{errors.timeframe}</p>
                )}
              </div>

              {/* Strategy Style: Editable */}
              <div>
                <label
                  htmlFor={`${modalId}-style`}
                  className="block text-[10px] text-slate-500 uppercase tracking-wider mb-1"
                >
                  Strategy Style
                </label>
                {isEditing ? (
                  <select
                    id={`${modalId}-style`}
                    value={strategyStyle}
                    onChange={(e) =>
                      setStrategyStyle(e.target.value as StrategyStyle)
                    }
                    className="w-full px-2.5 py-1.5 bg-[#0a0d14] border border-emerald-500/40 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-500 capitalize"
                  >
                    {SUPPORTED_STRATEGY_STYLES.map((style) => (
                      <option key={style} value={style}>
                        {style.replace("_", " ")}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="px-2.5 py-1.5 bg-[#0a0d14] border border-[#1e293b] rounded text-xs text-emerald-400 font-semibold uppercase">
                    {strategyStyle.replace("_", " ")}
                  </div>
                )}
                {errors.strategyStyle && (
                  <p className="text-[10px] text-red-400 mt-1">
                    {errors.strategyStyle}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* SECTION 2: Preferred Technical Indicators */}
          <div className="bg-[#131a27] border border-[#1e293b] rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400 border-b border-[#1e293b] pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-cyan-400" />
                PREFERRED TECHNICAL INDICATORS
              </span>
              <span className="text-[10px] text-slate-500">
                QUANTITATIVE VOCABULARY
              </span>
            </div>

            {isEditing ? (
              <div className="space-y-2 pt-1">
                <p className="text-[11px] text-slate-400">
                  Select indicators the agent should analyze in its reasoning cycle:
                </p>
                <div className="flex flex-wrap gap-2">
                  {SUPPORTED_INDICATORS.map((ind) => {
                    const isSelected = preferredIndicators.includes(ind);
                    return (
                      <button
                        key={ind}
                        type="button"
                        onClick={() => handleToggleIndicator(ind)}
                        className={`px-3 py-1.5 rounded text-xs font-mono border transition-all cursor-pointer ${
                          isSelected
                            ? "bg-cyan-950/60 border-cyan-500 text-cyan-300 font-semibold"
                            : "bg-[#0a0d14] border-[#1e293b] text-slate-400 hover:border-slate-600"
                        }`}
                      >
                        {ind}
                        {isSelected ? " ✓" : " +"}
                      </button>
                    );
                  })}
                </div>
                {errors.preferredIndicators && (
                  <p className="text-[10px] text-red-400">
                    {errors.preferredIndicators}
                  </p>
                )}
              </div>
            ) : (
              <div className="flex flex-wrap gap-2 pt-1">
                {preferredIndicators.map((ind) => (
                  <span
                    key={ind}
                    className="px-2.5 py-1 bg-cyan-950/30 border border-cyan-500/30 text-cyan-400 rounded text-xs font-medium"
                  >
                    {ind}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* SECTION 3: Strategic Objectives */}
          <div className="bg-[#131a27] border border-[#1e293b] rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400 border-b border-[#1e293b] pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                STRATEGIC OBJECTIVES
              </span>
              <span className="text-[10px] text-slate-500">
                {objectives.length} TARGET{objectives.length === 1 ? "" : "S"}
              </span>
            </div>

            {isEditing ? (
              <div className="space-y-2 pt-1">
                <div className="space-y-1.5">
                  {objectives.map((obj, idx) => (
                    <div
                      key={idx}
                      className="flex items-center space-x-2 bg-[#0a0d14] border border-[#1e293b] rounded p-1.5"
                    >
                      <span className="text-[10px] text-slate-500 w-4 text-center">
                        {idx + 1}
                      </span>
                      <input
                        type="text"
                        value={obj}
                        onChange={(e) => {
                          const updated = [...objectives];
                          updated[idx] = e.target.value;
                          setObjectives(updated);
                        }}
                        className="flex-1 bg-transparent text-xs text-slate-200 focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => handleRemoveObjective(idx)}
                        disabled={objectives.length <= 1}
                        className="text-slate-500 hover:text-red-400 p-1 disabled:opacity-30 cursor-pointer"
                        aria-label={`Remove objective ${idx + 1}`}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>

                {objectives.length < 10 && (
                  <div className="flex space-x-2 pt-1">
                    <input
                      type="text"
                      placeholder="Add strategic objective..."
                      value={newObjectiveDraft}
                      onChange={(e) => setNewObjectiveDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleAddObjective();
                        }
                      }}
                      className="flex-1 px-2.5 py-1.5 bg-[#0a0d14] border border-[#1e293b] rounded text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-emerald-500/50"
                    />
                    <button
                      type="button"
                      onClick={handleAddObjective}
                      className="px-3 py-1.5 bg-[#1e293b] hover:bg-[#283548] text-slate-200 rounded text-xs flex items-center space-x-1 cursor-pointer"
                    >
                      <Plus className="w-3 h-3" />
                      <span>Add</span>
                    </button>
                  </div>
                )}
                {errors.objectives && (
                  <p className="text-[10px] text-red-400">{errors.objectives}</p>
                )}
              </div>
            ) : (
              <ul className="space-y-1.5 pt-1">
                {objectives.map((obj, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-slate-300 flex items-start space-x-2 bg-[#0a0d14] border border-[#1e293b]/60 rounded px-2.5 py-1.5"
                  >
                    <span className="text-emerald-400 font-bold">›</span>
                    <span>{obj}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* SECTION 4: Risk Boundaries & Limits */}
          <div className="bg-[#131a27] border border-[#1e293b] rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400 border-b border-[#1e293b] pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Percent className="w-3.5 h-3.5 text-amber-400" />
                QUANTITATIVE RISK BOUNDARIES
              </span>
              <span className="text-[10px] text-slate-500">
                DETERMINISTIC LIMITS
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              {/* Risk Per Trade */}
              <div className="bg-[#0a0d14] border border-[#1e293b] rounded p-2.5">
                <label
                  htmlFor={`${modalId}-risk`}
                  className="block text-[10px] text-slate-400 uppercase tracking-wider mb-1"
                >
                  Risk / Trade
                </label>
                {isEditing ? (
                  <div className="relative">
                    <input
                      id={`${modalId}-risk`}
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="10.0"
                      value={riskPerTrade}
                      onChange={(e) => setRiskPerTrade(e.target.value)}
                      className="w-full px-2 py-1 bg-[#131a27] border border-amber-500/40 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500 pr-5"
                    />
                    <span className="absolute right-2 top-1 text-xs text-slate-500">
                      %
                    </span>
                  </div>
                ) : (
                  <div className="text-sm font-bold text-amber-400">
                    {Number(riskPerTrade).toFixed(1)}%
                    <span className="text-[10px] text-slate-500 ml-1 font-normal">
                      (₹
                      {Math.round(
                        (initialCapital * Number(riskPerTrade)) / 100
                      ).toLocaleString("en-IN")}
                      )
                    </span>
                  </div>
                )}
                {errors.riskPerTrade && (
                  <p className="text-[10px] text-red-400 mt-1">
                    {errors.riskPerTrade}
                  </p>
                )}
              </div>

              {/* Max Position Exposure */}
              <div className="bg-[#0a0d14] border border-[#1e293b] rounded p-2.5">
                <label
                  htmlFor={`${modalId}-exposure`}
                  className="block text-[10px] text-slate-400 uppercase tracking-wider mb-1"
                >
                  Max Exposure
                </label>
                {isEditing ? (
                  <div className="relative">
                    <input
                      id={`${modalId}-exposure`}
                      type="number"
                      step="1.0"
                      min="1.0"
                      max="100.0"
                      value={positionExposure}
                      onChange={(e) => setPositionExposure(e.target.value)}
                      className="w-full px-2 py-1 bg-[#131a27] border border-amber-500/40 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500 pr-5"
                    />
                    <span className="absolute right-2 top-1 text-xs text-slate-500">
                      %
                    </span>
                  </div>
                ) : (
                  <div className="text-sm font-bold text-slate-200">
                    {Number(positionExposure).toFixed(1)}%
                    <span className="text-[10px] text-slate-500 ml-1 font-normal">
                      (₹
                      {Math.round(
                        (initialCapital * Number(positionExposure)) / 100
                      ).toLocaleString("en-IN")}
                      )
                    </span>
                  </div>
                )}
                {errors.positionExposure && (
                  <p className="text-[10px] text-red-400 mt-1">
                    {errors.positionExposure}
                  </p>
                )}
              </div>

              {/* Max Daily Loss */}
              <div className="bg-[#0a0d14] border border-[#1e293b] rounded p-2.5">
                <label
                  htmlFor={`${modalId}-daily-loss`}
                  className="block text-[10px] text-slate-400 uppercase tracking-wider mb-1"
                >
                  Daily Loss Limit
                </label>
                {isEditing ? (
                  <div className="relative">
                    <input
                      id={`${modalId}-daily-loss`}
                      type="number"
                      step="0.5"
                      min="1.0"
                      max="50.0"
                      value={dailyLoss}
                      onChange={(e) => setDailyLoss(e.target.value)}
                      className="w-full px-2 py-1 bg-[#131a27] border border-amber-500/40 rounded text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500 pr-5"
                    />
                    <span className="absolute right-2 top-1 text-xs text-slate-500">
                      %
                    </span>
                  </div>
                ) : (
                  <div className="text-sm font-bold text-red-400">
                    {Number(dailyLoss).toFixed(1)}%
                    <span className="text-[10px] text-slate-500 ml-1 font-normal">
                      (₹
                      {Math.round(
                        (initialCapital * Number(dailyLoss)) / 100
                      ).toLocaleString("en-IN")}
                      )
                    </span>
                  </div>
                )}
                {errors.dailyLoss && (
                  <p className="text-[10px] text-red-400 mt-1">
                    {errors.dailyLoss}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* SECTION 5: Strategic Rationale (Read-Only) */}
          <div className="bg-[#131a27] border border-[#1e293b] rounded-lg p-4 space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400 border-b border-[#1e293b] pb-2">
              <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-amber-400" />
                TRANSLATION RATIONALE (READ-ONLY)
              </span>
              <span className="text-[10px] text-slate-500">
                PERSISTED SUMMARY
              </span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed pt-1 italic bg-[#0a0d14] border border-[#1e293b]/60 rounded p-3">
              {mandate.rationale
                ? mandate.rationale
                : "Quantitative mandate translated deterministically from natural language specification."}
            </p>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-[#1e293b] bg-[#131a27] flex flex-wrap items-center justify-between gap-3">
          {isEditing ? (
            /* Edit Mode Actions */
            <div className="w-full flex items-center justify-between">
              <button
                type="button"
                onClick={handleDiscardEdits}
                className="px-3 py-1.5 bg-[#1e293b] hover:bg-[#283548] text-slate-300 rounded text-xs transition-colors cursor-pointer"
              >
                Discard Changes
              </button>
              <div className="flex items-center space-x-2">
                <button
                  type="button"
                  onClick={() => setIsEditing(false)}
                  className="px-3 py-1.5 text-slate-400 hover:text-slate-200 text-xs transition-colors cursor-pointer"
                >
                  Cancel Edit
                </button>
                <button
                  type="button"
                  onClick={handleApplyEdits}
                  className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-slate-900 font-semibold rounded text-xs flex items-center space-x-1.5 transition-colors cursor-pointer"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Apply Edits</span>
                </button>
              </div>
            </div>
          ) : (
            /* Review Mode Actions (Specification Section 12 required buttons) */
            <>
              <div className="flex items-center space-x-2">
                {onRevisePrompt && (
                  <button
                    type="button"
                    onClick={onRevisePrompt}
                    disabled={isConfirming}
                    className="px-3 py-1.5 bg-[#182030] hover:bg-[#1e293b] text-slate-300 border border-[#1e293b] rounded text-xs flex items-center space-x-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  >
                    <ArrowLeft className="w-3 h-3" />
                    <span>Revise Prompt</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setIsEditing(true)}
                  disabled={isConfirming}
                  className="px-3 py-1.5 bg-[#182030] hover:bg-[#1e293b] text-slate-200 border border-slate-700 rounded text-xs flex items-center space-x-1.5 transition-colors cursor-pointer disabled:opacity-50"
                >
                  <Edit3 className="w-3 h-3 text-cyan-400" />
                  <span>EDIT</span>
                </button>
              </div>

              <div className="flex items-center space-x-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isConfirming}
                  className="px-3 py-1.5 text-slate-400 hover:text-slate-200 text-xs transition-colors cursor-pointer disabled:opacity-50"
                >
                  Cancel
                </button>

                {/* Explicit Start Simulation / Confirm Action */}
                <button
                  type="button"
                  onClick={handleConfirmAndStart}
                  disabled={isConfirming}
                  className="px-4 py-1.5 bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold rounded text-xs flex items-center space-x-1.5 shadow-lg shadow-emerald-900/30 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isConfirming ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Starting Simulation...</span>
                    </>
                  ) : (
                    <>
                      <Zap className="w-3.5 h-3.5 fill-current" />
                      <span>START SIMULATION</span>
                    </>
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
