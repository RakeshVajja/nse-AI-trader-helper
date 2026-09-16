import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSimulationWebSocket } from "../hooks/useSimulationWebSocket";
import { SimulationEvent } from "../types";

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  readyState: number = WebSocket.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  simulateOpen() {
    this.readyState = WebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  simulateMessage(data: unknown) {
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    this.onmessage?.(new MessageEvent("message", { data: payload }));
  }

  simulateClose(code = 1000, reason = "") {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  simulateError() {
    this.onerror?.(new Event("error"));
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = "") {
    this.readyState = WebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }
}

describe("useSimulationWebSocket Hook", () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    MockWebSocket.instances = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    global.WebSocket = MockWebSocket as any;
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
    vi.useRealTimers();
  });

  it("does not connect if simulationId is null", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: null })
    );

    expect(result.current.connectionState).toBe("DISCONNECTED");
    expect(result.current.isConnected).toBe(false);
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it("does not connect if enabled is false", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123", enabled: false })
    );

    expect(result.current.connectionState).toBe("DISCONNECTED");
    expect(MockWebSocket.instances.length).toBe(0);
  });

  it("connects and updates state to CONNECTING then CONNECTED on open", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123" })
    );

    expect(result.current.connectionState).toBe("CONNECTING");
    expect(MockWebSocket.instances.length).toBe(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/simulations/sim-123");

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    expect(result.current.connectionState).toBe("CONNECTED");
    expect(result.current.isConnected).toBe(true);
  });

  it("receives and parses valid typed simulation events", () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123", onEvent })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    const mockEvent: SimulationEvent = {
      event_type: "candle_update",
      simulation_id: "sim-123",
      wall_clock_timestamp: "2026-09-16T05:00:00Z",
      virtual_timestamp: "2026-01-01T09:15:00Z",
      sequence: 1,
      payload: {
        step_index: 1,
        candle: {
          timestamp: "2026-01-01T09:15:00Z",
          open: 2400,
          high: 2420,
          low: 2390,
          close: 2415,
          volume: 10000,
        },
      },
    };

    act(() => {
      MockWebSocket.instances[0].simulateMessage(mockEvent);
    });

    expect(result.current.lastEvent).toEqual(mockEvent);
    expect(onEvent).toHaveBeenCalledWith(mockEvent);
  });

  it("safely ignores malformed non-JSON messages without throwing", () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123", onEvent })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    act(() => {
      MockWebSocket.instances[0].simulateMessage("NOT A JSON STRING");
    });

    expect(result.current.lastEvent).toBeNull();
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("sets error state on socket error", () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123", onError })
    );

    act(() => {
      MockWebSocket.instances[0].simulateError();
    });

    expect(result.current.connectionState).toBe("ERROR");
    expect(onError).toHaveBeenCalled();
  });

  it("sends outgoing messages through WebSocket when OPEN", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123" })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    act(() => {
      result.current.send({ type: "ping" });
    });

    expect(MockWebSocket.instances[0].sentMessages).toEqual([
      JSON.stringify({ type: "ping" }),
    ]);
  });

  it("cleans up and closes socket on unmount", () => {
    const { unmount } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123" })
    );

    const ws = MockWebSocket.instances[0];
    expect(ws.readyState).toBe(WebSocket.CONNECTING);

    unmount();

    expect(ws.readyState).toBe(WebSocket.CLOSED);
  });

  it("does not auto-reconnect on 4404 simulation not found or 1000 normal close", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({
        simulationId: "sim-123",
        autoReconnect: true,
        reconnectIntervalMs: 1000,
      })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
      MockWebSocket.instances[0].simulateClose(4404, "Simulation not found");
    });

    expect(result.current.connectionState).toBe("DISCONNECTED");

    // Advance timer past reconnect interval
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    // Should NOT have created a second instance
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it("auto-reconnects on unexpected socket disconnection (e.g., 1006)", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({
        simulationId: "sim-123",
        autoReconnect: true,
        reconnectIntervalMs: 1000,
      })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
      MockWebSocket.instances[0].simulateClose(1006, "Abnormal closure");
    });

    expect(result.current.connectionState).toBe("DISCONNECTED");

    // Advance timer to trigger reconnect
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // Reconnection created a new WebSocket instance!
    expect(MockWebSocket.instances.length).toBe(2);
    expect(result.current.connectionState).toBe("CONNECTING");
  });

  it("discards malformed events with invalid event_type, missing sequence, or missing payload", () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-123", onEvent })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    // 1. Unknown event_type
    act(() => {
      MockWebSocket.instances[0].simulateMessage({
        event_type: "unknown_custom_event",
        simulation_id: "sim-123",
        sequence: 1,
        wall_clock_timestamp: "2026-09-16T05:00:00Z",
        payload: {},
      });
    });
    expect(result.current.lastEvent).toBeNull();
    expect(onEvent).not.toHaveBeenCalled();

    // 2. Missing sequence
    act(() => {
      MockWebSocket.instances[0].simulateMessage({
        event_type: "candle_update",
        simulation_id: "sim-123",
        wall_clock_timestamp: "2026-09-16T05:00:00Z",
        payload: {},
      });
    });
    expect(result.current.lastEvent).toBeNull();

    // 3. Null or undefined payload
    act(() => {
      MockWebSocket.instances[0].simulateMessage({
        event_type: "candle_update",
        simulation_id: "sim-123",
        sequence: 2,
        wall_clock_timestamp: "2026-09-16T05:00:00Z",
        payload: null,
      });
    });
    expect(result.current.lastEvent).toBeNull();
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("discards events with mismatched simulation_id", () => {
    const onEvent = vi.fn();
    const { result } = renderHook(() =>
      useSimulationWebSocket({ simulationId: "sim-target-123", onEvent })
    );

    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    // Event targeting a DIFFERENT simulation
    act(() => {
      MockWebSocket.instances[0].simulateMessage({
        event_type: "candle_update",
        simulation_id: "sim-other-456",
        sequence: 1,
        wall_clock_timestamp: "2026-09-16T05:00:00Z",
        payload: { step_index: 1 },
      });
    });

    expect(result.current.lastEvent).toBeNull();
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("stops reconnecting after reaching maxReconnectAttempts", () => {
    const { result } = renderHook(() =>
      useSimulationWebSocket({
        simulationId: "sim-123",
        autoReconnect: true,
        maxReconnectAttempts: 2,
        reconnectIntervalMs: 1000,
      })
    );

    // First connection established
    act(() => {
      MockWebSocket.instances[0].simulateOpen();
    });

    // Disconnects unexpectedly (attempt 1)
    act(() => {
      MockWebSocket.instances[0].simulateClose(1006, "Abnormal closure 1");
      vi.advanceTimersByTime(2000);
    });
    expect(MockWebSocket.instances.length).toBe(2);

    // Reconnection 1 fails immediately without opening (attempt 2)
    act(() => {
      MockWebSocket.instances[1].simulateClose(1006, "Connection failed 2");
      vi.advanceTimersByTime(3000);
    });
    expect(MockWebSocket.instances.length).toBe(3);

    // Reconnection 2 fails immediately -> reaches maxReconnectAttempts (2)
    act(() => {
      MockWebSocket.instances[2].simulateClose(1006, "Connection failed 3");
      vi.advanceTimersByTime(10000);
    });

    // No further instances created!
    expect(MockWebSocket.instances.length).toBe(3);
    expect(result.current.connectionState).toBe("DISCONNECTED");
  });
});
