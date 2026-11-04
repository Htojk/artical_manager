import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArticleListPage } from "./ArticleListPage";
import { installFetchMock, jsonResponse, renderWithProviders } from "../test/utils";
import type { Article, PerformanceRow } from "../types";

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
  current_draft_version: 2,
  current_title_version: 2,
  error: null,
  created_at: "2026-10-29T08:00:00.000Z",
  updated_at: "2026-10-30T08:30:00.000Z",
};

const performance: PerformanceRow = {
  article_id: "article-1",
  title: article.title,
  status: "running",
  views: 1200,
  revenue_yuan: 45.5,
  cost: 1.25,
  roi: 36.4,
};

describe("ArticleListPage", () => {
  it("renders articles, workflow status, stage, platforms and cost", async () => {
    installFetchMock((url) => {
      if (url.startsWith("/api/articles")) {
        return jsonResponse({ items: [article], total: 1 });
      }
      if (url.startsWith("/api/analytics/performance")) {
        return jsonResponse({ items: [performance], total: 1 });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<ArticleListPage />);

    const titleLink = await screen.findByRole("link", { name: article.title });
    expect(titleLink).toHaveAttribute("href", "/articles/article-1");
    expect(screen.getByText("写作")).toBeInTheDocument();
    expect(screen.getByText("微信公众号")).toBeInTheDocument();
    expect(screen.getByText("知乎")).toBeInTheDocument();
    expect(screen.getAllByText("运行中").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1\.25/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /新建文章/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除文章：AI Agent 工作流设计" })).toBeInTheDocument();
  });
});
