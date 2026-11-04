import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ArticleDetailPage } from "./ArticleDetailPage";
import { installFetchMock, jsonResponse, renderWithProviders } from "../test/utils";
import type {
  Article,
  StageDetail,
  StageSummary,
  StageTimeline,
  WorkflowRun,
} from "../types";

const article: Article = {
  id: "article-1",
  title: "AI Agent 工作流设计",
  status: "running",
  current_stage: "writing",
  topic_mode: "ai",
  target_platforms: ["wechat", "zhihu"],
  publish_confirmation: true,
  current_topic_id: "topic-1",
  current_outline_version: 1,
  current_draft_version: 1,
  current_title_version: 1,
  error: null,
  created_at: "2026-10-30T08:00:00.000Z",
  updated_at: "2026-10-30T08:30:00.000Z",
};

const run: WorkflowRun = {
  id: "run-1",
  article_id: article.id,
  thread_id: "thread-1",
  status: "running",
  current_stage: "writing",
  revision_count: 0,
  max_revisions: 2,
  pause_requested: false,
  error: null,
  created_at: "2026-10-30T08:00:00.000Z",
  updated_at: "2026-10-30T08:30:00.000Z",
};

function stageSummary(
  stage: StageSummary["stage"],
  label: string,
  status: StageSummary["status"],
  startedAt: string | null,
  finishedAt: string | null,
): StageSummary {
  return {
    stage,
    label,
    status,
    attempt: status === "pending" ? 0 : 1,
    started_at: startedAt,
    finished_at: finishedAt,
    error: null,
    artifact: {},
  };
}

const timeline: StageTimeline = {
  article: {
    id: article.id,
    status: article.status,
    current_stage: article.current_stage,
  },
  run,
  stages: [
    stageSummary("topic_selection", "选题", "completed", "2026-10-30T08:00:00.000Z", "2026-10-30T08:01:00.000Z"),
    stageSummary("research", "资料搜索", "completed", "2026-10-30T08:01:00.000Z", "2026-10-30T08:03:00.000Z"),
    stageSummary("outline", "大纲生成", "completed", "2026-10-30T08:03:00.000Z", "2026-10-30T08:05:00.000Z"),
    stageSummary("writing", "写作", "running", "2026-10-30T08:05:00.000Z", null),
    stageSummary("review", "审核", "pending", null, null),
    stageSummary("formatting", "分平台排版", "pending", null, null),
    stageSummary("publishing", "发布", "pending", null, null),
  ],
};

const writingDetail: StageDetail<"writing"> = {
  stage: "writing",
  label: "写作",
  stage_run: null,
  content: { latest: null, history: [] },
};

describe("ArticleDetailPage", () => {
  it("keeps a sticky desktop rail and exposes a horizontal rail plus drawer on small screens", async () => {
    const user = userEvent.setup();
    class EventSourceMock {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      constructor(public url: string) {}
      addEventListener = vi.fn();
      close = vi.fn();
    }
    vi.stubGlobal("EventSource", EventSourceMock);

    installFetchMock((url) => {
      if (url === "/api/articles/article-1") {
        return jsonResponse({ article, topics: [] });
      }
      if (url === "/api/articles/article-1/stages") {
        return jsonResponse(timeline);
      }
      if (url === "/api/articles/article-1/stages/writing") {
        return jsonResponse(writingDetail);
      }
      if (url === "/api/articles/article-1/stages/outline") {
        return jsonResponse({
          stage: "outline",
          label: "大纲生成",
          stage_run: null,
          content: { latest: null, history: [] },
        } satisfies StageDetail<"outline">);
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(
      <Routes>
        <Route path="/articles/:id" element={<ArticleDetailPage />} />
      </Routes>,
      { route: "/articles/article-1?stage=writing" },
    );

    const rail = await screen.findByTestId("sticky-stage-rail");
    expect(rail).toHaveClass("lg:sticky", "lg:top-20", "lg:block");
    const scrollContainer = screen.getByTestId("article-scroll-container");
    expect(within(scrollContainer).getByTestId("sticky-stage-rail")).toBe(rail);

    expect(await screen.findByText("尚无正文")).toBeInTheDocument();
    expect(screen.getAllByTestId(/^stage-node-/)).toHaveLength(16);
    expect(screen.getAllByRole("list", { name: "文章生成流程" })).toHaveLength(2);
    expect(screen.getAllByLabelText("文章生成流程")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "流程" }));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: "生成流程" }),
    ).toBeInTheDocument();
    expect(within(dialog).getAllByTestId(/^stage-node-/)).toHaveLength(8);
    expect(within(dialog).getByTestId("stage-node-writing")).toHaveAttribute(
      "data-status",
      "running",
    );

    await user.click(within(dialog).getByTestId("stage-node-outline"));

    expect(await screen.findByText("尚无大纲")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(
      screen
        .getAllByTestId("stage-node-outline")
        .some((node) => node.getAttribute("aria-current") === "step"),
    ).toBe(true);
  });

  it("shows the review decision gate instead of a generic resume button", async () => {
    class EventSourceMock {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      constructor(public url: string) {}
      addEventListener = vi.fn();
      close = vi.fn();
    }
    vi.stubGlobal("EventSource", EventSourceMock);

    installFetchMock((url) => {
      if (url === "/api/articles/article-1") {
        return jsonResponse({
          article: { ...article, status: "waiting_review", current_stage: "review" },
          topics: [],
        });
      }
      if (url === "/api/articles/article-1/stages") {
        return jsonResponse({
          ...timeline,
          article: { ...timeline.article, status: "waiting_review", current_stage: "review" },
          run: { ...run, status: "waiting_review", current_stage: "review" },
        } satisfies StageTimeline);
      }
      if (url === "/api/articles/article-1/stages/review") {
        return jsonResponse({
          stage: "review",
          label: "审核",
          stage_run: null,
          content: { latest: null, history: [], latest_decision: null },
        } satisfies StageDetail<"review">);
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(
      <Routes>
        <Route path="/articles/:id" element={<ArticleDetailPage />} />
      </Routes>,
      { route: "/articles/article-1?stage=review" },
    );

    expect(await screen.findByText("人工审稿确认")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "继续运行" })).not.toBeInTheDocument();
  });
});
