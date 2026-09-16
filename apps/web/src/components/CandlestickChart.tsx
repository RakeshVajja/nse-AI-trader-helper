"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineStyle,
  SeriesMarker,
  SeriesMarkerPosition,
  SeriesMarkerShape,
  UTCTimestamp,
  CandlestickData,
  HistogramData,
  LineData,
  TickMarkType,
} from "lightweight-charts";
import {
  Candle,
  ChartTradeMarker,
  IndicatorSeries,
  LiveCandleUpdate,
  TrendRegime,
  VolatilityRegime,
} from "@/types";
import {
  Loader2,
  AlertTriangle,
  RefreshCw,
  BarChart2,
  Eye,
  EyeOff,
  Crosshair,
  TrendingUp,
} from "lucide-react";

export interface CandlestickChartProps {
  candles: Candle[];
  symbol: string;
  timeframe: string;
  indicatorSeries?: IndicatorSeries | null;
  isLoading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Phase 10B: Authoritative executed trades or strategy signal markers */
  markers?: ChartTradeMarker[];
  /** Phase 10B: Active position stop-loss level */
  stopLoss?: number | null;
  /** Phase 10B: Active position take-profit level */
  takeProfit?: number | null;
  /** Phase 10B: Live simulation candle stream event */
  liveCandle?: LiveCandleUpdate | null;
}

interface HoverData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number;
  changePercent: number;
  ema9?: number | null;
  ema20?: number | null;
  sma50?: number | null;
  rsi14?: number | null;
  macd?: number | null;
  macdSignal?: number | null;
  macdHist?: number | null;
  atr14?: number | null;
  atrp14?: number | null;
  trendRegime?: TrendRegime | null;
  volatilityRegime?: VolatilityRegime | null;
}

export function CandlestickChart({
  candles,
  symbol,
  timeframe,
  indicatorSeries,
  isLoading = false,
  error = null,
  onRetry,
  markers = [],
  stopLoss = null,
  takeProfit = null,
  liveCandle = null,
}: CandlestickChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ema9SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const sma50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const stopLossLineRef = useRef<IPriceLine | null>(null);
  const takeProfitLineRef = useRef<IPriceLine | null>(null);

  const candlesRef = useRef<Candle[]>(candles);
  const indicatorSeriesRef = useRef<IndicatorSeries | null | undefined>(indicatorSeries);
  const allCandlesRef = useRef<Candle[]>([]);
  const lastIndicatorsRef = useRef<{
    ema9: number | null;
    ema20: number | null;
    sma50: number | null;
    prevEma9: number | null;
    prevEma20: number | null;
    ema9Acc: number | null;
    prevEma9Acc: number | null;
    ema20Acc: number | null;
    prevEma20Acc: number | null;
    closes: number[];
  }>({
    ema9: null,
    ema20: null,
    sma50: null,
    prevEma9: null,
    prevEma20: null,
    ema9Acc: null,
    prevEma9Acc: null,
    ema20Acc: null,
    prevEma20Acc: null,
    closes: [],
  });

  const [hoverData, setHoverData] = useState<HoverData | null>(null);

  // Overlay visibility toggles
  const [showEma9, setShowEma9] = useState<boolean>(true);
  const [showEma20, setShowEma20] = useState<boolean>(true);
  const [showSma50, setShowSma50] = useState<boolean>(true);
  const [showVolume, setShowVolume] = useState<boolean>(true);
  const [showMarkers, setShowMarkers] = useState<boolean>(true);
  const [showPriceLines, setShowPriceLines] = useState<boolean>(true);

  // Helpers
  const formatPrice = (val: number) =>
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(val);

  const formatVol = (val: number) => {
    if (val >= 10000000) return `${(val / 10000000).toFixed(2)} Cr`;
    if (val >= 100000) return `${(val / 100000).toFixed(2)} L`;
    if (val >= 1000) return `${(val / 1000).toFixed(1)} K`;
    return val.toString();
  };

  const formatDateTimeIST = (epochSec: number) => {
    const d = new Date(epochSec * 1000);
    return new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(d);
  };

  // Helper to extract indicator metrics at a given timestamp/index
  const extractIndicatorsAtTime = (
    epochSec: number,
    inds?: IndicatorSeries | null
  ): Partial<HoverData> => {
    if (!inds || !inds.timestamps || inds.timestamps.length === 0) return {};

    for (let i = inds.timestamps.length - 1; i >= 0; i--) {
      const indEpoch = Math.floor(new Date(inds.timestamps[i]).getTime() / 1000);
      if (indEpoch === epochSec) {
        return {
          ema9: inds.ema9[i],
          ema20: inds.ema20[i],
          sma50: inds.sma50[i],
          rsi14: inds.rsi14[i],
          macd: inds.macd_line[i],
          macdSignal: inds.macd_signal[i],
          macdHist: inds.macd_histogram[i],
          atr14: inds.atr14[i],
          atrp14: inds.atrp14[i],
          trendRegime: inds.trend_regimes[i],
          volatilityRegime: inds.volatility_regimes[i],
        };
      }
    }
    return {};
  };

  // Keep refs updated
  useEffect(() => {
    candlesRef.current = candles;
    indicatorSeriesRef.current = indicatorSeries;

    if (candles && candles.length > 0) {
      const last = candles[candles.length - 1];
      const change = last.close - last.open;
      const changePercent = last.open !== 0 ? (change / last.open) * 100 : 0;
      const epochSec = Math.floor(new Date(last.timestamp).getTime() / 1000);

      const lastInds = extractIndicatorsAtTime(epochSec, indicatorSeries);

      setHoverData({
        time: formatDateTimeIST(epochSec),
        open: last.open,
        high: last.high,
        low: last.low,
        close: last.close,
        volume: last.volume,
        change,
        changePercent,
        ...lastInds,
      });
    } else {
      setHoverData(null);
    }
  }, [candles, indicatorSeries]);

  // Main Chart Initialization
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0a0d14" },
        textColor: "#94a3b8",
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        fontSize: 11,
      },
      localization: {
        timeFormatter: (time: number | string) => {
          const epoch =
            typeof time === "number"
              ? time
              : Math.floor(new Date(time).getTime() / 1000);
          return formatDateTimeIST(epoch);
        },
        dateFormat: "dd MMM yyyy",
      },
      grid: {
        vertLines: { color: "rgba(30, 41, 59, 0.6)" },
        horzLines: { color: "rgba(30, 41, 59, 0.6)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(56, 189, 248, 0.5)",
          width: 1,
          style: 3,
          labelBackgroundColor: "#1e293b",
        },
        horzLine: {
          color: "rgba(56, 189, 248, 0.5)",
          width: 1,
          style: 3,
          labelBackgroundColor: "#1e293b",
        },
      },
      rightPriceScale: {
        borderColor: "#1e293b",
        scaleMargins: {
          top: 0.08,
          bottom: 0.2,
        },
      },
      timeScale: {
        borderColor: "#1e293b",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        tickMarkFormatter: (time: number | string, tickMarkType: TickMarkType) => {
          const epoch =
            typeof time === "number"
              ? time
              : Math.floor(new Date(time).getTime() / 1000);
          const d = new Date(epoch * 1000);
          if (
            tickMarkType === TickMarkType.Time ||
            tickMarkType === TickMarkType.TimeWithSeconds
          ) {
            return new Intl.DateTimeFormat("en-IN", {
              timeZone: "Asia/Kolkata",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            }).format(d);
          }
          if (tickMarkType === TickMarkType.DayOfMonth) {
            return new Intl.DateTimeFormat("en-IN", {
              timeZone: "Asia/Kolkata",
              day: "2-digit",
              month: "short",
            }).format(d);
          }
          if (tickMarkType === TickMarkType.Month) {
            return new Intl.DateTimeFormat("en-IN", {
              timeZone: "Asia/Kolkata",
              month: "short",
              year: "2-digit",
            }).format(d);
          }
          if (tickMarkType === TickMarkType.Year) {
            return new Intl.DateTimeFormat("en-IN", {
              timeZone: "Asia/Kolkata",
              year: "numeric",
            }).format(d);
          }
          return null;
        },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    chartRef.current = chart;

    // 1. Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
      priceFormat: {
        type: "price",
        precision: 2,
        minMove: 0.05,
      },
    });
    candleSeriesRef.current = candleSeries;

    // 2. Volume series
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.82,
        bottom: 0,
      },
    });
    volumeSeriesRef.current = volumeSeries;

    // 3. Technical Indicator Overlays (Phase 10B / Spec §54)
    // EMA9 (Sky Blue)
    const ema9Series = chart.addLineSeries({
      color: "#38bdf8",
      lineWidth: 2,
      title: "EMA 9",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ema9SeriesRef.current = ema9Series;

    // EMA20 (Amber)
    const ema20Series = chart.addLineSeries({
      color: "#f59e0b",
      lineWidth: 2,
      title: "EMA 20",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    ema20SeriesRef.current = ema20Series;

    // SMA50 (Purple)
    const sma50Series = chart.addLineSeries({
      color: "#a855f7",
      lineWidth: 2,
      title: "SMA 50",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    sma50SeriesRef.current = sma50Series;

    // 4. Crosshair move subscriber
    chart.subscribeCrosshairMove((param) => {
      if (
        !param.point ||
        !param.time ||
        !param.seriesData ||
        !candleSeriesRef.current
      ) {
        const currentCandles = candlesRef.current;
        if (currentCandles && currentCandles.length > 0) {
          const last = currentCandles[currentCandles.length - 1];
          const change = last.close - last.open;
          const changePercent = last.open !== 0 ? (change / last.open) * 100 : 0;
          const epochSec = Math.floor(new Date(last.timestamp).getTime() / 1000);
          const lastInds = extractIndicatorsAtTime(epochSec, indicatorSeriesRef.current);

          setHoverData({
            time: formatDateTimeIST(epochSec),
            open: last.open,
            high: last.high,
            low: last.low,
            close: last.close,
            volume: last.volume,
            change,
            changePercent,
            ...lastInds,
          });
        }
        return;
      }

      const cData = param.seriesData.get(candleSeriesRef.current) as CandlestickData | undefined;
      const vData = volumeSeriesRef.current
        ? (param.seriesData.get(volumeSeriesRef.current) as HistogramData | undefined)
        : undefined;

      if (cData) {
        const change = cData.close - cData.open;
        const changePercent = cData.open !== 0 ? (change / cData.open) * 100 : 0;
        const timeVal =
          typeof param.time === "number"
            ? param.time
            : Math.floor(new Date(param.time as string).getTime() / 1000);

        const indData = extractIndicatorsAtTime(timeVal, indicatorSeriesRef.current);

        setHoverData({
          time: formatDateTimeIST(timeVal),
          open: cData.open,
          high: cData.high,
          low: cData.low,
          close: cData.close,
          volume: vData?.value || 0,
          change,
          changePercent,
          ...indData,
        });
      }
    });

    // 5. Responsive Resize
    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0 || !entries[0].contentRect) return;
      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });
    });

    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      if (stopLossLineRef.current && candleSeriesRef.current) {
        try {
          candleSeriesRef.current.removePriceLine(stopLossLineRef.current);
        } catch {}
        stopLossLineRef.current = null;
      }
      if (takeProfitLineRef.current && candleSeriesRef.current) {
        try {
          candleSeriesRef.current.removePriceLine(takeProfitLineRef.current);
        } catch {}
        takeProfitLineRef.current = null;
      }
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ema9SeriesRef.current = null;
      ema20SeriesRef.current = null;
      sma50SeriesRef.current = null;
    };
  }, []);

  // Update Candlestick and Volume data on historical candles change
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !chartRef.current) {
      return;
    }

    if (!candles || candles.length === 0) {
      candleSeriesRef.current.setData([]);
      volumeSeriesRef.current.setData([]);
      allCandlesRef.current = [];
      lastIndicatorsRef.current = {
        ema9: null,
        ema20: null,
        sma50: null,
        prevEma9: null,
        prevEma20: null,
        ema9Acc: null,
        prevEma9Acc: null,
        ema20Acc: null,
        prevEma20Acc: null,
        closes: [],
      };
      return;
    }

    const timeMap = new Map<number, { candle: CandlestickData; vol: HistogramData; raw: Candle }>();

    for (const c of candles) {
      const epochSec = Math.floor(new Date(c.timestamp).getTime() / 1000) as UTCTimestamp;
      if (isNaN(epochSec)) continue;

      const isUp = c.close >= c.open;
      timeMap.set(epochSec, {
        candle: {
          time: epochSec,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        },
        vol: {
          time: epochSec,
          value: c.volume,
          color: isUp ? "rgba(16, 185, 129, 0.35)" : "rgba(239, 68, 68, 0.35)",
        },
        raw: c,
      });
    }

    // Strict chronological ordering by timestamp ascending
    const sortedKeys = Array.from(timeMap.keys()).sort((a, b) => a - b);
    const candleDataList: CandlestickData[] = [];
    const volumeDataList: HistogramData[] = [];
    const sortedRawCandles: Candle[] = [];

    for (const k of sortedKeys) {
      const item = timeMap.get(k);
      if (item) {
        candleDataList.push(item.candle);
        volumeDataList.push(item.vol);
        sortedRawCandles.push(item.raw);
      }
    }

    allCandlesRef.current = sortedRawCandles;
    lastIndicatorsRef.current.closes = sortedRawCandles.map((c) => c.close);

    candleSeriesRef.current.setData(candleDataList);
    volumeSeriesRef.current.setData(showVolume ? volumeDataList : []);
    chartRef.current.timeScale().fitContent();
  }, [candles, showVolume]);

  // Update Indicator Overlay Series (EMA9, EMA20, SMA50)
  useEffect(() => {
    if (!ema9SeriesRef.current || !ema20SeriesRef.current || !sma50SeriesRef.current) {
      return;
    }

    if (!indicatorSeries || !indicatorSeries.timestamps || indicatorSeries.timestamps.length === 0) {
      ema9SeriesRef.current.setData([]);
      ema20SeriesRef.current.setData([]);
      sma50SeriesRef.current.setData([]);
      return;
    }

    const ema9Points: LineData[] = [];
    const ema20Points: LineData[] = [];
    const sma50Points: LineData[] = [];

    const n = indicatorSeries.timestamps.length;
    let latestEma9: number | null = null;
    let latestEma20: number | null = null;
    let latestSma50: number | null = null;

    for (let i = 0; i < n; i++) {
      const epochSec = Math.floor(new Date(indicatorSeries.timestamps[i]).getTime() / 1000) as UTCTimestamp;
      if (isNaN(epochSec)) continue;

      if (indicatorSeries.ema9[i] !== null && indicatorSeries.ema9[i] !== undefined) {
        const val = indicatorSeries.ema9[i]!;
        if (showEma9) ema9Points.push({ time: epochSec, value: val });
        latestEma9 = val;
      }
      if (indicatorSeries.ema20[i] !== null && indicatorSeries.ema20[i] !== undefined) {
        const val = indicatorSeries.ema20[i]!;
        if (showEma20) ema20Points.push({ time: epochSec, value: val });
        latestEma20 = val;
      }
      if (indicatorSeries.sma50[i] !== null && indicatorSeries.sma50[i] !== undefined) {
        const val = indicatorSeries.sma50[i]!;
        if (showSma50) sma50Points.push({ time: epochSec, value: val });
        latestSma50 = val;
      }
    }

    lastIndicatorsRef.current.ema9 = latestEma9;
    lastIndicatorsRef.current.ema20 = latestEma20;
    lastIndicatorsRef.current.sma50 = latestSma50;
    lastIndicatorsRef.current.prevEma9 = latestEma9;
    lastIndicatorsRef.current.prevEma20 = latestEma20;
    lastIndicatorsRef.current.ema9Acc = latestEma9;
    lastIndicatorsRef.current.prevEma9Acc = latestEma9;
    lastIndicatorsRef.current.ema20Acc = latestEma20;
    lastIndicatorsRef.current.prevEma20Acc = latestEma20;

    // Strict chronological sort by timestamp
    ema9Points.sort((a, b) => (a.time as number) - (b.time as number));
    ema20Points.sort((a, b) => (a.time as number) - (b.time as number));
    sma50Points.sort((a, b) => (a.time as number) - (b.time as number));

    ema9SeriesRef.current.setData(showEma9 ? ema9Points : []);
    ema20SeriesRef.current.setData(showEma20 ? ema20Points : []);
    sma50SeriesRef.current.setData(showSma50 ? sma50Points : []);
  }, [indicatorSeries, showEma9, showEma20, showSma50]);

  // Phase 10B: Render Trade and Order Execution Markers
  useEffect(() => {
    if (!candleSeriesRef.current) return;

    if (!showMarkers || !markers || markers.length === 0) {
      candleSeriesRef.current.setMarkers([]);
      return;
    }

    // De-duplicate markers by unique id (or time+type+price) to prevent duplicate renders
    const seenMarkerKeys = new Set<string>();
    const uniqueMarkers: typeof markers = [];
    for (const m of markers) {
      const key = m.id || `${m.time}-${m.type}-${m.price}`;
      if (!seenMarkerKeys.has(key)) {
        seenMarkerKeys.add(key);
        uniqueMarkers.push(m);
      }
    }

    const chartMarkers: SeriesMarker<UTCTimestamp>[] = uniqueMarkers
      .map((m) => {
        let position: SeriesMarkerPosition = "aboveBar";
        let shape: SeriesMarkerShape = "circle";
        let color = "#38bdf8";
        let defaultText = "";

        switch (m.type) {
          case "BUY_EXECUTION":
            position = "belowBar";
            shape = "arrowUp";
            color = "#10b981"; // Emerald
            defaultText = `BUY @ ₹${formatPrice(m.price)}`;
            break;
          case "SELL_EXECUTION":
            position = "aboveBar";
            shape = "arrowDown";
            color = "#ef4444"; // Rose
            defaultText = `SELL @ ₹${formatPrice(m.price)}`;
            break;
          case "SL_EXIT":
            position = "aboveBar";
            shape = "square";
            color = "#f43f5e"; // Bright Rose
            defaultText = `SL EXIT @ ₹${formatPrice(m.price)}`;
            break;
          case "TP_EXIT":
            position = "aboveBar";
            shape = "circle";
            color = "#10b981"; // Emerald
            defaultText = `TP EXIT @ ₹${formatPrice(m.price)}`;
            break;
          case "SIGNAL_BUY":
            position = "belowBar";
            shape = "circle";
            color = "#38bdf8"; // Sky Blue
            defaultText = "SIG: BUY";
            break;
          case "SIGNAL_SELL":
            position = "aboveBar";
            shape = "circle";
            color = "#f59e0b"; // Amber
            defaultText = "SIG: SELL";
            break;
        }

        return {
          time: m.time as UTCTimestamp,
          position,
          shape,
          color,
          text: m.text || defaultText,
          id: m.id,
        };
      })
      // Lightweight Charts strictly requires markers to be sorted by time ascending.
      // Tie-break with ID for deterministic ordering at the same timestamp.
      .sort((a, b) => {
        const timeDiff = (a.time as number) - (b.time as number);
        if (timeDiff !== 0) return timeDiff;
        return (a.id || "").localeCompare(b.id || "");
      });

    candleSeriesRef.current.setMarkers(chartMarkers);
  }, [markers, showMarkers]);

  // Phase 10B: Active Stop-Loss and Take-Profit Visual Price Lines
  useEffect(() => {
    if (!candleSeriesRef.current) return;

    // 1. Stop Loss Price Line
    if (stopLossLineRef.current) {
      try {
        candleSeriesRef.current.removePriceLine(stopLossLineRef.current);
      } catch {}
      stopLossLineRef.current = null;
    }

    if (showPriceLines && stopLoss !== null && stopLoss !== undefined && stopLoss > 0) {
      stopLossLineRef.current = candleSeriesRef.current.createPriceLine({
        price: stopLoss,
        color: "#ef4444",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `SL ₹${formatPrice(stopLoss)}`,
      });
    }

    // 2. Take Profit Price Line
    if (takeProfitLineRef.current) {
      try {
        candleSeriesRef.current.removePriceLine(takeProfitLineRef.current);
      } catch {}
      takeProfitLineRef.current = null;
    }

    if (showPriceLines && takeProfit !== null && takeProfit !== undefined && takeProfit > 0) {
      takeProfitLineRef.current = candleSeriesRef.current.createPriceLine({
        price: takeProfit,
        color: "#10b981",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: `TP ₹${formatPrice(takeProfit)}`,
      });
    }
  }, [stopLoss, takeProfit, showPriceLines]);

  // Phase 10B: Live Streaming Candle Updates (O(1) update without full re-render)
  useEffect(() => {
    if (!liveCandle || !candleSeriesRef.current || !volumeSeriesRef.current) {
      return;
    }

    const { candle } = liveCandle;
    const epochSec = Math.floor(new Date(candle.timestamp).getTime() / 1000) as UTCTimestamp;
    if (isNaN(epochSec)) return;

    const all = allCandlesRef.current;
    const last = all.length > 0 ? all[all.length - 1] : null;
    const lastEpoch = last ? Math.floor(new Date(last.timestamp).getTime() / 1000) : -1;

    const isUp = candle.close >= candle.open;
    const candleBar: CandlestickData = {
      time: epochSec,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
    };
    const volBar: HistogramData = {
      time: epochSec,
      value: candle.volume,
      color: isUp ? "rgba(16, 185, 129, 0.35)" : "rgba(239, 68, 68, 0.35)",
    };

    const isUpdateToCurrent = Boolean(last && epochSec === lastEpoch);
    const isNewBar = Boolean(!last || epochSec > lastEpoch);

    if (isUpdateToCurrent) {
      // Incoming update to current bar
      candleSeriesRef.current.update(candleBar);
      if (showVolume) volumeSeriesRef.current.update(volBar);
      all[all.length - 1] = candle;
    } else if (isNewBar) {
      // Chronological new candle
      candleSeriesRef.current.update(candleBar);
      if (showVolume) volumeSeriesRef.current.update(volBar);
      all.push(candle);
    } else {
      // Past / out-of-order candle: ignore safely to prevent chart corruption
      return;
    }

    // Online incremental indicator calculation for streaming visualization
    const indState = lastIndicatorsRef.current;

    if (isNewBar) {
      indState.closes.push(candle.close);
      indState.prevEma9Acc = indState.ema9Acc;
      indState.prevEma20Acc = indState.ema20Acc;
      indState.prevEma9 = indState.ema9;
      indState.prevEma20 = indState.ema20;
    } else if (isUpdateToCurrent) {
      if (indState.closes.length > 0) {
        indState.closes[indState.closes.length - 1] = candle.close;
      } else {
        indState.closes.push(candle.close);
      }
    }

    // Online EMA 9 (alpha = 2 / (9 + 1) = 0.2)
    // Uses previous finalized bar accumulator so intra-bar ticks do not compound
    const prevEma9Acc = indState.prevEma9Acc;
    const currentEma9Acc =
      prevEma9Acc !== null ? 0.2 * candle.close + 0.8 * prevEma9Acc : candle.close;
    indState.ema9Acc = currentEma9Acc;

    // Strict warm-up: EMA9 requires at least 9 data points before outputting (or already warmed up from backend)
    let newEma9: number | null = null;
    if (indState.closes.length >= 9 || indState.prevEma9 !== null) {
      newEma9 = currentEma9Acc;
      indState.ema9 = newEma9;
      if (showEma9 && ema9SeriesRef.current) {
        ema9SeriesRef.current.update({ time: epochSec, value: newEma9 });
      }
    }

    // Online EMA 20 (alpha = 2 / (20 + 1) = 2/21)
    const prevEma20Acc = indState.prevEma20Acc;
    const currentEma20Acc =
      prevEma20Acc !== null
        ? (2 / 21) * candle.close + (19 / 21) * prevEma20Acc
        : candle.close;
    indState.ema20Acc = currentEma20Acc;

    // Strict warm-up: EMA20 requires at least 20 data points before outputting (or already warmed up from backend)
    let newEma20: number | null = null;
    if (indState.closes.length >= 20 || indState.prevEma20 !== null) {
      newEma20 = currentEma20Acc;
      indState.ema20 = newEma20;
      if (showEma20 && ema20SeriesRef.current) {
        ema20SeriesRef.current.update({ time: epochSec, value: newEma20 });
      }
    }

    // Online SMA 50 (rolling average of last 50 closes)
    let newSma50: number | null = null;
    if (indState.closes.length >= 50) {
      const window50 = indState.closes.slice(-50);
      const sum50 = window50.reduce((acc, v) => acc + v, 0);
      newSma50 = sum50 / 50;
      indState.sma50 = newSma50;
      if (showSma50 && sma50SeriesRef.current) {
        sma50SeriesRef.current.update({ time: epochSec, value: newSma50 });
      }
    }

    // Update HUD with live candle metrics
    const change = candle.close - candle.open;
    const changePercent = candle.open !== 0 ? (change / candle.open) * 100 : 0;
    setHoverData({
      time: formatDateTimeIST(epochSec),
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
      volume: candle.volume,
      change,
      changePercent,
      ema9: newEma9,
      ema20: newEma20,
      sma50: indState.sma50,
    });
  }, [liveCandle, showVolume, showEma9, showEma20, showSma50]);

  return (
    <div className="relative w-full h-full flex flex-col bg-[#0a0d14] overflow-hidden">
      {/* Top HUD: OHLCV Bar + Indicator Overlay Toggles + Markers/Lines Controls */}
      <div className="h-10 px-4 border-b border-[#1e293b] bg-[#0e1420]/90 backdrop-blur flex items-center justify-between text-xs font-mono shrink-0 z-10">
        <div className="flex items-center space-x-3 overflow-x-auto no-scrollbar">
          {/* Symbol & Timeframe badge */}
          <div className="flex items-center space-x-1.5 shrink-0">
            <span className="font-bold text-slate-100 tracking-wider">
              {symbol}
            </span>
            <span className="px-1.5 py-0.2 bg-emerald-500/10 text-emerald-400 text-[10px] rounded border border-emerald-500/20 font-semibold">
              {timeframe}
            </span>
            <span className="text-[10px] text-slate-500 font-sans">NSE</span>
          </div>

          {/* OHLC Metrics */}
          {hoverData && (
            <div className="hidden lg:flex items-center space-x-2.5 text-[11px] shrink-0">
              <div>
                <span className="text-slate-500 mr-1">O</span>
                <span className="text-slate-200 font-medium">
                  {formatPrice(hoverData.open)}
                </span>
              </div>
              <div>
                <span className="text-slate-500 mr-1">H</span>
                <span className="text-emerald-400 font-medium">
                  {formatPrice(hoverData.high)}
                </span>
              </div>
              <div>
                <span className="text-slate-500 mr-1">L</span>
                <span className="text-rose-400 font-medium">
                  {formatPrice(hoverData.low)}
                </span>
              </div>
              <div>
                <span className="text-slate-500 mr-1">C</span>
                <span className="text-slate-200 font-medium">
                  {formatPrice(hoverData.close)}
                </span>
              </div>
              <div>
                <span
                  className={`font-semibold ${
                    hoverData.change >= 0 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {hoverData.change >= 0 ? "+" : ""}
                  {formatPrice(hoverData.change)} ({hoverData.changePercent >= 0 ? "+" : ""}
                  {hoverData.changePercent.toFixed(2)}%)
                </span>
              </div>
            </div>
          )}

          {/* Live Indicator Value Pills */}
          {hoverData && (
            <div className="hidden xl:flex items-center space-x-2 text-[10px] text-slate-300 shrink-0 border-l border-[#1e293b] pl-2.5">
              {hoverData.ema9 !== undefined && hoverData.ema9 !== null && (
                <span className="text-sky-400">
                  EMA9: {hoverData.ema9.toFixed(2)}
                </span>
              )}
              {hoverData.ema20 !== undefined && hoverData.ema20 !== null && (
                <span className="text-amber-400">
                  EMA20: {hoverData.ema20.toFixed(2)}
                </span>
              )}
              {hoverData.sma50 !== undefined && hoverData.sma50 !== null && (
                <span className="text-purple-400">
                  SMA50: {hoverData.sma50.toFixed(2)}
                </span>
              )}
              {hoverData.rsi14 !== undefined && hoverData.rsi14 !== null && (
                <span className="text-cyan-300">
                  RSI: {hoverData.rsi14.toFixed(1)}
                </span>
              )}
              {hoverData.atrp14 !== undefined && hoverData.atrp14 !== null && (
                <span className="text-slate-400">
                  ATRP: {hoverData.atrp14.toFixed(2)}%
                </span>
              )}
            </div>
          )}
        </div>

        {/* Right HUD Controls: Indicator & Marker Toggles */}
        <div className="flex items-center space-x-1.5 shrink-0">
          <button
            onClick={() => setShowEma9((prev) => !prev)}
            title="Toggle EMA 9 Overlay"
            className={`px-2 py-0.5 text-[10px] font-mono rounded flex items-center space-x-1 transition-colors border ${
              showEma9
                ? "bg-sky-500/20 text-sky-300 border-sky-500/30"
                : "bg-[#182030] text-slate-500 border-transparent hover:text-slate-300"
            }`}
          >
            {showEma9 ? <Eye className="w-2.5 h-2.5" /> : <EyeOff className="w-2.5 h-2.5" />}
            <span>EMA 9</span>
          </button>

          <button
            onClick={() => setShowEma20((prev) => !prev)}
            title="Toggle EMA 20 Overlay"
            className={`px-2 py-0.5 text-[10px] font-mono rounded flex items-center space-x-1 transition-colors border ${
              showEma20
                ? "bg-amber-500/20 text-amber-300 border-amber-500/30"
                : "bg-[#182030] text-slate-500 border-transparent hover:text-slate-300"
            }`}
          >
            {showEma20 ? <Eye className="w-2.5 h-2.5" /> : <EyeOff className="w-2.5 h-2.5" />}
            <span>EMA 20</span>
          </button>

          <button
            onClick={() => setShowSma50((prev) => !prev)}
            title="Toggle SMA 50 Overlay"
            className={`px-2 py-0.5 text-[10px] font-mono rounded flex items-center space-x-1 transition-colors border ${
              showSma50
                ? "bg-purple-500/20 text-purple-300 border-purple-500/30"
                : "bg-[#182030] text-slate-500 border-transparent hover:text-slate-300"
            }`}
          >
            {showSma50 ? <Eye className="w-2.5 h-2.5" /> : <EyeOff className="w-2.5 h-2.5" />}
            <span>SMA 50</span>
          </button>

          <button
            onClick={() => setShowVolume((prev) => !prev)}
            title="Toggle Volume Sub-Pane"
            className={`px-2 py-0.5 text-[10px] font-mono rounded flex items-center space-x-1 transition-colors border ${
              showVolume
                ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
                : "bg-[#182030] text-slate-500 border-transparent hover:text-slate-300"
            }`}
          >
            <span>VOL</span>
          </button>

          {/* Phase 10B Trade Markers Toggle */}
          <button
            onClick={() => setShowMarkers((prev) => !prev)}
            title="Toggle Executed Trade & Order Markers"
            className={`px-2 py-0.5 text-[10px] font-mono rounded flex items-center space-x-1 transition-colors border ${
              showMarkers
                ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
                : "bg-[#182030] text-slate-500 border-transparent hover:text-slate-300"
            }`}
          >
            <TrendingUp className="w-2.5 h-2.5" />
            <span>TRADES ({markers.length})</span>
          </button>

          {/* Phase 10B SL/TP Price Lines Toggle */}
          <button
            onClick={() => setShowPriceLines((prev) => !prev)}
            title="Toggle Stop-Loss & Take-Profit Visual Price Lines"
            className={`px-2 py-0.5 text-[10px] font-mono rounded flex items-center space-x-1 transition-colors border ${
              showPriceLines
                ? "bg-rose-500/20 text-rose-300 border-rose-500/30"
                : "bg-[#182030] text-slate-500 border-transparent hover:text-slate-300"
            }`}
          >
            <Crosshair className="w-2.5 h-2.5" />
            <span>SL/TP</span>
          </button>
        </div>
      </div>

      {/* Chart Canvas Area */}
      <div className="relative flex-1 w-full h-full min-h-0">
        <div ref={chartContainerRef} className="w-full h-full" />

        {/* Loading Overlay */}
        {isLoading && (
          <div className="absolute inset-0 bg-[#0a0d14]/70 backdrop-blur-xs flex items-center justify-center z-20">
            <div className="flex flex-col items-center space-y-3 bg-[#131a27] border border-[#1e293b] px-6 py-4 rounded-xl shadow-xl">
              <Loader2 className="w-6 h-6 text-emerald-400 animate-spin" />
              <div className="text-xs font-mono text-slate-300">
                Fetching {symbol} ({timeframe}) market & indicator data...
              </div>
            </div>
          </div>
        )}

        {/* Error Overlay */}
        {error && !isLoading && (
          <div className="absolute inset-0 bg-[#0a0d14]/90 flex items-center justify-center p-6 z-20">
            <div className="max-w-md w-full bg-[#131a27] border border-rose-500/30 rounded-xl p-6 text-center space-y-3 shadow-2xl">
              <div className="w-10 h-10 rounded-full bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mx-auto">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-semibold text-slate-100 font-mono">
                Failed to Load Market Data
              </h3>
              <p className="text-xs text-slate-400 font-mono break-words">
                {error}
              </p>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="mt-2 inline-flex items-center space-x-1.5 px-3.5 py-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 text-xs font-mono rounded-md border border-emerald-500/30 transition-colors"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry Fetch</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* Empty State Overlay */}
        {!isLoading && !error && (!candles || candles.length === 0) && (
          <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
            <div className="flex flex-col items-center space-y-2 text-slate-500 text-xs font-mono">
              <BarChart2 className="w-8 h-8 stroke-1 text-slate-600" />
              <span>No candlestick data available for {symbol} ({timeframe})</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
