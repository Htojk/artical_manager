import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEventSource } from "./useEventSource";
import type { AppEvent } from "../types";

class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  closed = false;

  private listeners = new Map<string, EventListenerOrEventListenerObject[]>();

  constructor(url: string | URL) {
    this.url = String(url);
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (!listener) return;
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close() {
    this.closed = true;
  }

  emitOpen() {
    this.onopen?.();
  }

  emitError() {
    this.onerror?.();
  }

  emitNamed(type: string, payload: unknown) {
    const event = new MessageEvent<string>(type, { data: JSON.stringify(payload) });
    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") {
        (listener as EventListener)(event);
      } else {
        listener.handleEvent(event);
      }
    }
  }
}

function Harness({
  onReconnect,
  onEvent,
}: {
  onReconnect?: () => void;
  onEvent?: (event: AppEvent) => void;
}) {
  const { status, reconnectAttempts } = useEventSource({
    url: "/api/events",
    eventTypes: ["stage.status"],
    minDelayMs: 1000,
    maxDelayMs: 4000,
    onReconnect,
    onEvent,
  });
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="attempts">{reconnectAttempts}</span>
    </div>
  );
}

describe("useEventSource", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });

  it("reconnects with exponential backoff and refreshes after reconnect", () => {
    const onReconnect = vi.fn();
    render(<Harness onReconnect={onReconnect} />);

    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0]?.url).toBe("/api/events");
    expect(screen.getByTestId("status")).toHaveTextContent("connecting");

    act(() => MockEventSource.instances[0]?.emitOpen());
    expect(screen.getByTestId("status")).toHaveTextContent("open");

    act(() => MockEventSource.instances[0]?.emitError());
    expect(screen.getByTestId("status")).toHaveTextContent("error");
    expect(screen.getByTestId("attempts")).toHaveTextContent("1");

    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(MockEventSource.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => MockEventSource.instances[1]?.emitError());
    expect(screen.getByTestId("attempts")).toHaveTextContent("2");

    act(() => {
      vi.advanceTimersByTime(1999);
    });
    expect(MockEventSource.instances).toHaveLength(2);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(MockEventSource.instances).toHaveLength(3);

    act(() => MockEventSource.instances[2]?.emitOpen());
    expect(screen.getByTestId("status")).toHaveTextContent("open");
    expect(screen.getByTestId("attempts")).toHaveTextContent("0");
    expect(onReconnect).toHaveBeenCalledTimes(1);
  });

  it("parses named events and forwards article events", () => {
    const onEvent = vi.fn();
    render(<Harness onEvent={onEvent} />);

    act(() => {
      MockEventSource.instances[0]?.emitNamed("stage.status", {
        type: "stage.status",
        article_id: "article-1",
        run_id: "run-1",
        data: { stage: "writing", status: "running" },
      });
    });

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "stage.status",
        article_id: "article-1",
        run_id: "run-1",
        data: { stage: "writing", status: "running" },
      }),
    );
  });
});
