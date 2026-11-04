import { useEffect, useRef, useState } from "react";
import type { AppEvent } from "../types";

export type EventSourceStatus = "connecting" | "open" | "error" | "disabled";

const DEFAULT_EVENT_TYPES = [
  "connected",
  "stage.status",
  "artifact.created",
  "review.completed",
  "publish.updated",
  "run.status",
  "run.finished",
];

export interface UseEventSourceOptions {
  url?: string;
  enabled?: boolean;
  eventTypes?: string[];
  onEvent?: (event: AppEvent) => void;
  onOpen?: (reconnected: boolean) => void;
  onReconnect?: () => void;
  onError?: () => void;
  minDelayMs?: number;
  maxDelayMs?: number;
}

export interface UseEventSourceResult {
  status: EventSourceStatus;
  reconnectAttempts: number;
}

function parseEvent(event: MessageEvent<string>, fallbackType: string): AppEvent {
  try {
    const parsed = JSON.parse(event.data) as unknown;
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      return {
        type: typeof record.type === "string" ? record.type : fallbackType,
        article_id: typeof record.article_id === "string" ? record.article_id : null,
        run_id: typeof record.run_id === "string" ? record.run_id : null,
        data:
          typeof record.data === "object" && record.data !== null
            ? (record.data as Record<string, unknown>)
            : {},
        created_at: typeof record.created_at === "string" ? record.created_at : undefined,
      };
    }
  } catch {
    // Heartbeats and non-JSON events are intentionally ignored.
  }
  return { type: fallbackType, data: {} };
}

/**
 * Keeps an EventSource open with exponential-backoff reconnects. The reconnect
 * callback is the signal for a caller to perform a full query refresh, because
 * events emitted while disconnected are not replayed by the backend.
 */
export function useEventSource({
  url = "/api/events",
  enabled = true,
  eventTypes = DEFAULT_EVENT_TYPES,
  onEvent,
  onOpen,
  onReconnect,
  onError,
  minDelayMs = 1000,
  maxDelayMs = 30000,
}: UseEventSourceOptions = {}): UseEventSourceResult {
  const [status, setStatus] = useState<EventSourceStatus>(
    enabled ? "connecting" : "disabled",
  );
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  const onEventRef = useRef(onEvent);
  const onOpenRef = useRef(onOpen);
  const onReconnectRef = useRef(onReconnect);
  const onErrorRef = useRef(onError);
  const eventTypesRef = useRef(eventTypes);
  onEventRef.current = onEvent;
  onOpenRef.current = onOpen;
  onReconnectRef.current = onReconnect;
  onErrorRef.current = onError;
  eventTypesRef.current = eventTypes;

  const eventTypesKey = eventTypes.join("|");

  useEffect(() => {
    if (!enabled) {
      setStatus("disabled");
      return;
    }

    let source: EventSource | null = null;
    let retryTimer: number | undefined;
    let disposed = false;
    let attempt = 0;
    let hasConnected = false;
    setStatus("connecting");

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");
      source = new EventSource(url);

      source.onopen = () => {
        if (disposed) return;
        const reconnected = hasConnected || attempt > 0;
        hasConnected = true;
        attempt = 0;
        setReconnectAttempts(0);
        setStatus("open");
        onOpenRef.current?.(reconnected);
        if (reconnected) onReconnectRef.current?.();
      };

      source.onerror = () => {
        if (disposed) return;
        source?.close();
        source = null;
        setStatus("error");
        onErrorRef.current?.();
        const delay = Math.min(minDelayMs * 2 ** attempt, maxDelayMs);
        attempt += 1;
        setReconnectAttempts(attempt);
        retryTimer = window.setTimeout(connect, delay);
      };

      const handleMessage = (event: MessageEvent<string>) => {
        onEventRef.current?.(parseEvent(event, "message"));
      };
      source.onmessage = handleMessage;
      for (const type of eventTypesRef.current) {
        source.addEventListener(type, handleMessage as EventListener);
      }
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      source?.close();
    };
  }, [enabled, url, eventTypesKey, minDelayMs, maxDelayMs]);

  return { status, reconnectAttempts };
}
