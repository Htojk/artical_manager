import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { getDisplayStatus, StageRail } from "./StageRail";
import type { StageSummary } from "../../types";

const stages: StageSummary[] = [
  {
    stage: "topic_selection",
    label: "选题",
    status: "completed",
    attempt: 1,
    started_at: "2026-10-30T08:00:00.000Z",
    finished_at: "2026-10-30T08:01:00.000Z",
    error: null,
    artifact: {},
  },
  {
    stage: "research",
    label: "资料搜索",
    status: "running",
    attempt: 1,
    started_at: "2026-10-30T08:01:00.000Z",
    finished_at: null,
    error: null,
    artifact: {},
  },
  {
    stage: "outline",
    label: "大纲生成",
    status: "failed",
    attempt: 2,
    started_at: "2026-10-30T08:02:00.000Z",
    finished_at: "2026-10-30T08:03:00.000Z",
    error: "模型超时",
    artifact: {},
  },
  {
    stage: "writing",
    label: "写作",
    status: "pending",
    attempt: 0,
    started_at: null,
    finished_at: null,
    error: null,
    artifact: {},
  },
  {
    stage: "title_optimization",
    label: "标题优化",
    status: "pending",
    attempt: 0,
    started_at: null,
    finished_at: null,
    error: null,
    artifact: {},
  },
  {
    stage: "review",
    label: "审核",
    status: "skipped",
    attempt: 0,
    started_at: null,
    finished_at: null,
    error: null,
    artifact: {},
  },
  {
    stage: "formatting",
    label: "分平台排版",
    status: "pending",
    attempt: 0,
    started_at: null,
    finished_at: null,
    error: null,
    artifact: {},
  },
  {
    stage: "publishing",
    label: "发布",
    status: "pending",
    attempt: 0,
    started_at: null,
    finished_at: null,
    error: null,
    artifact: {},
  },
];

describe("StageRail", () => {
  it("always renders the workflow nodes with their statuses", () => {
    render(
      <StageRail
        stages={stages}
        activeStage="writing"
        onSelect={() => undefined}
        articleStatus="paused"
        runStatus="paused"
        currentStage="writing"
      />,
    );

    expect(screen.getAllByTestId(/^stage-node-/)).toHaveLength(8);
    expect(screen.getByTestId("stage-node-topic_selection")).toHaveAttribute(
      "data-status",
      "completed",
    );
    expect(screen.getByTestId("stage-node-research")).toHaveAttribute(
      "data-status",
      "running",
    );
    expect(screen.getByTestId("stage-node-outline")).toHaveAttribute(
      "data-status",
      "failed",
    );
    expect(screen.getByTestId("stage-node-writing")).toHaveAttribute(
      "data-status",
      "warning",
    );
    expect(screen.getByTestId("stage-node-title_optimization")).toHaveAttribute(
      "data-status",
      "pending",
    );
    expect(screen.getByTestId("stage-node-review")).toHaveAttribute(
      "data-status",
      "warning",
    );
    expect(screen.getByTestId("stage-node-formatting")).toHaveAttribute(
      "data-status",
      "pending",
    );
    expect(screen.getByTestId("stage-node-publishing")).toHaveAttribute(
      "data-status",
      "pending",
    );
    expect(screen.getByTestId("stage-node-writing")).toHaveAttribute(
      "aria-current",
      "step",
    );
  });

  it("maps paused and needs-human current stages to the warning state", () => {
    const pending = stages[3];
    expect(
      getDisplayStatus(pending, {
        articleStatus: "paused",
        runStatus: "paused",
        currentStage: "writing",
      }),
    ).toBe("warning");
    expect(
      getDisplayStatus(pending, {
        articleStatus: "needs_human",
        runStatus: "needs_human",
        currentStage: "writing",
      }),
    ).toBe("warning");
    expect(
      getDisplayStatus(pending, {
        articleStatus: "running",
        runStatus: "running",
        currentStage: "writing",
      }),
    ).toBe("pending");
  });

  it("notifies the selected stage when a node is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <StageRail
        stages={stages}
        activeStage="topic_selection"
        onSelect={onSelect}
        articleStatus="running"
        runStatus="running"
        currentStage="research"
      />,
    );

    await user.click(screen.getByTestId("stage-node-formatting"));
    expect(onSelect).toHaveBeenCalledWith("formatting");
  });

  it("renders the horizontal compact variant without the legend", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <StageRail
        variant="horizontal"
        stages={stages}
        activeStage="research"
        onSelect={onSelect}
        articleStatus="running"
        runStatus="running"
        currentStage="research"
        showLegend={false}
      />,
    );

    expect(screen.getAllByTestId(/^stage-node-/)).toHaveLength(8);
    expect(screen.queryByLabelText("状态图例")).not.toBeInTheDocument();
    expect(screen.getByTestId("stage-node-research")).toHaveAttribute(
      "aria-current",
      "step",
    );

    await user.click(screen.getByTestId("stage-node-review"));
    expect(onSelect).toHaveBeenCalledWith("review");
  });
});
