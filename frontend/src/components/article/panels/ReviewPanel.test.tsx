import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReviewPanel } from "./ReviewPanel";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../../../test/utils";
import type { StageDetail } from "../../../types";

const reviewDetail: StageDetail<"review"> = {
  stage: "review",
  label: "审核",
  stage_run: null,
  content: {
    latest: {
      id: "report-1",
      draft_version_id: "draft-1",
      scores: {},
      total: 88,
      verdict: "pass",
      rollback_to: null,
      rationale: "整体质量达标",
      model: "fake",
      config_version: "v1",
      created_at: "2026-11-03T08:00:00.000Z",
    },
    history: [],
    latest_decision: null,
  },
};

describe("ReviewPanel", () => {
  it("approves from the human review gate", async () => {
    const user = userEvent.setup();
    const calls: { method: string; body: unknown }[] = [];
    installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/stages/review" && requestMethod(init) === "GET") {
        return jsonResponse(reviewDetail);
      }
      if (url === "/api/articles/article-1/review/decision") {
        calls.push({ method: requestMethod(init), body: requestBody(init) });
        return jsonResponse({ id: "run-1", status: "running" });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<ReviewPanel articleId="article-1" waiting />);

    expect(await screen.findByText("人工审稿确认")).toBeInTheDocument();
    const reject = screen.getByRole("button", { name: "驳回并重新生成" });
    expect(reject).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "通过并继续" }));

    expect(await screen.findByText("已通过，工作流继续排版。")).toBeInTheDocument();
    expect(calls).toEqual([
      { method: "POST", body: { decision: "approve", feedback: "" } },
    ]);
  });

  it("rejects with feedback and requires non-empty feedback", async () => {
    const user = userEvent.setup();
    const calls: { method: string; body: unknown }[] = [];
    installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/stages/review" && requestMethod(init) === "GET") {
        return jsonResponse(reviewDetail);
      }
      if (url === "/api/articles/article-1/review/decision") {
        calls.push({ method: requestMethod(init), body: requestBody(init) });
        return jsonResponse({ id: "run-1", status: "running" });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<ReviewPanel articleId="article-1" waiting />);

    await screen.findByText("人工审稿确认");
    await user.type(screen.getByLabelText("驳回意见（驳回时必填）"), "章节结构需要调整");
    await user.click(screen.getByRole("button", { name: "驳回并重新生成" }));

    expect(await screen.findByText("已驳回，工作流按意见回退重生成。")).toBeInTheDocument();
    expect(calls).toEqual([
      {
        method: "POST",
        body: { decision: "reject", feedback: "章节结构需要调整" },
      },
    ]);
  });

  it("hides the decision form outside the waiting state", async () => {
    installFetchMock((url) =>
      url === "/api/articles/article-1/stages/review"
        ? jsonResponse(reviewDetail)
        : jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404),
    );

    renderWithProviders(<ReviewPanel articleId="article-1" />);

    expect(await screen.findByText("审核通过")).toBeInTheDocument();
    expect(screen.queryByText("人工审稿确认")).not.toBeInTheDocument();
  });
});
