import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { TopicPanel } from "./TopicPanel";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestMethod,
} from "../../../test/utils";
import type { Article, StageDetail, Topic } from "../../../types";

const topics: Topic[] = [
  {
    id: "topic-1",
    article_id: "article-1",
    source: "ai",
    title: "AI Agent 工程实践",
    angle: "从工作流编排与可观测性切入",
    rationale: "覆盖工程团队最关心的落地问题",
    target_platforms: ["wechat", "zhihu"],
    hot_signals: [],
    discussion_score: 86,
    discussion_reason: "工程团队与管理者对落地成本存在分歧",
    entertainment_score: 0,
    entertainment_reason: "",
    entertainment_scores: {},
    content_format: "hot_take",
    selected: false,
    created_at: "2026-10-30T08:00:00.000Z",
  },
  {
    id: "topic-2",
    article_id: "article-1",
    source: "ai_hot",
    title: "多智能体协作的边界",
    angle: "讨论协作成本与适用场景",
    rationale: "近期讨论热度较高",
    target_platforms: ["wechat"],
    hot_signals: [
      {
        title: "多智能体登上热榜",
        heat: 92,
        url: "https://example.com/hot",
      },
    ],
    discussion_score: 78,
    discussion_reason: "支持者与质疑者都有明确案例",
    entertainment_score: 0,
    entertainment_reason: "",
    entertainment_scores: {},
    content_format: "hot_take",
    selected: false,
    created_at: "2026-10-30T08:01:00.000Z",
  },
];

const article: Article = {
  id: "article-1",
  title: "",
  status: "waiting_topic",
  current_stage: "topic_selection",
  topic_mode: "ai",
  target_platforms: ["wechat", "zhihu"],
  publish_confirmation: true,
  current_topic_id: null,
  current_outline_version: null,
  current_draft_version: null,
  current_title_version: null,
  error: null,
  created_at: "2026-10-30T08:00:00.000Z",
  updated_at: "2026-10-30T08:00:00.000Z",
};

const detail: StageDetail<"topic_selection"> = {
  stage: "topic_selection",
  label: "选题",
  stage_run: null,
  content: { selected: null, topics },
};

describe("TopicPanel", () => {
  it("lists AI candidates and selects a topic through the API", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/stages/topic_selection") {
        return jsonResponse(detail);
      }
      if (url === "/api/articles/article-1/topics/topic-1/select") {
        expect(requestMethod(init)).toBe("POST");
        return jsonResponse({
          topic: { ...topics[0], selected: true },
          article: { ...article, current_topic_id: "topic-1", status: "draft" },
          source_fetch: {
            ok: true,
            source_id: "source-1",
            title: "AI Agent 工程实践",
            error: null,
            reason: "已抓取正文并保存为来源",
          },
        });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<TopicPanel articleId="article-1" />);

    const candidateButtons = await screen.findAllByRole("button", {
      name: /^选择选题：/,
    });
    expect(candidateButtons).toHaveLength(2);

    expect(await screen.findByText("讨论度 86")).toBeInTheDocument();
    expect(
      screen.getByText("讨论度理由：工程团队与管理者对落地成本存在分歧"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "多智能体登上热榜" })).toHaveAttribute(
      "href",
      "https://example.com/hot",
    );

    await user.click(
      screen.getByRole("button", { name: "选择选题：AI Agent 工程实践" }),
    );

    expect(
      await screen.findByText(
        "已选择「AI Agent 工程实践」。已抓取关联正文并保存为来源。现在可以启动工作流。",
      ),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/topics/topic-1/select") &&
            requestMethod(init ?? {}) === "POST",
        ),
      ).toBe(true);
    });
  });
});
