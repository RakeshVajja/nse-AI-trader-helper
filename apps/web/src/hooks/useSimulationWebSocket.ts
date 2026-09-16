"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  isValidSimulationEvent,
  SimulationEvent,
  WebSocketConnectionState,
} from "@/types";

export interface UseSimulationWebSocketOptions {
  /** Target simulation session ID to stream events for. */
  simulationId: string | null;
  /** Whether the socket should automatically connect when simulationId is provided. Defaults to true. */
  enabled?: boolean;
  /** Whether to automatically attempt reconnection if disconnected unexpectedly. Defaults to true. */
  autoReconnect?: boolean;
  /** Maximum number of reconnection attempts before giving up. Defaults to 5. */
  maxReconnectAttempts?: number;
  /** Base interval between reconnection attempts in milliseconds. Defaults to 2000. */
  reconnectIntervalMs?: number;
  /** Optional callback invoked whenever a valid typed event is received. */
  onEvent?: (event: SimulationEvent) => void;
  /** Optional callback invoked on socket error. */
  onError?: (error: Event) => void;
}

export interface UseSimulationWebSocketReturn {
  /** Current connection lifecycle state. */
  connectionState: WebSocketConnectionState;
  /** The most recently received and parsed typed simulation event. */
  lastEvent: SimulationEvent | null;
  /** Convenient boolean flag indicating if the socket is currently connected. */
  isConnected: boolean;
  /** Manually trigger connection. */
  connect: () => void;
  /** Manually trigger clean disconnection. */
  disconnect: () => void;
  /** Send message or ping payload to the backend server. */
  send: (data: string | object) => void;
}

function buildWebSocketUrl(simulationId: string): string {
  const apiBase =
    process.env.NEXT_PUBLIC_WS_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000";

  const isSecure = apiBase.startsWith("https") || apiBase.startsWith("wss");
  const wsProtocol = isSecure ? "wss" : "ws";
  const cleanHost = apiBase
    .replace(/^(https?|wss?):\/\//, "")
    .replace(/\/api\/v1\/?$/, "")
    .replace(/\/$/, "");

  return `${wsProtocol}://${cleanHost}/ws/simulations/${simulationId}`;
}

export function useSimulationWebSocket({
  simulationId,
  enabled = true,
  autoReconnect = true,
  maxReconnectAttempts = 5,
  reconnectIntervalMs = 2000,
  onEvent,
  onError,
}: UseSimulationWebSocketOptions): UseSimulationWebSocketReturn {
  const [connectionState, setConnectionState] =
    useState<WebSocketConnectionState>("DISCONNECTED");
  const [lastEvent, setLastEvent] = useState<SimulationEvent | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const unmountedRef = useRef<boolean>(false);

  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    clearReconnectTimer();
    reconnectAttemptsRef.current = 0;

    if (wsRef.current) {
      // Avoid firing onclose handler side-effects
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.onopen = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    setConnectionState("DISCONNECTED");
  }, [clearReconnectTimer]);

  const connect = useCallback(() => {
    if (!simulationId || typeof window === "undefined") {
      return;
    }

    // Clean existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    clearReconnectTimer();
    setConnectionState("CONNECTING");

    try {
      const url = buildWebSocketUrl(simulationId);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (unmountedRef.current) {
          ws.close();
          return;
        }
        setConnectionState("CONNECTED");
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (messageEvent: MessageEvent) => {
        if (unmountedRef.current) return;

        try {
          const parsed: unknown = JSON.parse(messageEvent.data);
          if (isValidSimulationEvent(parsed)) {
            // Strictly guard against cross-simulation event leakage
            if (simulationId && parsed.simulation_id !== simulationId) {
              return;
            }
            setLastEvent(parsed);
            onEventRef.current?.(parsed);
          }
        } catch {
          // Discard unparseable non-event frames safely
        }
      };

      ws.onerror = (errorEvt: Event) => {
        if (unmountedRef.current) return;
        setConnectionState("ERROR");
        onErrorRef.current?.(errorEvt);
      };

      ws.onclose = (closeEvent: CloseEvent) => {
        if (unmountedRef.current) return;

        setConnectionState("DISCONNECTED");
        wsRef.current = null;

        // Normal closure (1000) or explicit 4404 simulation not found -> do not reconnect
        if (closeEvent.code === 1000 || closeEvent.code === 4404) {
          return;
        }

        // Auto-reconnection logic
        if (autoReconnect && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current += 1;
          const delay = reconnectIntervalMs * Math.min(reconnectAttemptsRef.current, 3);
          clearReconnectTimer();
          reconnectTimerRef.current = setTimeout(() => {
            if (!unmountedRef.current && enabled) {
              connect();
            }
          }, delay);
        }
      };
    } catch {
      setConnectionState("ERROR");
    }
  }, [
    simulationId,
    enabled,
    autoReconnect,
    maxReconnectAttempts,
    reconnectIntervalMs,
    clearReconnectTimer,
  ]);

  const send = useCallback((data: string | object) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const payload = typeof data === "string" ? data : JSON.stringify(data);
      wsRef.current.send(payload);
    }
  }, []);

  // Sync connection state with simulationId and enabled flag
  useEffect(() => {
    unmountedRef.current = false;

    if (enabled && simulationId) {
      connect();
    } else {
      disconnect();
    }

    return () => {
      unmountedRef.current = true;
      disconnect();
    };
  }, [simulationId, enabled, connect, disconnect]);

  return {
    connectionState,
    lastEvent,
    isConnected: connectionState === "CONNECTED",
    connect,
    disconnect,
    send,
  };
}
