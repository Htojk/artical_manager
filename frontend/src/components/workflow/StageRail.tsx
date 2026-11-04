import type { ArticleStatus, RunStatus, StageKey, StageStatus, StageSummary } from "../../types";
import { STAGE_KEYS, STAGE_LABELS, STAGE_STATUS_LABELS } from "../../lib/labels";
import { cn, formatDuration } from "../../lib/utils";
import { Check, Circle, Loader2, PauseCircle, X } from "lucide-react";

type DisplayStatus = StageStatus | "warning";

interface StageRailProps {
  stages: StageSummary[];
  activeStage: StageKey;
  onSelect: (stage: StageKey) => void;
  articleStatus?: ArticleStatus;
  runStatus?: RunStatus | null;
  currentStage?: string | null;
  variant?: "vertical" | "horizontal";
  className?: string;
  showLegend?: boolean;
}

const WARNING_ARTICLE_STATUSES: ArticleStatus[] = [
  "paused",
  "waiting_review",
  "waiting_publish",
  "waiting_topic",
  "needs_human",
];

const WARNING_RUN_STATUSES: RunStatus[] = [
  "paused",
  "waiting_review",
  "waiting_publish",
  "needs_human",
];

export function getDisplayStatus(
  stage: StageSummary,
  options: {
    articleStatus?: ArticleStatus;
    runStatus?: RunStatus | null;
    currentStage?: string | null;
  },
): DisplayStatus {
  if (stage.status === "running") return "running";
  if (stage.status === "failed") return "failed";
  if (stage.status === "completed") return "completed";
  if (stage.status === "skipped") return "warning";

  const isCurrent =
    options.currentStage === stage.stage ||
    (!!stage.started_at && !stage.finished_at) ||
    stage.stage === (options.currentStage as StageKey | undefined);
  const articleWarning =
    isCurrent &&
    !!options.articleStatus &&
    WARNING_ARTICLE_STATUSES.includes(options.articleStatus);
  const runWarning =
    isCurrent && !!options.runStatus && WARNING_RUN_STATUSES.includes(options.runStatus);
  return articleWarning || runWarning ? "warning" : "pending";
}

const STATUS_STYLES: Record<
  DisplayStatus,
  { node: string; text: string; icon: typeof Circle; line: string }
> = {
  pending: {
    node: "border-slate-300 bg-white text-slate-400",
    text: "text-slate-400",
    icon: Circle,
    line: "bg-slate-200",
  },
  running: {
    node: "border-blue-400 bg-blue-50 text-blue-600 ring-4 ring-blue-100",
    text: "text-blue-600",
    icon: Loader2,
    line: "bg-blue-200",
  },
  completed: {
    node: "border-emerald-400 bg-emerald-50 text-emerald-600",
    text: "text-emerald-600",
    icon: Check,
    line: "bg-emerald-200",
  },
  failed: {
    node: "border-red-400 bg-red-50 text-red-600",
    text: "text-red-600",
    icon: X,
    line: "bg-red-200",
  },
  warning: {
    node: "border-amber-400 bg-amber-50 text-amber-600 ring-4 ring-amber-100",
    text: "text-amber-600",
    icon: PauseCircle,
    line: "bg-amber-200",
  },
  skipped: {
    node: "border-amber-300 bg-amber-50 text-amber-600",
    text: "text-amber-600",
    icon: PauseCircle,
    line: "bg-amber-200",
  },
};

const STATUS_LABELS: Record<DisplayStatus, string> = {
  pending: STAGE_STATUS_LABELS.pending,
  running: STAGE_STATUS_LABELS.running,
  completed: STAGE_STATUS_LABELS.completed,
  failed: STAGE_STATUS_LABELS.failed,
  skipped: STAGE_STATUS_LABELS.skipped,
  warning: STAGE_STATUS_LABELS.warning,
};

function mergedStages(stages: StageSummary[]): StageSummary[] {
  const byStage = new Map(stages.map((stage) => [stage.stage, stage]));
  return STAGE_KEYS.map(
    (key) =>
      byStage.get(key) ?? {
        stage: key,
        label: STAGE_LABELS[key],
        status: "pending",
        attempt: 0,
        started_at: null,
        finished_at: null,
        error: null,
        artifact: {},
      },
  );
}

export function StageRail({
  stages,
  activeStage,
  onSelect,
  articleStatus,
  runStatus,
  currentStage,
  variant = "vertical",
  className,
  showLegend = true,
}: StageRailProps) {
  const items = mergedStages(stages);
  const horizontal = variant === "horizontal";

  if (horizontal) {
    return (
      <ol
        className={cn("flex min-w-max items-center gap-1.5", className)}
        aria-label="文章生成流程"
      >
        {items.map((stage, index) => {
          const status = getDisplayStatus(stage, { articleStatus, runStatus, currentStage });
          const styles = STATUS_STYLES[status];
          const Icon = styles.icon;
          const active = stage.stage === activeStage;
          return (
            <li key={stage.stage} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onSelect(stage.stage)}
                aria-current={active ? "step" : undefined}
                aria-label={`${stage.label}，${STATUS_LABELS[status]}`}
                data-testid={`stage-node-${stage.stage}`}
                data-status={status}
                className={cn(
                  "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition-colors",
                  active
                    ? "border-indigo-300 bg-indigo-50 text-indigo-700 shadow-sm"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                )}
              >
                <span
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full border text-[10px]",
                    styles.node,
                  )}
                >
                  <Icon
                    className={cn("h-3 w-3", status === "running" && "animate-spin")}
                    aria-hidden="true"
                  />
                </span>
                <span className="font-medium">{stage.label}</span>
              </button>
              {index < items.length - 1 ? (
                <span className="h-px w-3 bg-slate-300" aria-hidden="true" />
              ) : null}
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
            生成流程
          </p>
          <p className="mt-0.5 text-xs text-slate-500">点击节点查看阶段内容</p>
        </div>
        {runStatus ? (
          <span className="text-[11px] font-medium text-slate-400">{items.length} 个节点</span>
        ) : null}
      </div>

      <ol className="space-y-1" aria-label="文章生成流程">
        {items.map((stage, index) => {
          const status = getDisplayStatus(stage, { articleStatus, runStatus, currentStage });
          const styles = STATUS_STYLES[status];
          const Icon = styles.icon;
          const active = stage.stage === activeStage;
          const isLast = index === items.length - 1;
          return (
            <li key={stage.stage} className="relative">
              {!isLast ? (
                <span
                  className={cn("absolute left-[17px] top-9 h-[calc(100%-1.5rem)] w-px", styles.line)}
                  aria-hidden="true"
                />
              ) : null}
              <button
                type="button"
                onClick={() => onSelect(stage.stage)}
                aria-current={active ? "step" : undefined}
                data-testid={`stage-node-${stage.stage}`}
                data-status={status}
                className={cn(
                  "relative z-10 flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors",
                  active
                    ? "border-indigo-200 bg-indigo-50/80 shadow-sm"
                    : "border-transparent hover:border-slate-200 hover:bg-slate-50",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2",
                    styles.node,
                  )}
                >
                  <Icon
                    className={cn("h-4 w-4", status === "running" && "animate-spin")}
                    aria-hidden="true"
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        "truncate text-sm font-semibold",
                        active ? "text-indigo-900" : "text-slate-800",
                      )}
                    >
                      {stage.label}
                    </span>
                    <span className={cn("shrink-0 text-[11px] font-medium", styles.text)}>
                      {STATUS_LABELS[status]}
                    </span>
                  </span>
                  <span className="mt-0.5 flex items-center justify-between gap-2 text-[11px] text-slate-400">
                    <span>
                      {stage.attempt > 0 ? `第 ${stage.attempt} 次` : STAGE_LABELS[stage.stage]}
                    </span>
                    {stage.started_at ? (
                      <span>{formatDuration(stage.started_at, stage.finished_at)}</span>
                    ) : null}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {showLegend ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1.5 border-t border-slate-100 pt-3" aria-label="状态图例">
          {(
            [
              ["pending", "未开始"],
              ["running", "进行中"],
              ["completed", "已完成"],
              ["failed", "失败"],
              ["warning", "待确认"],
            ] as const
          ).map(([status, label]) => (
            <span key={status} className="inline-flex items-center gap-1 text-[11px] text-slate-400">
              <span
                className={cn("h-2 w-2 rounded-full", {
                  "bg-slate-300": status === "pending",
                  "bg-blue-500": status === "running",
                  "bg-emerald-500": status === "completed",
                  "bg-red-500": status === "failed",
                  "bg-amber-500": status === "warning",
                })}
                aria-hidden="true"
              />
              {label}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export { STATUS_STYLES as STAGE_STATUS_STYLES };
