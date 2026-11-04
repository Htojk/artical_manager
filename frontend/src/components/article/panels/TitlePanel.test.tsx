import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TitlePanel } from "./TitlePanel";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../../../test/utils";
import type { StageDetail, TitleVersion } from "../../../types";

function titleVersion(selected: string): TitleVersion {
  return {
    id: `title-${selected}`,
    version: 1,
    candidates: [
      {
        title: "为什么你的 AI 项目总是延期？",
        style: "悬念型",
        rationale: "制造疑问",
        score: 85,
      },
      {
        title: "AI 工程实践：三条落地经验",
        style: "干货型",
        rationale: "点出读者收益",
        score: 92,
      },
    ],
    selected_title: selected,
    strategy: "以读者收益为核心",
    model: "gpt-4o-mini",
    prompt_tokens: 1200,
    completion_tokens: 320,
    duration_ms: 900,
    created_by: "model",
    note: "模型优化",
    created_at: "2026-10-30T08:10:00.000Z",
  };
}

function stageDetail(latest: TitleVersion): StageDetail<"title_optimization"> {
  return {
    stage: "title_optimization",
    label: "标题优化",
    stage_run: null,
    content: { latest, history: [latest] },
  };
}

describe("TitlePanel", () => {
  it("shows candidates and replaces the article title after selecting one", async () => {
    const user = userEvent.setup();
    let selected = "AI 工程实践：三条落地经验";
    let putBody: unknown = null;

    installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/stages/title_optimization" && requestMethod(init) === "PUT") {
        putBody = requestBody(init);
        const body = requestBody(init) as { title: string };
        selected = body.title;
        return jsonResponse({
          ...titleVersion(selected),
          created_by: "user",
          note: "用户选择",
        });
      }
      if (url === "/api/articles/article-1/stages/title_optimization") {
        return jsonResponse(stageDetail(titleVersion(selected)));
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<TitlePanel articleId="article-1" />);

    expect(await screen.findByText("候选标题（2）")).toBeInTheDocument();
    expect(screen.getByText(/以读者收益为核心/)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "选择标题：为什么你的 AI 项目总是延期？" }),
    );

    await waitFor(() => {
      expect(putBody).toEqual({ title: "为什么你的 AI 项目总是延期？", note: "用户选择" });
    });
    expect(
      await screen.findByText("标题已更新，审核与排版将使用新标题。"),
    ).toBeInTheDocument();
  });
});
