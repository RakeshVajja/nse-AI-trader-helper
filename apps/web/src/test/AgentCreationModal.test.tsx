import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AgentCreationModal } from "../components/AgentCreationModal";
import { SUPPORTED_EQUITIES, SUPPORTED_INDICES, SUPPORTED_TIMEFRAMES } from "../types";

describe("Phase 9A — AgentCreationModal", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onSubmit: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 1. Form renders all required fields
  it("renders all required form fields with clear labels and descriptors", () => {
    render(<AgentCreationModal {...defaultProps} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("INITIALIZE AI TRADING AGENT")).toBeInTheDocument();

    // Fields
    expect(screen.getByLabelText(/AGENT NAME/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/TARGET INSTRUMENT/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/EXECUTION TIMEFRAME/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/INITIAL VIRTUAL CAPITAL/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/RISK \/ TRADE/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/MAX EXPOSURE/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/DAILY LOSS LIMIT/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/NATURAL LANGUAGE STRATEGY PROMPT/i)).toBeInTheDocument();

    // Submit and cancel buttons
    expect(
      screen.getByRole("button", { name: /Generate Strategy Mandate/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cancel/i })).toBeInTheDocument();
  });

  // 2. Correct defaults are displayed
  it("displays authoritative defaults aligned with backend contracts", () => {
    render(<AgentCreationModal {...defaultProps} />);

    expect(screen.getByLabelText(/TARGET INSTRUMENT/i)).toHaveValue("RELIANCE");
    expect(screen.getByLabelText(/EXECUTION TIMEFRAME/i)).toHaveValue("15m");
    expect(screen.getByLabelText(/INITIAL VIRTUAL CAPITAL/i)).toHaveValue(100000);
    expect(screen.getByLabelText(/RISK \/ TRADE/i)).toHaveValue(2);
    expect(screen.getByLabelText(/MAX EXPOSURE/i)).toHaveValue(25);
    expect(screen.getByLabelText(/DAILY LOSS LIMIT/i)).toHaveValue(5);
  });

  // 3. Required text validation works
  it("validates required agent name and strategy prompt text", async () => {
    render(<AgentCreationModal {...defaultProps} />);

    const submitBtn = screen.getByRole("button", { name: /Generate Strategy Mandate/i });
    fireEvent.click(submitBtn);

    expect(await screen.findByText(/Agent name is required/i)).toBeInTheDocument();
    expect(
      await screen.findByText(/Natural language strategy prompt is required/i)
    ).toBeInTheDocument();
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();

    // Test prompt shorter than 3 characters
    fireEvent.change(screen.getByLabelText(/AGENT NAME/i), {
      target: { value: "Momentum Bot" },
    });
    fireEvent.change(screen.getByLabelText(/NATURAL LANGUAGE STRATEGY PROMPT/i), {
      target: { value: "Hi" },
    });
    fireEvent.click(submitBtn);

    expect(
      await screen.findByText(/Strategy prompt must be at least 3 characters/i)
    ).toBeInTheDocument();
    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  // 4. Numerical/range validation works
  it("enforces numeric range constraints on capital and risk limits", async () => {
    render(<AgentCreationModal {...defaultProps} />);

    fireEvent.change(screen.getByLabelText(/AGENT NAME/i), {
      target: { value: "Boundary Agent" },
    });
    fireEvent.change(screen.getByLabelText(/NATURAL LANGUAGE STRATEGY PROMPT/i), {
      target: { value: "Valid momentum strategy text here." },
    });

    // Negative initial capital
    fireEvent.change(screen.getByLabelText(/INITIAL VIRTUAL CAPITAL/i), {
      target: { value: -500 },
    });
    // Excessive risk per trade (> 10%)
    fireEvent.change(screen.getByLabelText(/RISK \/ TRADE/i), {
      target: { value: 15.0 },
    });
    // Excessive exposure (> 100%)
    fireEvent.change(screen.getByLabelText(/MAX EXPOSURE/i), {
      target: { value: 150.0 },
    });
    // Excessive daily loss (> 50%)
    fireEvent.change(screen.getByLabelText(/DAILY LOSS LIMIT/i), {
      target: { value: 75.0 },
    });

    const submitBtn = screen.getByRole("button", { name: /Generate Strategy Mandate/i });
    fireEvent.click(submitBtn);

    expect(
      await screen.findByText(/Initial capital must be greater than ₹0/i)
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Risk per trade must be between 0.1% and 10.0%/i)
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Position exposure must be between 1.0% and 100.0%/i)
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Daily loss limit must be between 1.0% and 50.0%/i)
    ).toBeInTheDocument();

    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  // 5. Constrained selects reject/avoid unsupported values
  it("restricts instrument and timeframe options strictly to supported vocabularies", () => {
    render(<AgentCreationModal {...defaultProps} />);

    const instSelect = screen.getByLabelText(/TARGET INSTRUMENT/i) as HTMLSelectElement;
    const optionValues = Array.from(instSelect.options).map((o) => o.value);

    // Verify all 7 equities and 3 indices are present
    for (const eq of SUPPORTED_EQUITIES) {
      expect(optionValues).toContain(eq);
    }
    for (const idx of SUPPORTED_INDICES) {
      expect(optionValues).toContain(idx);
    }
    expect(optionValues.length).toBe(10);

    const tfSelect = screen.getByLabelText(/EXECUTION TIMEFRAME/i) as HTMLSelectElement;
    const tfValues = Array.from(tfSelect.options).map((o) => o.value);
    for (const tf of SUPPORTED_TIMEFRAMES) {
      expect(tfValues).toContain(tf);
    }
    expect(tfValues.length).toBe(5);
  });

  // 6. Invalid submission is blocked
  it("blocks submission and preserves user inputs on error", () => {
    render(<AgentCreationModal {...defaultProps} />);

    fireEvent.change(screen.getByLabelText(/AGENT NAME/i), {
      target: { value: "Test Agent" },
    });
    // Leave strategy prompt blank
    const submitBtn = screen.getByRole("button", { name: /Generate Strategy Mandate/i });
    fireEvent.click(submitBtn);

    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
    // Agent name should remain preserved in input
    expect(screen.getByLabelText(/AGENT NAME/i)).toHaveValue("Test Agent");
  });

  // 7. Valid submission produces exactly the expected request payload/state
  it("compiles and submits clean AgentMandateCreateRequest payload with correct percentage decimals", async () => {
    render(<AgentCreationModal {...defaultProps} />);

    fireEvent.change(screen.getByLabelText(/AGENT NAME/i), {
      target: { value: "  TCS Trend Follower  " },
    });
    fireEvent.change(screen.getByLabelText(/TARGET INSTRUMENT/i), {
      target: { value: "TCS" },
    });
    fireEvent.change(screen.getByLabelText(/EXECUTION TIMEFRAME/i), {
      target: { value: "5m" },
    });
    fireEvent.change(screen.getByLabelText(/INITIAL VIRTUAL CAPITAL/i), {
      target: { value: 250000 },
    });
    fireEvent.change(screen.getByLabelText(/RISK \/ TRADE/i), {
      target: { value: 1.5 },
    });
    fireEvent.change(screen.getByLabelText(/MAX EXPOSURE/i), {
      target: { value: 20.0 },
    });
    fireEvent.change(screen.getByLabelText(/DAILY LOSS LIMIT/i), {
      target: { value: 4.0 },
    });
    fireEvent.change(screen.getByLabelText(/NATURAL LANGUAGE STRATEGY PROMPT/i), {
      target: {
        value:
          "  I want a trend following strategy for TCS on 5m candles. Buy above EMA20 with RSI above 50.  ",
      },
    });

    const submitBtn = screen.getByRole("button", { name: /Generate Strategy Mandate/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(defaultProps.onSubmit).toHaveBeenCalledTimes(1);
    });

    expect(defaultProps.onSubmit).toHaveBeenCalledWith({
      agent_name: "TCS Trend Follower",
      instrument: "TCS",
      timeframe: "5m",
      initial_capital: 250000,
      max_risk_per_trade: 0.015, // 1.5% -> 0.015
      max_position_exposure: 0.20, // 20% -> 0.20
      max_daily_loss: 0.04, // 4% -> 0.04
      strategy_prompt:
        "I want a trend following strategy for TCS on 5m candles. Buy above EMA20 with RSI above 50.",
    });

    expect(defaultProps.onClose).toHaveBeenCalledTimes(1);
  });

  // 8. Loading/submitting state prevents duplicate submission
  it("disables submit button and shows spinner during async submission", async () => {
    let resolveSubmit: () => void = () => {};
    const pendingSubmit = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveSubmit = resolve;
        })
    );

    render(<AgentCreationModal {...defaultProps} onSubmit={pendingSubmit} />);

    fireEvent.change(screen.getByLabelText(/AGENT NAME/i), {
      target: { value: "Async Agent" },
    });
    fireEvent.change(screen.getByLabelText(/NATURAL LANGUAGE STRATEGY PROMPT/i), {
      target: { value: "Long momentum strategy on breakout." },
    });

    const submitBtn = screen.getByRole("button", { name: /Generate Strategy Mandate/i });
    fireEvent.click(submitBtn);

    // Button should enter loading state and become disabled
    expect(submitBtn).toBeDisabled();
    expect(screen.getByText(/Compiling Mandate.../i)).toBeInTheDocument();

    // Clicking again should not trigger a second call
    fireEvent.click(submitBtn);
    expect(pendingSubmit).toHaveBeenCalledTimes(1);

    // Resolve submission
    resolveSubmit();
    await waitFor(() => {
      expect(defaultProps.onClose).toHaveBeenCalled();
    });
  });

  // 9. Cancel/close behavior works
  it("triggers onClose when clicking Cancel button, Close icon, or pressing Escape", () => {
    const { rerender } = render(<AgentCreationModal {...defaultProps} />);

    // Cancel button
    const cancelBtn = screen.getByRole("button", { name: /Cancel/i });
    fireEvent.click(cancelBtn);
    expect(defaultProps.onClose).toHaveBeenCalledTimes(1);

    // Close X button
    const closeIconBtn = screen.getByLabelText(/Close modal/i);
    fireEvent.click(closeIconBtn);
    expect(defaultProps.onClose).toHaveBeenCalledTimes(2);

    // Escape key
    fireEvent.keyDown(window, { key: "Escape" });
    expect(defaultProps.onClose).toHaveBeenCalledTimes(3);

    // Not open -> renders nothing
    rerender(<AgentCreationModal {...defaultProps} isOpen={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  // 10. Specification-required accessibility behavior
  it("provides correct ARIA dialog roles and accessibility labels", () => {
    render(<AgentCreationModal {...defaultProps} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby");
    expect(dialog).toHaveAttribute("aria-describedby");

    const labelId = dialog.getAttribute("aria-labelledby");
    expect(document.getElementById(labelId!)).toHaveTextContent("INITIALIZE AI TRADING AGENT");
  });

  // 11. Active terminal props fallback if unsupported values are provided
  it("safely falls back to RELIANCE and 15m if props provide unsupported values", () => {
    render(
      <AgentCreationModal
        {...defaultProps}
        defaultSymbol={"INVALID_TICKER" as any}
        defaultTimeframe={"99h" as any}
      />
    );

    expect(screen.getByLabelText(/TARGET INSTRUMENT/i)).toHaveValue("RELIANCE");
    expect(screen.getByLabelText(/EXECUTION TIMEFRAME/i)).toHaveValue("15m");
  });
});
