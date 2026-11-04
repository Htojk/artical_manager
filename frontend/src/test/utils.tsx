import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/" }: { route?: string } = {},
) {
  const queryClient = createTestQueryClient();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function emptyResponse(status = 204): Response {
  return new Response(null, { status });
}

type FetchHandler = (url: string, init: RequestInit) => Response | Promise<Response>;

export function installFetchMock(handler: FetchHandler) {
  const mocked = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
      handler(String(input), init ?? {}),
  );
  vi.stubGlobal("fetch", mocked);
  return mocked;
}

export function requestMethod(init: RequestInit): string {
  return (init.method ?? "GET").toUpperCase();
}

export function requestBody(init: RequestInit): unknown {
  if (typeof init.body !== "string") return null;
  try {
    return JSON.parse(init.body) as unknown;
  } catch {
    return init.body;
  }
}
