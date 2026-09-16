import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MandateReviewModal } from "../components/MandateReviewModal";
import { AgentMandate, SUPPORTED_INDICATORS, SUPPORTED_TIMEFRAMES } from "../types";

describe("Phase 9B — MandateReviewModal", () => {
  const sampleMandate: AgentMandate = {
    strategy_style: "momentum",
    objectives: [
      "Capture bullish momentum breakouts",
      "Avoid choppy sideways consolidation",
    ],
    preferred_indicators: ["EMA9", "EMA20", "RSI14", "MACD"],
    instrument: "RELIANCE",
    timeframe: "15m",
    risk_per_trade: 0.02, // 2%
    max_position_exposure: 0.25, // 25%
    max_daily_loss: 0.05, // 5%
    rationale: "Translates momentum prompt into EMA trend filter with RSI confirmation.",
  };

  const defaultProps = {
    isOpen: true,
    mandate: sampleMandate,
    agentName: "Reliance Momentum Bot",
    initialCapital: 100000,
    onClose: vi.fn(),
    onRevisePrompt: vi.fn(),
    onConfirm: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 1. Review screen renders the complete returned AgentMandate
  it("renders the complete returned AgentMandate and context", () => {
    render(<MandateReviewModal {...defaultProps} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("AGENT MANDATE REVIEW")).toBeInTheDocument();
    expect(screen.getByText("Reliance Momentum Bot")).toBeInTheDocument();
    expect(screen.getByText("₹1,00,000")).toBeInTheDocument();
    expect(screen.getAllByText("RELIANCE").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("momentum")).toBeInTheDocument();
    expect(screen.getByText("15m")).toBeInTheDocument();
    expect(screen.getByText("Capture bullish momentum breakouts")).toBeInTheDocument();
    expect(screen.getByText("Avoid choppy sideways consolidation")).toBeInTheDocument();
    expect(screen.getByText("EMA9")).toBeInTheDocument();
    expect(screen.getByText("EMA20")).toBeInTheDocument();
    expect(screen.getByText("RSI14")).toBeInTheDocument();
    expect(screen.getByText("MACD")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Translates momentum prompt into EMA trend filter with RSI confirmation."
      )
    ).toBeInTheDocument();

    // Required buttons from Specification Section 12
    expect(screen.getByRole("button", { name: /EDIT/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /START SIMULATION/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
  });

  // 2. Generated mandate values are displayed accurately
  it("displays numerical risk percentages accurately converted from backend fractions", () => {
    render(<MandateReviewModal {...defaultProps} />);

    // 0.02 -> 2.0%, 0.25 -> 25.0%, 0.05 -> 5.0%
    expect(screen.getByText(/2\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/25\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/^5\.0%/)).toBeInTheDocument();

    // INR monetary projections based on initial capital ₹100,000
    expect(screen.getByText(/₹2,000/)).toBeInTheDocument(); // 2% of 100,000
    expect(screen.getByText(/₹25,000/)).toBeInTheDocument(); // 25% of 100,000
    expect(screen.getByText(/₹5,000/)).toBeInTheDocument(); // 5% of 100,000
  });

  // 3. Editable fields are actually editable
  it("allows switching to edit mode and updating editable fields", async () => {
    render(<MandateReviewModal {...defaultProps} />);

    // Click EDIT
    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));
    expect(screen.getByText("EDIT MODE")).toBeInTheDocument();

    // Edit Strategy Style
    const styleSelect = screen.getByLabelText(/Strategy Style/i);
    fireEvent.change(styleSelect, { target: { value: "trend_following" } });

    // Edit Timeframe
    const tfSelect = screen.getByLabelText(/Timeframe/i);
    fireEvent.change(tfSelect, { target: { value: "5m" } });

    // Edit Risk Per Trade
    const riskInput = screen.getByLabelText(/Risk \/ Trade/i);
    fireEvent.change(riskInput, { target: { value: "1.5" } });

    // Edit Max Exposure
    const expInput = screen.getByLabelText(/Max Exposure/i);
    fireEvent.change(expInput, { target: { value: "30.0" } });

    // Edit Daily Loss
    const lossInput = screen.getByLabelText(/Daily Loss Limit/i);
    fireEvent.change(lossInput, { target: { value: "4.0" } });

    // Toggle indicator (remove MACD, add SMA50)
    fireEvent.click(screen.getByRole("button", { name: /MACD/i }));
    fireEvent.click(screen.getByRole("button", { name: /SMA50/i }));

    // Apply Edits
    fireEvent.click(screen.getByRole("button", { name: /Apply Edits/i }));

    // Back in review mode: verify updated values are displayed
    expect(screen.queryByText("EDIT MODE")).not.toBeInTheDocument();
    expect(screen.getByText("trend following")).toBeInTheDocument();
    expect(screen.getByText("5m")).toBeInTheDocument();
    expect(screen.getByText(/1\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/30\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/4\.0%/)).toBeInTheDocument();
    expect(screen.getByText("SMA50")).toBeInTheDocument();
    expect(screen.queryByText("MACD")).not.toBeInTheDocument();
  });

  // 4. Immutable fields cannot be edited
  it("strictly renders instrument and rationale as immutable across all modes", () => {
    render(<MandateReviewModal {...defaultProps} />);

    // In Review Mode: instrument is locked
    expect(screen.getByText("LOCKED")).toBeInTheDocument();
    expect(screen.getAllByText("RELIANCE").length).toBeGreaterThanOrEqual(1);

    // Switch to Edit Mode
    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));

    // Instrument remains locked with no input/select controls
    expect(screen.getByText("LOCKED")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Instrument/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Instrument/i })).not.toBeInTheDocument();

    // Rationale remains read-only
    expect(screen.getByText(/TRANSLATION RATIONALE \(READ-ONLY\)/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /rationale/i })
    ).not.toBeInTheDocument();
  });

  // 5. Supported vocabulary constraints remain enforced
  it("constrains timeframes and indicators strictly to supported vocabularies in edit mode", () => {
    render(<MandateReviewModal {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));

    // Check timeframe select options
    const tfSelect = screen.getByLabelText(/Timeframe/i) as HTMLSelectElement;
    const tfOptions = Array.from(tfSelect.options).map((o) => o.value);
    expect(tfOptions).toEqual([...SUPPORTED_TIMEFRAMES]);

    // Check supported indicators available to toggle
    for (const ind of SUPPORTED_INDICATORS) {
      expect(screen.getByRole("button", { name: new RegExp(ind, "i") })).toBeInTheDocument();
    }
  });

  // 6. Numeric/risk validation works at boundaries
  it("enforces boundary limits on numeric risk fields in edit mode", async () => {
    render(<MandateReviewModal {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));

    // Boundary violations
    fireEvent.change(screen.getByLabelText(/Risk \/ Trade/i), {
      target: { value: "15.0" }, // > 10%
    });
    fireEvent.change(screen.getByLabelText(/Max Exposure/i), {
      target: { value: "0.5" }, // < 1%
    });
    fireEvent.change(screen.getByLabelText(/Daily Loss Limit/i), {
      target: { value: "60.0" }, // > 50%
    });

    fireEvent.click(screen.getByRole("button", { name: /Apply Edits/i }));

    expect(
      await screen.findByText(/Risk per trade must be between 0.1% and 10.0%/i)
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Position exposure must be between 1.0% and 100.0%/i)
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Daily loss limit must be between 1.0% and 50.0%/i)
    ).toBeInTheDocument();

    // Modal stays in edit mode on failure
    expect(screen.getByText("EDIT MODE")).toBeInTheDocument();
  });

  // 7. Invalid edits block confirmation
  it("blocks confirmation when indicators list is emptied or objective list is empty", async () => {
    render(<MandateReviewModal {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));

    // Deselect all selected indicators
    fireEvent.click(screen.getByRole("button", { name: /EMA9/i }));
    fireEvent.click(screen.getByRole("button", { name: /EMA20/i }));
    fireEvent.click(screen.getByRole("button", { name: /RSI14/i }));
    fireEvent.click(screen.getByRole("button", { name: /MACD/i }));

    fireEvent.click(screen.getByRole("button", { name: /Apply Edits/i }));

    expect(
      await screen.findByText(/At least one preferred indicator must be selected/i)
    ).toBeInTheDocument();
    expect(defaultProps.onConfirm).not.toHaveBeenCalled();
  });

  // 8. Valid edits produce exactly the expected confirmed payload
  it("compiles and submits clean ConfirmedAgentMandate with decimal fractions upon confirmation", async () => {
    render(<MandateReviewModal {...defaultProps} />);

    // Switch to edit mode and change risk to 1.5% and timeframe to 5m
    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));
    fireEvent.change(screen.getByLabelText(/Timeframe/i), {
      target: { value: "5m" },
    });
    fireEvent.change(screen.getByLabelText(/Risk \/ Trade/i), {
      target: { value: "1.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply Edits/i }));

    // Click START SIMULATION
    const startBtn = screen.getByRole("button", { name: /START SIMULATION/i });
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(defaultProps.onConfirm).toHaveBeenCalledTimes(1);
    });

    expect(defaultProps.onConfirm).toHaveBeenCalledWith({
      agent_name: "Reliance Momentum Bot",
      initial_capital: 100000,
      mandate: {
        strategy_style: "momentum",
        objectives: [
          "Capture bullish momentum breakouts",
          "Avoid choppy sideways consolidation",
        ],
        preferred_indicators: ["EMA9", "EMA20", "RSI14", "MACD"],
        instrument: "RELIANCE",
        timeframe: "5m",
        risk_per_trade: 0.015, // 1.5% -> 0.015
        max_position_exposure: 0.25, // 25% -> 0.25
        max_daily_loss: 0.05, // 5% -> 0.05
        rationale:
          "Translates momentum prompt into EMA trend filter with RSI confirmation.",
      },
    });

    expect(defaultProps.onClose).toHaveBeenCalledTimes(1);
  });

  // 9. Confirm button prevents duplicate submission
  it("prevents duplicate confirmation calls while async operation is in flight", async () => {
    let resolveConfirm: () => void = () => {};
    const pendingConfirm = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveConfirm = resolve;
        })
    );

    render(<MandateReviewModal {...defaultProps} onConfirm={pendingConfirm} />);

    const startBtn = screen.getByRole("button", { name: /START SIMULATION/i });
    fireEvent.click(startBtn);

    expect(startBtn).toBeDisabled();
    expect(screen.getByText(/Starting Simulation.../i)).toBeInTheDocument();

    // Click again while in-flight
    fireEvent.click(startBtn);
    expect(pendingConfirm).toHaveBeenCalledTimes(1);

    // Resolve confirm
    resolveConfirm();
    await waitFor(() => {
      expect(defaultProps.onClose).toHaveBeenCalledTimes(1);
    });
  });

  // 10. Loading state is shown during confirmation
  it("displays loading spinner and text while confirming", async () => {
    const neverEndingConfirm = vi.fn().mockReturnValue(new Promise(() => {}));

    render(
      <MandateReviewModal {...defaultProps} onConfirm={neverEndingConfirm} />
    );

    const startBtn = screen.getByRole("button", { name: /START SIMULATION/i });
    fireEvent.click(startBtn);

    expect(startBtn).toBeDisabled();
    expect(screen.getByText("Starting Simulation...")).toBeInTheDocument();
  });

  // 11. API failure preserves the user's reviewed/edited state
  it("surfaces confirmation error without losing reviewed or edited parameters", async () => {
    const failingConfirm = vi
      .fn()
      .mockRejectedValue(new Error("503 Service Unavailable: Simulation Engine busy"));

    render(<MandateReviewModal {...defaultProps} onConfirm={failingConfirm} />);

    const startBtn = screen.getByRole("button", { name: /START SIMULATION/i });
    fireEvent.click(startBtn);

    expect(
      await screen.findByText(/503 Service Unavailable: Simulation Engine busy/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Your reviewed configuration has been preserved/i)
    ).toBeInTheDocument();

    // Modal did not close
    expect(defaultProps.onClose).not.toHaveBeenCalled();

    // Reviewed values remain intact
    expect(screen.getByText("Reliance Momentum Bot")).toBeInTheDocument();
    expect(screen.getByText(/2\.0%/)).toBeInTheDocument();
  });

  // 12. Cancel/back behavior does not accidentally confirm
  it("does not trigger confirmation on Cancel, Revise Prompt, or Escape key", () => {
    render(<MandateReviewModal {...defaultProps} />);

    // Revise Prompt button
    const reviseBtn = screen.getByRole("button", { name: /Revise Prompt/i });
    fireEvent.click(reviseBtn);
    expect(defaultProps.onRevisePrompt).toHaveBeenCalledTimes(1);
    expect(defaultProps.onConfirm).not.toHaveBeenCalled();

    // Cancel button
    const cancelBtn = screen.getByRole("button", { name: /Cancel/i });
    fireEvent.click(cancelBtn);
    expect(defaultProps.onClose).toHaveBeenCalledTimes(1);
    expect(defaultProps.onConfirm).not.toHaveBeenCalled();

    // Escape key
    fireEvent.keyDown(window, { key: "Escape" });
    expect(defaultProps.onClose).toHaveBeenCalledTimes(2);
    expect(defaultProps.onConfirm).not.toHaveBeenCalled();
  });

  // 13. No private chain-of-thought is rendered
  it("does not render or expose internal chain-of-thought or reasoning artifacts", () => {
    const mandateWithCoT = {
      ...sampleMandate,
      chain_of_thought: "Thinking Process: 1. User wants momentum...",
      internal_reasoning: "Step 1: Analyzed 15m candles...",
    };

    render(<MandateReviewModal {...defaultProps} mandate={mandateWithCoT as any} />);

    expect(screen.queryByText(/Thinking Process/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/internal_reasoning/i)).not.toBeInTheDocument();
    // Persisted rationale IS shown
    expect(
      screen.getByText(
        "Translates momentum prompt into EMA trend filter with RSI confirmation."
      )
    ).toBeInTheDocument();
  });

  // 14. Accessibility semantics are correct
  it("implements complete ARIA dialog attributes and label associations", () => {
    render(<MandateReviewModal {...defaultProps} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby");
    expect(dialog).toHaveAttribute("aria-describedby");

    const labelId = dialog.getAttribute("aria-labelledby");
    expect(document.getElementById(labelId!)).toHaveTextContent("AGENT MANDATE REVIEW");
  });

  // 15. Discard changes restores originally generated mandate in edit mode
  it("restores original mandate parameters when Discard Changes is clicked", () => {
    render(<MandateReviewModal {...defaultProps} />);

    // Enter edit mode
    fireEvent.click(screen.getByRole("button", { name: /EDIT/i }));

    // Modify risk
    fireEvent.change(screen.getByLabelText(/Risk \/ Trade/i), {
      target: { value: "8.5" },
    });

    // Click Discard Changes
    fireEvent.click(screen.getByRole("button", { name: /Discard Changes/i }));

    // Back in review mode: original 2.0% is restored
    expect(screen.queryByText("EDIT MODE")).not.toBeInTheDocument();
    expect(screen.getByText(/2\.0%/)).toBeInTheDocument();
  });
});
