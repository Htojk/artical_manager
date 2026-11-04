import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AnalyticsPage } from "./AnalyticsPage";
import { installFetchMock, jsonResponse, renderWithProviders } from "../test/utils";
import type { AnalyticsSummary } from "../types";

const emptySummary: AnalyticsSummary = {
  articles: 0,
  published_articles: 0,
  total_cost: 0,
  prompt_tokens: 0,
  completion_tokens: 0,
  metrics: {
    views: 0,
    likes: 0,
    comments: 0,
    shares: 0,
    revenue_cents: 0,
    revenue_yuan: 0,
    by_platform: {},
  },
  revenue_yuan: 0,
  roi: null,
};

function rangeOf(url: string): { from: string | null; to: string | null } {
  const params = new URL(url, "http://localhost").searchParams;
  return { from: params.get("from"), to: params.get("to") };
}

describe("AnalyticsPage", () => {
  it("shows empty states and refetches when a date preset changes", async () => {
    const user = userEvent.setup();
    const summaryCalls: string[] = [];
    const performanceCalls: string[] = [];

    installFetchMock((url) => {
      if (url.startsWith("/api/analytics/summary")) {
        summaryCalls.push(url);
        return jsonResponse(emptySummary);
      }
      if (url.startsWith("/api/analytics/performance")) {
        performanceCalls.push(url);
        return jsonResponse({ items: [], total: 0 });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<AnalyticsPage />);

    expect(await screen.findByText("暂无平台指标")).toBeInTheDocument();
    expect(screen.getByText("暂无文章表现")).toBeInTheDocument();
    expect(await screen.findByText("暂无数据")).toBeInTheDocument();
    expect(summaryCalls).toHaveLength(1);
    expect(performanceCalls).toHaveLength(1);

    const initialRange = rangeOf(summaryCalls[0]);
    expect(initialRange.from).toBeTruthy();
    expect(initialRange.to).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "最近 7 天" }));

    await waitFor(() => {
      expect(summaryCalls.length).toBeGreaterThanOrEqual(2);
      expect(performanceCalls.length).toBeGreaterThanOrEqual(2);
    });
    const latestRange = rangeOf(summaryCalls.at(-1) ?? "");
    expect(latestRange.from).not.toBe(initialRange.from);
    expect(latestRange.to).toBe(initialRange.to);
    expect(performanceCalls.at(-1)).toContain("from=");
    expect(await screen.findByText("暂无数据")).toBeInTheDocument();
  });
});
