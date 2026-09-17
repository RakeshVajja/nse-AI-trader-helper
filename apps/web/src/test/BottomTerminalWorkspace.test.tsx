import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { BottomTerminalWorkspace } from "../components/BottomTerminalWorkspace";
import { ActivityFeed } from "../components/ActivityFeed";
import { TradeLog } from "../components/TradeLog";
import { PerformancePanel } from "../components/PerformancePanel";
import {
  formatSimulationEventToActivity,
  formatOrderExecutedToTrade,
  formatApiTradeToLogEntry,
  mapApiPerformanceToMetrics,
  formatINR,
  formatTimeDisplay,
  ActivityItem,
  TradeLogEntry,
  SimulationPerformanceMetrics,
  ApiTradeResponse,
  ApiPerformanceMetricsResponse,
} from "../types/simulation-terminal";
import { SimulationEvent } from "../types";


describe("Phase 10D: Bottom Terminal Workspace & Components", () => {
  // ---------------------------------------------------------------------------
  // 1. Pure Event Converters & Signal vs Execution Demarcation
  // ---------------------------------------------------------------------------
  describe("Event Converters & Demarcation", () => {
    it("converts agent_started, agent_analyzing, tool_call, and agent_decision to activity items", () => {
      const startedEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 1,
        event_type: "agent_started",
        wall_clock_timestamp: "2026-09-17T10:00:00Z",
        virtual_timestamp: "2026-09-17T09:15:00Z",
        payload: {
          agent_id: "agent-1",
          agent_name: "Reliance Momentum",
          status: "RUNNING",
          strategy_style: "MOMENTUM",
        },
      };
      const act1 = formatSimulationEventToActivity(startedEvent);
      expect(act1).not.toBeNull();
      expect(act1?.category).toBe("SYSTEM");
      expect(act1?.title).toBe("Agent Started");
      expect(act1?.description).toContain("Reliance Momentum");

      const decisionEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 2,
        event_type: "agent_decision",
        wall_clock_timestamp: "2026-09-17T10:01:00Z",
        virtual_timestamp: "2026-09-17T09:30:00Z",
        payload: {
          action: "BUY",
          confidence: 0.85,
          reason: "EMA9 crossed above EMA20",
        },
      };
      const act2 = formatSimulationEventToActivity(decisionEvent);
      expect(act2?.category).toBe("SIGNAL");
      expect(act2?.title).toBe("Decision: BUY");
      expect(act2?.description).toContain("85%");
      expect(act2?.description).toContain("EMA9 crossed above EMA20");
    });

    it("strictly refuses to fabricate a TradeLogEntry from an agent_decision signal", () => {
      const decisionEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 5,
        event_type: "agent_decision",
        wall_clock_timestamp: "2026-09-17T10:02:00Z",
        payload: {
          action: "BUY",
          confidence: 0.9,
          reason: "Strong breakout",
        },
      };

      // Demarcation test: Signals must NEVER produce trade log entries
      const trade = formatOrderExecutedToTrade(decisionEvent, "RELIANCE");
      expect(trade).toBeNull();
    });

    it("converts only authoritative order_executed FILLED events to TradeLogEntry", () => {
      const fillEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 8,
        event_type: "order_executed",
        virtual_timestamp: "2026-09-17T09:30:00Z",
        wall_clock_timestamp: "2026-09-17T10:02:00Z",
        payload: {
          order_id: "ord-123",
          trade_id: "trd-456",
          side: "BUY",
          quantity: 25,
          execution_price: 2450.5,
          slippage_cost: 12.5,
          transaction_cost: 15.0,
          status: "FILLED",
          is_auto_exit: false,
        },
      };

      const trade = formatOrderExecutedToTrade(fillEvent, "RELIANCE");
      expect(trade).not.toBeNull();
      expect(trade?.id).toBe("trd-456");
      expect(trade?.side).toBe("BUY");
      expect(trade?.quantity).toBe(25);
      expect(trade?.executionPrice).toBe(2450.5);
      expect(trade?.transactionCost).toBe(15.0);
      expect(trade?.slippageCost).toBe(12.5);
      expect(trade?.status).toBe("FILLED");

      // REJECTED order should not be added to trade log
      const rejectedEvent: SimulationEvent = {
        ...fillEvent,
        payload: { ...fillEvent.payload, status: "REJECTED" },
      };
      expect(formatOrderExecutedToTrade(rejectedEvent)).toBeNull();
    });

    it("ignores candle_update events from activity log to prevent high-frequency flooding", () => {
      const candleEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 20,
        event_type: "candle_update",
        wall_clock_timestamp: "2026-09-17T10:05:00Z",
        payload: {
          step_index: 5,
          candle: {
            timestamp: "2026-09-17T09:45:00Z",
            open: 2450,
            high: 2460,
            low: 2445,
            close: 2458,
            volume: 12000,
          },
        },
      };
      expect(formatSimulationEventToActivity(candleEvent)).toBeNull();
    });

    it("converts REST ApiTradeResponse and ApiPerformanceMetricsResponse accurately", () => {
      const apiTrade: ApiTradeResponse = {
        id: "trd-rest-1",
        simulation_id: "sim-100",
        order_id: "ord-rest-1",
        instrument_id: 1,
        symbol: "TCS",
        side: "BUY",
        quantity: 10,
        entry_price: 3500.0,
        exit_price: 3550.0,
        gross_pnl: 500.0,
        net_pnl: 480.0,
        transaction_costs: 15.0,
        slippage_cost: 5.0,
        is_closed: true,
        entry_time: "2026-09-17T09:15:00Z",
        exit_time: "2026-09-17T10:30:00Z",
      };

      const trade = formatApiTradeToLogEntry(apiTrade);
      expect(trade.symbol).toBe("TCS");
      expect(trade.netPnl).toBe(480.0);
      expect(trade.isClosed).toBe(true);
      expect(trade.status).toBe("CLOSED");

      const apiPerf: ApiPerformanceMetricsResponse = {
        simulation_id: "sim-100",
        initial_capital: 100000,
        final_portfolio_value: 104500,
        gross_pnl: 5000,
        net_pnl: 4500,
        total_return_pct: 4.5,
        transaction_costs: 350,
        slippage_cost: 150,
        total_trades: 12,
        winning_trades: 8,
        losing_trades: 4,
        win_rate_pct: 66.67,
        average_win: 800,
        average_loss: 475,
        profit_factor: 2.15,
        max_drawdown_pct: 1.8,
        exposure_pct: 18.5,
        open_positions_count: 1,
      };

      const perf = mapApiPerformanceToMetrics(apiPerf);
      expect(perf.netPnl).toBe(4500);
      expect(perf.winRatePct).toBe(66.67);
      expect(perf.profitFactor).toBe(2.15);
      expect(perf.maxDrawdownPct).toBe(1.8);
    });
  });

  // ---------------------------------------------------------------------------
  // 2. ActivityFeed Component Tests
  // ---------------------------------------------------------------------------
  describe("ActivityFeed Component", () => {
    const mockItems: ActivityItem[] = [
      {
        id: "act-1",
        sequence: 1,
        timestamp: "2026-09-17T09:15:00Z",
        eventType: "agent_started",
        category: "SYSTEM",
        title: "Agent Started",
        description: "Execution initialized",
        severity: "info",
      },
      {
        id: "act-2",
        sequence: 2,
        timestamp: "2026-09-17T09:30:00Z",
        eventType: "agent_decision",
        category: "SIGNAL",
        title: "Decision: BUY",
        description: "BUY signal emitted with 85% confidence",
        severity: "success",
      },
      {
        id: "act-3",
        sequence: 3,
        timestamp: "2026-09-17T09:30:05Z",
        eventType: "risk_check",
        category: "RISK",
        title: "Risk Check: PASSED",
        description: "Within risk parameters",
        severity: "success",
      },
      {
        id: "act-4",
        sequence: 4,
        timestamp: "2026-09-17T09:30:10Z",
        eventType: "order_executed",
        category: "ORDER",
        title: "Order Executed: BUY",
        description: "Filled 25 shares @ ₹2,450.50",
        severity: "success",
      },
    ];

    it("renders empty state when no activity items exist", () => {
      render(<ActivityFeed items={[]} />);
      expect(screen.getByTestId("activity-feed")).toBeInTheDocument();
      expect(screen.getByText(/No activity events recorded yet/i)).toBeInTheDocument();
    });

    it("renders chronological items and filters by category correctly", () => {
      render(<ActivityFeed items={mockItems} />);

      const renderedItems = screen.getAllByTestId("activity-item");
      expect(renderedItems.length).toBe(4);
      expect(screen.getByText("Decision: BUY")).toBeInTheDocument();

      // Filter by Signals only
      const signalFilterBtn = screen.getByTestId("activity-filter-signal");
      fireEvent.click(signalFilterBtn);

      const signalItems = screen.getAllByTestId("activity-item");
      expect(signalItems.length).toBe(1);
      expect(screen.getByText("Decision: BUY")).toBeInTheDocument();

      // Filter by Orders only
      const orderFilterBtn = screen.getByTestId("activity-filter-order");
      fireEvent.click(orderFilterBtn);
      const orderItems = screen.getAllByTestId("activity-item");
      expect(orderItems.length).toBe(1);
      expect(screen.getByText("Order Executed: BUY")).toBeInTheDocument();

      // Return to All
      const allFilterBtn = screen.getByTestId("activity-filter-all");
      fireEvent.click(allFilterBtn);
      expect(screen.getAllByTestId("activity-item").length).toBe(4);
    });

    it("handles auto-scroll toggle checkbox", () => {
      render(<ActivityFeed items={mockItems} />);
      const checkbox = screen.getByRole("checkbox", { name: /auto-scroll/i });
      expect(checkbox).toBeChecked();

      fireEvent.click(checkbox);
      expect(checkbox).not.toBeChecked();
    });
  });

  // ---------------------------------------------------------------------------
  // 3. TradeLog Component Tests
  // ---------------------------------------------------------------------------
  describe("TradeLog Component", () => {
    const mockTrades: TradeLogEntry[] = [
      {
        id: "trade-1",
        timestamp: "2026-09-17T09:30:00Z",
        symbol: "RELIANCE",
        side: "BUY",
        quantity: 20,
        executionPrice: 2450.0,
        transactionCost: 12.0,
        slippageCost: 5.0,
        status: "FILLED",
        isAutoExit: false,
        isClosed: false,
      },
      {
        id: "trade-2",
        timestamp: "2026-09-17T11:00:00Z",
        symbol: "RELIANCE",
        side: "SELL",
        quantity: 20,
        executionPrice: 2480.0,
        exitPrice: 2480.0,
        grossPnl: 600.0,
        netPnl: 566.0,
        transactionCost: 24.0,
        slippageCost: 10.0,
        status: "CLOSED",
        isAutoExit: true,
        isClosed: true,
      },
    ];

    it("renders empty state when no trades exist", () => {
      render(<TradeLog trades={[]} />);
      expect(screen.getByTestId("trade-log")).toBeInTheDocument();
      expect(screen.getByText(/No trades executed yet/i)).toBeInTheDocument();
    });

    it("renders filled and closed trades with prices, P&L, costs, and badges", () => {
      render(<TradeLog trades={mockTrades} />);

      const entries = screen.getAllByTestId("trade-log-entry");
      expect(entries.length).toBe(2);

      // Verify side badges
      expect(screen.getByText("BUY")).toBeInTheDocument();
      expect(screen.getByText("SELL")).toBeInTheDocument();

      // Verify SL/TP EXIT badge for trade 2
      expect(screen.getByText("SL/TP EXIT")).toBeInTheDocument();

      // Verify realized P&L display
      expect(screen.getAllByText("+₹566.00").length).toBeGreaterThanOrEqual(1);

      // Verify summary header counts
      expect(screen.getByText("Total Fills:")).toBeInTheDocument();
      expect(screen.getByText("2")).toBeInTheDocument(); // total fills
    });
  });

  // ---------------------------------------------------------------------------
  // 4. PerformancePanel Component Tests
  // ---------------------------------------------------------------------------
  describe("PerformancePanel Component", () => {
    const mockMetrics: SimulationPerformanceMetrics = {
      simulationId: "sim-test-1",
      initialCapital: 100000,
      finalPortfolioValue: 106450,
      grossPnl: 7200,
      netPnl: 6450,
      totalReturnPct: 6.45,
      transactionCosts: 500,
      slippageCost: 250,
      totalTrades: 10,
      winningTrades: 7,
      losingTrades: 3,
      winRatePct: 70.0,
      averageWin: 1200,
      averageLoss: 650,
      profitFactor: 2.45,
      maxDrawdownPct: 2.1,
      exposurePct: 22.5,
      openPositionsCount: 1,
    };

    it("renders empty state when no metrics provided", () => {
      render(<PerformancePanel metrics={null} />);
      expect(screen.getByTestId("performance-panel")).toBeInTheDocument();
      expect(screen.getByText(/No performance data available/i)).toBeInTheDocument();
    });

    it("renders all Section 58 performance metrics accurately", () => {
      render(<PerformancePanel metrics={mockMetrics} status="COMPLETED" />);

      expect(screen.getByTestId("performance-panel")).toBeInTheDocument();

      // Header summary
      expect(screen.getByText("Settled / Final")).toBeInTheDocument();
      expect(screen.getByText("+6.45%")).toBeInTheDocument();
      expect(screen.getAllByText("+₹6,450.00").length).toBeGreaterThanOrEqual(1);

      // Capital card

      expect(screen.getByText("₹1,00,000.00")).toBeInTheDocument();
      expect(screen.getByText("₹1,06,450.00")).toBeInTheDocument();

      // Trade performance card
      expect(screen.getByText("10")).toBeInTheDocument(); // total trades
      expect(screen.getByText("7W")).toBeInTheDocument();
      expect(screen.getByText("3L")).toBeInTheDocument();
      expect(screen.getByText("70.0%")).toBeInTheDocument(); // win rate
      expect(screen.getByText("2.45")).toBeInTheDocument(); // profit factor

      // Expectancy card
      expect(screen.getByText("+₹1,200.00")).toBeInTheDocument();
      expect(screen.getByText("-₹650.00")).toBeInTheDocument();

      // Risk & costs card
      expect(screen.getByText("2.10%")).toBeInTheDocument(); // max drawdown
      expect(screen.getByText("22.5%")).toBeInTheDocument(); // exposure
      expect(screen.getByText("₹500.00")).toBeInTheDocument(); // transaction costs
      expect(screen.getByText("₹250.00")).toBeInTheDocument(); // slippage
    });

    it("renders Real-Time Tracking mode during active playback", () => {
      render(<PerformancePanel metrics={mockMetrics} status="RUNNING" />);
      expect(screen.getByText("Real-Time Tracking")).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // 5. BottomTerminalWorkspace Integration Tests
  // ---------------------------------------------------------------------------
  describe("BottomTerminalWorkspace Component", () => {
    const mockActivity: ActivityItem[] = [
      {
        id: "act-1",
        sequence: 1,
        timestamp: "2026-09-17T09:15:00Z",
        eventType: "agent_started",
        category: "SYSTEM",
        title: "Agent Started",
        description: "Test run",
        severity: "info",
      },
    ];

    const mockTrades: TradeLogEntry[] = [
      {
        id: "trd-1",
        timestamp: "2026-09-17T09:30:00Z",
        symbol: "RELIANCE",
        side: "BUY",
        quantity: 10,
        executionPrice: 2450.0,
        transactionCost: 10.0,
        slippageCost: 2.0,
        status: "FILLED",
        isAutoExit: false,
        isClosed: false,
      },
    ];

    const mockMetrics: SimulationPerformanceMetrics = {
      simulationId: "sim-ws-1",
      initialCapital: 100000,
      finalPortfolioValue: 102500,
      grossPnl: 2700,
      netPnl: 2500,
      totalReturnPct: 2.5,
      transactionCosts: 150,
      slippageCost: 50,
      totalTrades: 3,
      winningTrades: 2,
      losingTrades: 1,
      winRatePct: 66.7,
      averageWin: 1500,
      averageLoss: 500,
      profitFactor: 3.0,
      maxDrawdownPct: 0.8,
      exposurePct: 15.0,
      openPositionsCount: 1,
    };

    it("renders tab navigation with badges and switches views on click", () => {
      const onTabChange = vi.fn();
      const { rerender } = render(
        <BottomTerminalWorkspace
          activeTab="activity"
          onTabChange={onTabChange}
          activityItems={mockActivity}
          trades={mockTrades}
          metrics={mockMetrics}
        />
      );

      expect(screen.getByTestId("bottom-terminal-workspace")).toBeInTheDocument();
      expect(screen.getByTestId("activity-feed")).toBeInTheDocument();

      // Click Trades Tab
      const tradesTab = screen.getByTestId("tab-trades");
      fireEvent.click(tradesTab);
      expect(onTabChange).toHaveBeenCalledWith("trades");

      // Rerender with activeTab = trades
      rerender(
        <BottomTerminalWorkspace
          activeTab="trades"
          onTabChange={onTabChange}
          activityItems={mockActivity}
          trades={mockTrades}
          metrics={mockMetrics}
        />
      );
      expect(screen.getByTestId("trade-log")).toBeInTheDocument();

      // Click Performance Tab
      const perfTab = screen.getByTestId("tab-performance");
      fireEvent.click(perfTab);
      expect(onTabChange).toHaveBeenCalledWith("performance");

      // Rerender with activeTab = performance
      rerender(
        <BottomTerminalWorkspace
          activeTab="performance"
          onTabChange={onTabChange}
          activityItems={mockActivity}
          trades={mockTrades}
          metrics={mockMetrics}
        />
      );
      expect(screen.getByTestId("performance-panel")).toBeInTheDocument();
    });

    it("supports collapsing and expanding the terminal panel", () => {
      render(
        <BottomTerminalWorkspace
          activeTab="activity"
          onTabChange={vi.fn()}
          activityItems={mockActivity}
          trades={mockTrades}
          metrics={mockMetrics}
        />
      );

      expect(screen.getByTestId("activity-feed")).toBeInTheDocument();

      // Toggle collapse
      const toggleBtn = screen.getByTestId("workspace-toggle-collapse");
      fireEvent.click(toggleBtn);

      // Panel content should now be collapsed (hidden)
      expect(screen.queryByTestId("activity-feed")).not.toBeInTheDocument();

      // Toggle back expand
      fireEvent.click(toggleBtn);
      expect(screen.getByTestId("activity-feed")).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // 6. Edge Cases: Deduplication, Bounding, Reconnect, and Isolation
  // ---------------------------------------------------------------------------
  describe("Edge Cases & State Invariants", () => {
    it("deduplicates activity items by sequence and event ID", () => {
      const duplicateEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 42,
        event_type: "agent_decision",
        wall_clock_timestamp: "2026-09-17T10:00:00Z",
        payload: {
          action: "HOLD",
          confidence: 0.95,
          reason: "Consolidation zone",
        },
      };

      const item1 = formatSimulationEventToActivity(duplicateEvent);
      const item2 = formatSimulationEventToActivity(duplicateEvent);

      expect(item1?.id).toBe(item2?.id);
      expect(item1?.id).toBe("act-sim-100-42-agent_decision");

      // Simulating deduplication logic as in TerminalPage
      let queue: ActivityItem[] = [];
      const addEvent = (act: ActivityItem | null) => {
        if (!act) return;
        if (!queue.some((it) => it.id === act.id)) {
          queue = [...queue, act];
        }
      };

      addEvent(item1);
      addEvent(item2); // duplicate
      expect(queue.length).toBe(1);
    });

    it("enforces bounded state of 200 maximum items in activity feed queue", () => {
      let queue: ActivityItem[] = [];

      for (let i = 1; i <= 250; i++) {
        const evt: SimulationEvent = {
          simulation_id: "sim-bound",
          sequence: i,
          event_type: "risk_check",
          wall_clock_timestamp: "2026-09-17T10:00:00Z",
          payload: {
            order_id: `ord-${i}`,
            passed: true,
            reason: `Risk check #${i} passed`,
          },
        };
        const act = formatSimulationEventToActivity(evt);
        if (act && !queue.some((it) => it.id === act.id)) {
          const next = [...queue, act];
          queue = next.length > 200 ? next.slice(next.length - 200) : next;
        }
      }

      expect(queue.length).toBe(200);
      expect(queue[0].sequence).toBe(51); // First 50 pruned
      expect(queue[queue.length - 1].sequence).toBe(250); // Newest retained
    });

    it("deduplicates trade entries by orderId/tradeId", () => {
      const fillEvent: SimulationEvent = {
        simulation_id: "sim-100",
        sequence: 15,
        event_type: "order_executed",
        virtual_timestamp: "2026-09-17T09:30:00Z",
        wall_clock_timestamp: "2026-09-17T10:00:00Z",
        payload: {
          order_id: "ord-dup-1",
          trade_id: "trd-dup-1",
          side: "BUY",
          quantity: 50,
          execution_price: 2500,
          status: "FILLED",
          slippage_cost: 10,
          transaction_cost: 20,
          is_auto_exit: false,
        },
      };

      const trade1 = formatOrderExecutedToTrade(fillEvent, "RELIANCE");
      const trade2 = formatOrderExecutedToTrade(fillEvent, "RELIANCE");

      let tradeQueue: TradeLogEntry[] = [];
      const addTrade = (t: TradeLogEntry | null) => {
        if (!t) return;
        if (!tradeQueue.some((existing) => existing.id === t.id)) {
          tradeQueue = [...tradeQueue, t];
        }
      };

      addTrade(trade1);
      addTrade(trade2);
      expect(tradeQueue.length).toBe(1);
      expect(tradeQueue[0].id).toBe("trd-dup-1");
    });

    it("formats timestamps and currency with graceful fallbacks", () => {
      // Time format
      expect(formatTimeDisplay("2026-09-17T14:35:12.456Z")).toBe("14:35:12");
      expect(formatTimeDisplay("09:15:00")).toBe("09:15:00");
      expect(formatTimeDisplay(null)).toBe("--:--:--");
      expect(formatTimeDisplay(undefined)).toBe("--:--:--");

      // Space-delimited format
      expect(formatTimeDisplay("2026-09-17 11:20:30")).toBe("11:20:30");

      // Currency format
      expect(formatINR(100000)).toBe("₹1,00,000.00");
      expect(formatINR(2450.5, true)).toBe("+₹2,450.50");
      expect(formatINR(-560.25, true)).toBe("-₹560.25");
      expect(formatINR(null)).toBe("—");
      expect(formatINR(undefined)).toBe("—");
    });

    it("renders PerformancePanel safely when profitFactor is null, NaN, or Infinity", () => {
      const infiniteMetrics: SimulationPerformanceMetrics = {
        simulationId: "sim-inf",
        initialCapital: 100000,
        finalPortfolioValue: 105000,
        grossPnl: 5000,
        netPnl: 4800,
        totalReturnPct: 4.8,
        transactionCosts: 150,
        slippageCost: 50,
        totalTrades: 3,
        winningTrades: 3,
        losingTrades: 0,
        winRatePct: 100,
        averageWin: 1600,
        averageLoss: 0,
        profitFactor: Infinity, // Infinity because 0 losses
        maxDrawdownPct: 0.5,
        exposurePct: 20,
        openPositionsCount: 0,
      };

      const { rerender } = render(<PerformancePanel metrics={infiniteMetrics} />);
      expect(screen.getByText("∞")).toBeInTheDocument();

      // Null profit factor
      const nullMetrics: SimulationPerformanceMetrics = {
        ...infiniteMetrics,
        profitFactor: null as any,
      };
      rerender(<PerformancePanel metrics={nullMetrics} />);
      expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
    });

    it("displays authoritative backend metrics in TradeLog summary when provided", () => {
      const liveTrades: TradeLogEntry[] = [
        {
          id: "trd-live-1",
          timestamp: "2026-09-17T09:30:00Z",
          symbol: "RELIANCE",
          side: "BUY",
          quantity: 20,
          executionPrice: 2450.0,
          transactionCost: 12.0,
          slippageCost: 5.0,
          status: "FILLED",
          isAutoExit: false,
          isClosed: false,
          netPnl: null, // WebSocket live fill has no netPnl yet
        },
      ];

      const authoritativeMetrics: SimulationPerformanceMetrics = {
        simulationId: "sim-100",
        initialCapital: 100000,
        finalPortfolioValue: 103200,
        grossPnl: 3500,
        netPnl: 3200,
        totalReturnPct: 3.2,
        transactionCosts: 200,
        slippageCost: 100,
        totalTrades: 5,
        winningTrades: 4,
        losingTrades: 1,
        winRatePct: 80,
        averageWin: 900,
        averageLoss: 400,
        profitFactor: 2.25,
        maxDrawdownPct: 1.2,
        exposurePct: 15,
        openPositionsCount: 1,
      };

      render(<TradeLog trades={liveTrades} metrics={authoritativeMetrics} />);

      // Should display authoritative closed count (5) and record (4W / 1L) from metrics
      expect(screen.getByText("5")).toBeInTheDocument();
      expect(screen.getByText("(4W / 1L)")).toBeInTheDocument();
      expect(screen.getByText("+₹3,200.00")).toBeInTheDocument();
    });

    it("safely merges historical REST trades with live WebSocket fills without losing data", () => {
      // Historical trade from REST
      const restTrade: TradeLogEntry = {
        id: "trd-1",
        timestamp: "2026-09-17T09:15:00Z",
        symbol: "RELIANCE",
        side: "BUY",
        quantity: 20,
        executionPrice: 2400.0,
        exitPrice: 2450.0,
        netPnl: 950.0,
        grossPnl: 1000.0,
        transactionCost: 35.0,
        slippageCost: 15.0,
        status: "CLOSED",
        isAutoExit: false,
        isClosed: true,
      };

      // Live fill from WebSocket that arrived before REST returned
      const liveTrade: TradeLogEntry = {
        id: "trd-2",
        timestamp: "2026-09-17T09:45:00Z",
        symbol: "RELIANCE",
        side: "BUY",
        quantity: 15,
        executionPrice: 2460.0,
        transactionCost: 15.0,
        slippageCost: 5.0,
        status: "FILLED",
        isAutoExit: false,
        isClosed: false,
      };

      // Merge test mimicking TerminalPage logic
      const prevTrades = [liveTrade];
      const restTrades = [restTrade];

      const tradeMap = new Map<string, TradeLogEntry>();
      for (const restT of restTrades) {
        tradeMap.set(restT.id, restT);
      }
      for (const liveT of prevTrades) {
        const existing = tradeMap.get(liveT.id);
        if (!existing) {
          tradeMap.set(liveT.id, liveT);
        } else {
          tradeMap.set(liveT.id, {
            ...liveT,
            exitPrice: existing.exitPrice ?? liveT.exitPrice,
            netPnl: existing.netPnl ?? liveT.netPnl,
            grossPnl: existing.grossPnl ?? liveT.grossPnl,
            isClosed: existing.isClosed || liveT.isClosed,
            status: existing.isClosed ? "CLOSED" : liveT.status,
          });
        }
      }
      const merged = Array.from(tradeMap.values());

      expect(merged.length).toBe(2);
      expect(merged.find((t) => t.id === "trd-1")?.isClosed).toBe(true);
      expect(merged.find((t) => t.id === "trd-2")?.status).toBe("FILLED");
    });
  });
});


