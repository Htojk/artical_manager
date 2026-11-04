import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PublishingPanel } from "./PublishingPanel";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../../../test/utils";
import type {
  ConfirmSummary,
  PublishRecord,
  StageDetail,
  WorkflowRun,
} from "../../../types";

const publishingDetail: StageDetail<"publishing"> = {
  stage: "publishing",
  label: "发布",
  stage_run: null,
  content: { records: [] },
};

const summary: ConfirmSummary = {
  article_id: "article-1",
  title: "AI Agent 工程实践",
  platforms: [
    {
      platform: "wechat",
      display_name: "微信公众号",
      title: "AI Agent 工程实践",
      artifact_ready: true,
      available: true,
      mode: "api",
      reason: "",
    },
    {
      platform: "zhihu",
      display_name: "知乎",
      title: "AI Agent 工程实践",
      artifact_ready: false,
      available: true,
      mode: "manual",
      reason: "需要手动发布",
    },
  ],
};

const run: WorkflowRun = {
  id: "run-1",
  article_id: "article-1",
  thread_id: "thread-1",
  status: "running",
  current_stage: "publishing",
  revision_count: 0,
  max_revisions: 2,
  pause_requested: false,
  error: null,
  created_at: "2026-10-30T08:00:00.000Z",
  updated_at: "2026-10-30T08:10:00.000Z",
};

describe("PublishingPanel", () => {
  it("confirms the summary then approves the waiting publish step", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/stages/publishing") {
        return jsonResponse(publishingDetail);
      }
      if (url === "/api/articles/article-1/confirm-summary") {
        return jsonResponse(summary);
      }
      if (url === "/api/articles/article-1/confirm-publish") {
        expect(requestMethod(init)).toBe("POST");
        expect(requestBody(init)).toEqual({ decision: "approve" });
        return jsonResponse(run);
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(
      <PublishingPanel
        articleId="article-1"
        articleStatus="waiting_publish"
        runStatus="waiting_publish"
        platforms={["wechat", "zhihu"]}
      />,
    );

    expect(await screen.findByText("尚无发布记录")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    expect(await screen.findByText("微信公众号 · api")).toBeInTheDocument();
    expect(screen.getByText("知乎 · manual")).toBeInTheDocument();
    expect(screen.getByText("可发布")).toBeInTheDocument();
    expect(screen.getByText("将转手动/失败")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "批准并发布" }));

    expect(
      await screen.findByText("已确认发布，工作流将继续执行。"),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/confirm-publish") &&
            requestMethod(init ?? {}) === "POST",
        ),
      ).toBe(true);
    });
  });

  it("retries a failed platform publish and refreshes the record status", async () => {
    const user = userEvent.setup();
    let status = "failed";
    let retried = false;
    const failedRecord: PublishRecord = {
      id: "record-1",
      article_id: "article-1",
      platform: "wechat",
      formatted_output_id: "format-1",
      status: "failed",
      remote_id: null,
      url: null,
      published_at: null,
      error: "接口超时",
      attempt: 1,
      created_at: "2026-10-30T08:00:00.000Z",
      updated_at: "2026-10-30T08:05:00.000Z",
      latest_metric: null,
      history: [],
    };

    installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/publish/wechat/retry") {
        expect(requestMethod(init)).toBe("POST");
        retried = true;
        status = "publishing";
        return jsonResponse({ ...failedRecord, status, error: null });
      }
      if (url === "/api/articles/article-1/stages/publishing") {
        return jsonResponse({
          ...publishingDetail,
          content: {
            records: [
              {
                ...failedRecord,
                status,
                error: status === "failed" ? failedRecord.error : null,
              },
            ],
          },
        } satisfies StageDetail<"publishing">);
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(
      <PublishingPanel
        articleId="article-1"
        articleStatus="published"
        runStatus={null}
        platforms={["wechat"]}
      />,
    );

    expect(await screen.findByText("接口超时")).toBeInTheDocument();
    expect(screen.getByText("需要处理")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(await screen.findByText("重试请求已提交。")).toBeInTheDocument();
    await waitFor(() => {
      expect(retried).toBe(true);
      expect(screen.getByText("发布中")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "重试" })).not.toBeInTheDocument();
  });
});
