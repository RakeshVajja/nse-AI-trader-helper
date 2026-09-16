import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, cleanup, act } from "@testing-library/react";
import { CandlestickChart } from "../components/CandlestickChart";
import { Candle, ChartTradeMarker, IndicatorSeries, LiveCandleUpdate } from "../types";
import { LineStyle } from "lightweight-charts";

// -----------------------------------------------------------------------------
// Lightweight Charts & ResizeObserver Mocks
// -----------------------------------------------------------------------------

class MockResizeObserver {
  static instances: MockResizeObserver[] = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  callback: ResizeObserverCallback;

  constructor(cb: ResizeObserverCallback) {
    this.callback = cb;
    MockResizeObserver.instances.push(this);
  }
}

const mockCandleSeries = {
  seriesType: () => "Candlestick",
  setData: vi.fn(),
  update: vi.fn(),
  setMarkers: vi.fn(),
  createPriceLine: vi.fn((opts: any) => ({ ...opts, _id: "line-" + Math.random() })),
  removePriceLine: vi.fn(),
};

const mockVolumeSeries = {
  seriesType: () => "Histogram",
  setData: vi.fn(),
  update: vi.fn(),
  priceScale: () => ({
    applyOptions: vi.fn(),
  }),
};

const mockEma9Series = {
  seriesType: () => "Line",
  setData: vi.fn(),
  update: vi.fn(),
};

const mockEma20Series = {
  seriesType: () => "Line",
  setData: vi.fn(),
  update: vi.fn(),
};

const mockSma50Series = {
  seriesType: () => "Line",
  setData: vi.fn(),
  update: vi.fn(),
};

const mockTimeScale = {
  fitContent: vi.fn(),
};

const mockChart = {
  addCandlestickSeries: vi.fn(() => mockCandleSeries),
  addHistogramSeries: vi.fn(() => mockVolumeSeries),
  addLineSeries: vi.fn((options: any) => {
    if (options?.title === "EMA 9") return mockEma9Series;
    if (options?.title === "EMA 20") return mockEma20Series;
    return mockSma50Series;
  }),
  subscribeCrosshairMove: vi.fn(),
  applyOptions: vi.fn(),
  timeScale: vi.fn(() => mockTimeScale),
  remove: vi.fn(),
};

vi.mock("lightweight-charts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("lightweight-charts")>();
  return {
    ...actual,
    createChart: vi.fn(() => mockChart),
  };
});

// -----------------------------------------------------------------------------
// Test Fixtures
// -----------------------------------------------------------------------------

const sampleCandles: Candle[] = [
  {
    timestamp: "2026-03-01T09:15:00Z",
    open: 2500,
    high: 2520,
    low: 2490,
    close: 2515,
    volume: 50000,
  },
  {
    timestamp: "2026-03-01T09:30:00Z",
    open: 2515,
    high: 2530,
    low: 2510,
    close: 2525,
    volume: 60000,
  },
  {
    timestamp: "2026-03-01T09:45:00Z",
    open: 2525,
    high: 2540,
    low: 2520,
    close: 2535,
    volume: 45000,
  },
];

const sampleIndicators: IndicatorSeries = {
  symbol: "RELIANCE",
  timeframe: "15m",
  timestamps: [
    "2026-03-01T09:15:00Z",
    "2026-03-01T09:30:00Z",
    "2026-03-01T09:45:00Z",
  ],
  closes: [2515, 2525, 2535],
  ema9: [2510.5, 2514.2, 2519.8],
  ema20: [2505.0, 2508.3, 2512.1],
  sma50: [2500.0, 2501.5, 2503.2],
  rsi14: [55.2, 58.4, 62.1],
  macd_line: [2.5, 3.1, 3.8],
  macd_signal: [2.1, 2.4, 2.8],
  macd_histogram: [0.4, 0.7, 1.0],
  atr14: [15.2, 16.0, 15.8],
  atrp14: [0.6, 0.63, 0.62],
  trend_regimes: ["BULLISH", "BULLISH", "BULLISH"],
  volatility_regimes: ["NORMAL", "NORMAL", "NORMAL"],
  count: 3,
};

describe("Phase 10B — Quantitative Trading Terminal Layout (Chart + Indicators + Trade Markers)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    MockResizeObserver.instances = [];
    // @ts-ignore
    global.ResizeObserver = MockResizeObserver;
  });

  afterEach(() => {
    cleanup();
  });

  // 1. Chart renders with historical candle data
  it("1. renders chart with historical candle data and correct OHLC values", () => {
    render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    expect(mockChart.addCandlestickSeries).toHaveBeenCalled();
    expect(mockCandleSeries.setData).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({
          open: 2500,
          high: 2520,
          low: 2490,
          close: 2515,
        }),
        expect.objectContaining({
          open: 2515,
          high: 2530,
          low: 2510,
          close: 2525,
        }),
      ])
    );
    expect(mockTimeScale.fitContent).toHaveBeenCalled();
  });

  // 2. Candles appear in chronological order
  it("2. guarantees candles appear in strict ascending chronological order", () => {
    // Pass out-of-order candles: 09:45, 09:15, 09:30
    const unorderedCandles: Candle[] = [
      sampleCandles[2],
      sampleCandles[0],
      sampleCandles[1],
    ];

    render(
      <CandlestickChart
        candles={unorderedCandles}
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    const setDataCall = mockCandleSeries.setData.mock.calls[0][0];
    expect(setDataCall.length).toBe(3);
    expect(setDataCall[0].time).toBeLessThan(setDataCall[1].time);
    expect(setDataCall[1].time).toBeLessThan(setDataCall[2].time);

    // Verify first is 09:15 epoch and last is 09:45 epoch
    const t0 = Math.floor(new Date("2026-03-01T09:15:00Z").getTime() / 1000);
    const t2 = Math.floor(new Date("2026-03-01T09:45:00Z").getTime() / 1000);
    expect(setDataCall[0].time).toBe(t0);
    expect(setDataCall[2].time).toBe(t2);
  });

  // 3. Live candle_update adds/updates the correct candle
  it("3. updates current bar when live timestamp matches, and appends when advancing", () => {
    const { rerender } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    // A: Update the CURRENT bar (09:45)
    const updateCurrent: LiveCandleUpdate = {
      step_index: 2,
      candle: {
        timestamp: "2026-03-01T09:45:00Z",
        open: 2525,
        high: 2550, // High revised higher
        low: 2520,
        close: 2548,
        volume: 52000,
      },
    };

    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        liveCandle={updateCurrent}
      />
    );

    expect(mockCandleSeries.update).toHaveBeenCalledWith(
      expect.objectContaining({
        high: 2550,
        close: 2548,
      })
    );

    // B: Append a NEW bar (10:00)
    const newBar: LiveCandleUpdate = {
      step_index: 3,
      candle: {
        timestamp: "2026-03-01T10:00:00Z",
        open: 2548,
        high: 2560,
        low: 2545,
        close: 2555,
        volume: 42000,
      },
    };

    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        liveCandle={newBar}
      />
    );

    expect(mockCandleSeries.update).toHaveBeenCalledWith(
      expect.objectContaining({
        open: 2548,
        close: 2555,
      })
    );
  });

  // 4. Duplicate candle events do not create duplicate candles
  it("4. prevents duplicate candle events from creating duplicate chart bars", () => {
    const duplicates: Candle[] = [
      sampleCandles[0],
      sampleCandles[0], // Duplicate timestamp
      sampleCandles[1],
      sampleCandles[1], // Duplicate timestamp
      sampleCandles[2],
    ];

    render(
      <CandlestickChart
        candles={duplicates}
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    const setDataCall = mockCandleSeries.setData.mock.calls[0][0];
    // Exactly 3 unique timestamps
    expect(setDataCall.length).toBe(3);
    const times = setDataCall.map((c: any) => c.time);
    const uniqueTimes = new Set(times);
    expect(uniqueTimes.size).toBe(3);
  });

  // 5. Required indicators render with correct alignment
  it("5. renders required EMA9, EMA20, and SMA50 indicators with timestamp alignment", () => {
    render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        indicatorSeries={sampleIndicators}
      />
    );

    expect(mockEma9Series.setData).toHaveBeenCalled();
    expect(mockEma20Series.setData).toHaveBeenCalled();
    expect(mockSma50Series.setData).toHaveBeenCalled();

    const ema9Data = mockEma9Series.setData.mock.calls[0][0];
    const ema20Data = mockEma20Series.setData.mock.calls[0][0];
    const sma50Data = mockSma50Series.setData.mock.calls[0][0];

    expect(ema9Data.length).toBe(3);
    expect(ema20Data.length).toBe(3);
    expect(sma50Data.length).toBe(3);

    // Verify timestamp alignment with candle epochs
    const t0 = Math.floor(new Date("2026-03-01T09:15:00Z").getTime() / 1000);
    expect(ema9Data[0].time).toBe(t0);
    expect(ema9Data[0].value).toBe(2510.5);
    expect(ema20Data[0].time).toBe(t0);
    expect(ema20Data[0].value).toBe(2505.0);
    expect(sma50Data[0].time).toBe(t0);
    expect(sma50Data[0].value).toBe(2500.0);
  });

  // 6. Required trade/order markers render at correct timestamps
  it("6. renders BUY, SELL, and SL/TP exit markers at correct timestamps", () => {
    const tBuy = Math.floor(new Date("2026-03-01T09:15:00Z").getTime() / 1000);
    const tSell = Math.floor(new Date("2026-03-01T09:45:00Z").getTime() / 1000);

    const testMarkers: ChartTradeMarker[] = [
      {
        id: "m-1",
        time: tBuy,
        type: "BUY_EXECUTION",
        price: 2505,
        quantity: 20,
      },
      {
        id: "m-2",
        time: tSell,
        type: "SELL_EXECUTION",
        price: 2535,
        quantity: 20,
      },
      {
        id: "m-3",
        time: tSell + 900,
        type: "SL_EXIT",
        price: 2480,
        quantity: 10,
      },
      {
        id: "m-4",
        time: tSell + 1800,
        type: "TP_EXIT",
        price: 2600,
        quantity: 10,
      },
    ];

    render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        markers={testMarkers}
      />
    );

    expect(mockCandleSeries.setMarkers).toHaveBeenCalled();
    const markersCall = mockCandleSeries.setMarkers.mock.calls[0][0];
    expect(markersCall.length).toBe(4);

    // BUY Marker
    expect(markersCall[0]).toMatchObject({
      time: tBuy,
      position: "belowBar",
      shape: "arrowUp",
      color: "#10b981",
    });

    // SELL Marker
    expect(markersCall[1]).toMatchObject({
      time: tSell,
      position: "aboveBar",
      shape: "arrowDown",
      color: "#ef4444",
    });

    // SL EXIT Marker
    expect(markersCall[2]).toMatchObject({
      time: tSell + 900,
      position: "aboveBar",
      shape: "square",
      color: "#f43f5e",
    });

    // TP EXIT Marker
    expect(markersCall[3]).toMatchObject({
      time: tSell + 1800,
      position: "aboveBar",
      shape: "circle",
      color: "#10b981",
    });
  });

  // 7. BUY/SELL signal vs execution markers remain semantically distinct
  it("7. clearly distinguishes strategy decision signals from executed order markers", () => {
    const t = Math.floor(new Date("2026-03-01T09:15:00Z").getTime() / 1000);

    const testMarkers: ChartTradeMarker[] = [
      {
        id: "sig-1",
        time: t,
        type: "SIGNAL_BUY",
        price: 0,
        text: "SIG: BUY (85%)",
      },
      {
        id: "exec-1",
        time: t + 30,
        type: "BUY_EXECUTION",
        price: 2505,
        quantity: 10,
        text: "BUY @ ₹2,505.00",
      },
    ];

    render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        markers={testMarkers}
      />
    );

    const markersCall = mockCandleSeries.setMarkers.mock.calls[0][0];
    expect(markersCall.length).toBe(2);

    const signalMarker = markersCall[0];
    const execMarker = markersCall[1];

    // Verify semantic distinction: shape, color, and text
    expect(signalMarker.shape).toBe("circle");
    expect(signalMarker.color).toBe("#38bdf8"); // Sky blue
    expect(signalMarker.text).toBe("SIG: BUY (85%)");

    expect(execMarker.shape).toBe("arrowUp");
    expect(execMarker.color).toBe("#10b981"); // Emerald
    expect(execMarker.text).toBe("BUY @ ₹2,505.00");
  });

  // 8. Initial WebSocket state integrates without corrupting chart state (Stop-Loss & Take-Profit)
  it("8. renders Stop-Loss and Take-Profit price lines from position state without corrupting chart", () => {
    const { rerender } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        stopLoss={2480.5}
        takeProfit={2580.0}
      />
    );

    expect(mockCandleSeries.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({
        price: 2480.5,
        color: "#ef4444",
        lineStyle: LineStyle.Dashed,
        title: expect.stringContaining("SL"),
      })
    );

    expect(mockCandleSeries.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({
        price: 2580.0,
        color: "#10b981",
        lineStyle: LineStyle.Dashed,
        title: expect.stringContaining("TP"),
      })
    );

    // Position close -> removes lines
    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        stopLoss={null}
        takeProfit={null}
      />
    );

    expect(mockCandleSeries.removePriceLine).toHaveBeenCalled();
  });

  // 9. Future/unreceived candles are never rendered (No Lookahead Bias)
  it("9. strictly guards against lookahead: never renders future candles, rejects past ones", () => {
    render(
      <CandlestickChart
        candles={sampleCandles.slice(0, 2)} // Only up to 09:30
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    const initialData = mockCandleSeries.setData.mock.calls[0][0];
    expect(initialData.length).toBe(2);

    // Attempt to deliver an older/past candle (09:00 < 09:30)
    const pastCandle: LiveCandleUpdate = {
      step_index: 0,
      candle: {
        timestamp: "2026-03-01T09:00:00Z",
        open: 2490,
        high: 2500,
        low: 2485,
        close: 2495,
        volume: 30000,
      },
    };

    // The update call should be ignored safely to avoid backwards time error in Lightweight Charts
    render(
      <CandlestickChart
        candles={sampleCandles.slice(0, 2)}
        symbol="RELIANCE"
        timeframe="15m"
        liveCandle={pastCandle}
      />
    );

    // mockCandleSeries.update should not be called with an out-of-order timestamp
    const updateCalls = mockCandleSeries.update.mock.calls;
    for (const call of updateCalls) {
      const bar = call[0];
      const t0930 = Math.floor(new Date("2026-03-01T09:30:00Z").getTime() / 1000);
      expect(bar.time).toBeGreaterThanOrEqual(t0930);
    }
  });

  // 10. Chart cleanup occurs correctly on unmount
  it("10. cleanly disposes chart, series, price lines, and ResizeObserver on unmount", () => {
    const { unmount } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        stopLoss={2480}
        takeProfit={2580}
      />
    );

    expect(MockResizeObserver.instances.length).toBeGreaterThan(0);
    const observer = MockResizeObserver.instances[0];

    unmount();

    expect(observer.disconnect).toHaveBeenCalled();
    expect(mockChart.remove).toHaveBeenCalled();
    expect(mockCandleSeries.removePriceLine).toHaveBeenCalled();
  });

  // 11. Responsive resize behavior
  it("11. responds cleanly to container resize events via ResizeObserver", () => {
    render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    const observer = MockResizeObserver.instances[0];
    expect(observer).toBeDefined();

    act(() => {
      observer.callback(
        [
          {
            contentRect: { width: 1400, height: 750 },
          } as unknown as ResizeObserverEntry,
        ],
        observer as unknown as ResizeObserver
      );
    });

    expect(mockChart.applyOptions).toHaveBeenCalledWith({
      width: 1400,
      height: 750,
    });
  });

  // 12. Malformed/irrelevant WebSocket events do not crash the chart
  it("12. gracefully handles malformed or incomplete live event payloads without crashing", () => {
    const { rerender } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
      />
    );

    // Malformed candle timestamp (invalid date string)
    const malformedCandle: LiveCandleUpdate = {
      step_index: 99,
      candle: {
        timestamp: "invalid-date-not-an-iso-string",
        open: 100,
        high: 100,
        low: 100,
        close: 100,
        volume: 0,
      },
    };

    expect(() => {
      rerender(
        <CandlestickChart
          candles={sampleCandles}
          symbol="RELIANCE"
          timeframe="15m"
          liveCandle={malformedCandle}
        />
      );
    }).not.toThrow();

    // Null liveCandle
    expect(() => {
      rerender(
        <CandlestickChart
          candles={sampleCandles}
          symbol="RELIANCE"
          timeframe="15m"
          liveCandle={null}
        />
      );
    }).not.toThrow();
  });

  // 13. Intra-bar updates recalculate against previous bar accumulator without compounding error
  it("13. intra-bar updates recalculate against previous bar accumulator without compounding error", () => {
    const { rerender } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        indicatorSeries={sampleIndicators}
      />
    );

    // Initial state after historical load: latest EMA9 is 2519.8
    // Live update 1 to current bar (09:45): close moves to 2550
    // Expected EMA9 = 0.2 * 2550 + 0.8 * 2519.8 = 510 + 2015.84 = 2525.84
    const tick1: LiveCandleUpdate = {
      step_index: 2,
      candle: {
        timestamp: "2026-03-01T09:45:00Z",
        open: 2525,
        high: 2555,
        low: 2520,
        close: 2550,
        volume: 48000,
      },
    };

    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        indicatorSeries={sampleIndicators}
        liveCandle={tick1}
      />
    );

    const call1 = mockEma9Series.update.mock.calls[mockEma9Series.update.mock.calls.length - 1][0];
    expect(call1.value).toBeCloseTo(2525.84, 1);

    // Live update 2 to SAME bar (09:45): close moves to 2560
    // Expected EMA9 = 0.2 * 2560 + 0.8 * 2519.8 = 512 + 2015.84 = 2527.84
    // If it had compounded on tick 1, it would be 0.2 * 2560 + 0.8 * 2525.84 = 2532.67 (DEFECT!)
    const tick2: LiveCandleUpdate = {
      step_index: 2,
      candle: {
        timestamp: "2026-03-01T09:45:00Z",
        open: 2525,
        high: 2565,
        low: 2520,
        close: 2560,
        volume: 51000,
      },
    };

    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        indicatorSeries={sampleIndicators}
        liveCandle={tick2}
      />
    );

    const call2 = mockEma9Series.update.mock.calls[mockEma9Series.update.mock.calls.length - 1][0];
    expect(call2.value).toBeCloseTo(2527.84, 1);
  });

  // 14. Enforces strict indicator warm-up thresholds
  it("14. enforces strict indicator warm-up thresholds (EMA9 requires >= 9 closes)", () => {
    // Render with only 3 candles and no indicatorSeries (cold start)
    const { rerender } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        indicatorSeries={null}
      />
    );

    // Initial 3 candles: ema9 should not be outputted yet
    mockEma9Series.update.mockClear();

    // Stream 4th candle
    const candle4: LiveCandleUpdate = {
      step_index: 3,
      candle: {
        timestamp: "2026-03-01T10:00:00Z",
        open: 2535,
        high: 2545,
        low: 2530,
        close: 2540,
        volume: 20000,
      },
    };

    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        indicatorSeries={null}
        liveCandle={candle4}
      />
    );

    // Total closes = 4 (< 9). EMA9 should NOT have updated the chart series yet!
    expect(mockEma9Series.update).not.toHaveBeenCalled();
  });

  // 15. Sorts multiple markers at the same timestamp deterministically and filters duplicate IDs
  it("15. sorts multiple markers at the same timestamp deterministically and filters duplicate IDs", () => {
    const t = Math.floor(new Date("2026-03-01T09:30:00Z").getTime() / 1000);

    const sameTimeMarkers: ChartTradeMarker[] = [
      {
        id: "order-z",
        time: t,
        type: "SELL_EXECUTION",
        price: 2530,
      },
      {
        id: "order-a",
        time: t,
        type: "BUY_EXECUTION",
        price: 2515,
      },
      {
        id: "order-a", // Duplicate ID
        time: t,
        type: "BUY_EXECUTION",
        price: 2515,
      },
    ];

    render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        markers={sameTimeMarkers}
      />
    );

    const call = mockCandleSeries.setMarkers.mock.calls[0][0];
    // Exactly 2 unique markers (order-a and order-z), duplicate order-a removed
    expect(call.length).toBe(2);
    // Deterministically ordered by ID tie-breaker (order-a before order-z)
    expect(call[0].id).toBe("order-a");
    expect(call[1].id).toBe("order-z");
  });

  // 16. Replacing an active position updates price lines cleanly
  it("16. replacing an active position updates price lines cleanly and unmount tears them down", () => {
    const { rerender, unmount } = render(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        stopLoss={2480}
        takeProfit={2580}
      />
    );

    expect(mockCandleSeries.createPriceLine).toHaveBeenCalledTimes(2);

    // Replace with new tighter stop loss
    rerender(
      <CandlestickChart
        candles={sampleCandles}
        symbol="RELIANCE"
        timeframe="15m"
        stopLoss={2495}
        takeProfit={2580}
      />
    );

    // Previous line removed before new line created
    expect(mockCandleSeries.removePriceLine).toHaveBeenCalled();
    expect(mockCandleSeries.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 2495 })
    );

    unmount();
    expect(mockCandleSeries.removePriceLine).toHaveBeenCalled();
  });
});
