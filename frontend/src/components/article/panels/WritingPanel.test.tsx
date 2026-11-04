import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { WritingPanel } from "./WritingPanel";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../../../test/utils";
import type { DraftVersion, StageDetail } from "../../../types";

function draft(version: number): DraftVersion {
  return {
    id: `draft-${version}`,
    version,
    content_md: "# 开头\n\n结论先行，再展开论证。",
    summary: "结论先行",
    word_count: 18,
    model: "gpt-4o-mini",
    skill_snapshot: [{ name: "技术写作风格" }],
    citation_report: [],
    prompt_tokens: 1200,
    completion_tokens: 3400,
    duration_ms: 1234,
    created_by: version === 1 ? "writer" : "user_edit",
    note: "",
    created_at: "2026-10-30T08:10:00.000Z",
  };
}

function stageDetail(latest: DraftVersion): StageDetail<"writing"> {
  return {
    stage: "writing",
    label: "写作",
    stage_run: null,
    content: { latest, history: [draft(1), ...(latest.version > 1 ? [latest] : [])] },
  };
}

describe("WritingPanel", () => {
  it("shows token and duration metadata, then refreshes to the new version after saving", async () => {
    const user = userEvent.setup();
    let version = 1;
    const saveBodies: unknown[] = [];

    installFetchMock((url, init) => {
      if (url === "/api/articles/article-1/stages/writing" && requestMethod(init) === "PUT") {
        expect(requestBody(init)).toEqual({
          content_md: "# 开头\n\n结论先行，再展开论证。",
          summary: "结论先行",
          title: null,
        });
        saveBodies.push(requestBody(init));
        version = 2;
        return jsonResponse(draft(version));
      }
      if (url === "/api/articles/article-1/stages/writing") {
        return jsonResponse(stageDetail(draft(version)));
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<WritingPanel articleId="article-1" />);

    expect(await screen.findAllByText("v1")).not.toHaveLength(0);
    expect(screen.getByText(/Token：1,200 \/ 3,400/)).toBeInTheDocument();
    expect(screen.getByText("耗时：1.2 秒")).toBeInTheDocument();
    expect(screen.getByText("技术写作风格")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "保存为新版本" }));

    await waitFor(() => {
      expect(saveBodies).toHaveLength(1);
    });
    expect(await screen.findByText("正文已保存为新版本。审核和排版将读取最新内容。")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText("v2").length).toBeGreaterThan(0);
    });
  });
});
