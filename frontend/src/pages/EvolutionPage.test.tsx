import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { EvolutionPage } from "./EvolutionPage";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../test/utils";
import type { EvolutionSuggestion } from "../types";

function suggestion(status: EvolutionSuggestion["status"]): EvolutionSuggestion {
  return {
    id: "suggestion-1",
    type: "writing_rule",
    target_stage: "writing",
    title: "减少背景铺垫，开头直接给结论",
    rationale: "近期 3 篇初稿的审核意见都指出开头冗长。",
    evidence: [{ note: "审核问题：开头铺垫超过 400 字" }],
    patch: { rule: "首段先给结论" },
    expected_impact: "预计降低返工率 15%",
    status,
    before_snapshot: { rule: "先铺垫背景" },
    after_snapshot: { rule: "首段先给结论" },
    baseline: {},
    result: {},
    decided_note: null,
    created_at: "2026-10-30T08:00:00.000Z",
    decided_at: null,
    applied_at: null,
  };
}

describe("EvolutionPage", () => {
  it("renders status badges, filters by status and confirms an action", async () => {
    const user = userEvent.setup();
    let currentStatus: EvolutionSuggestion["status"] = "pending";
    const approveBodies: unknown[] = [];
    const requestedStatuses: string[] = [];

    installFetchMock((url, init) => {
      const method = requestMethod(init);
      if (url.startsWith("/api/evolution/suggestions") && url.endsWith("/approve")) {
        expect(method).toBe("POST");
        approveBodies.push(requestBody(init));
        currentStatus = "approved";
        return jsonResponse(suggestion(currentStatus));
      }
      if (url.startsWith("/api/evolution/suggestions")) {
        const query = new URL(url, "http://localhost").searchParams.get("status");
        requestedStatuses.push(query ?? "all");
        const items =
          query && query !== currentStatus ? [] : [suggestion(currentStatus)];
        return jsonResponse({ items, total: items.length });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<EvolutionPage />);

    expect(
      await screen.findByRole("heading", { name: "减少背景铺垫，开头直接给结论" }),
    ).toBeInTheDocument();
    expect(screen.getByText("审核问题：开头铺垫超过 400 字")).toBeInTheDocument();
    expect(screen.getAllByText("待审批")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "批准" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("批准改进建议");
    expect(dialog).toHaveTextContent("批准后建议不会立即生效");
    await user.click(screen.getByRole("button", { name: "批准建议" }));

    await waitFor(() => {
      expect(approveBodies).toEqual([{ note: "" }]);
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getAllByText("待审批")).toHaveLength(1);
      expect(screen.getAllByText("已批准")).toHaveLength(2);
    });
    expect(screen.getByRole("button", { name: "应用" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "已应用" }));

    await waitFor(() => {
      expect(requestedStatuses).toContain("applied");
    });
    expect(await screen.findByText("该状态下没有建议")).toBeInTheDocument();
  });
});
