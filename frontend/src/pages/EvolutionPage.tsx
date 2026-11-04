import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  CheckCircle2,
  CircleSlash,
  FlaskConical,
  RefreshCw,
  RotateCcw,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { api } from "../lib/api";
import { queryKeys } from "../hooks/useArticleQueries";
import { stageLabel } from "../lib/labels";
import { formatDate, toErrorMessage } from "../lib/utils";
import type { EvolutionSuggestion, JsonValue, SuggestionStatus } from "../types";
import { PageHeader } from "../components/common/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States";
import { StatusBadge } from "../components/common/StatusBadge";
import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";

type ActionKind = "approve" | "reject" | "apply" | "rollback";
type FilterStatus = "all" | SuggestionStatus;

const FILTERS: { value: FilterStatus; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待审批" },
  { value: "approved", label: "已批准" },
  { value: "rejected", label: "已拒绝" },
  { value: "applied", label: "已应用" },
  { value: "rolled_back", label: "已回滚" },
];

const TYPE_LABELS: Record<string, string> = {
  writing_rule: "写作规则",
  skill_update: "技能更新",
  prompt_update: "提示词更新",
  model_routing: "模型路由",
};

const ACTION_COPY: Record<
  ActionKind,
  { title: string; description: string; confirm: string; variant: "default" | "destructive" }
> = {
  approve: {
    title: "批准改进建议",
    description: "批准后建议不会立即生效，还需要再执行「应用」。你可以在备注中记录判断依据。",
    confirm: "批准建议",
    variant: "default",
  },
  reject: {
    title: "拒绝改进建议",
    description: "拒绝后该建议不会生效，且不能直接重新批准。建议填写拒绝原因供后续复盘。",
    confirm: "拒绝建议",
    variant: "destructive",
  },
  apply: {
    title: "应用改进建议",
    description:
      "应用会实际修改技能、提示词或阶段模型绑定。系统会保留应用前快照，可在之后回滚。",
    confirm: "确认应用",
    variant: "default",
  },
  rollback: {
    title: "回滚改进建议",
    description: "回滚会用应用前快照恢复配置。请确认当前没有依赖该改进的进行中工作流。",
    confirm: "确认回滚",
    variant: "destructive",
  },
};

function evidenceText(item: JsonValue): string {
  if (typeof item === "string") return item;
  if (typeof item === "number" || typeof item === "boolean") return String(item);
  if (item && typeof item === "object" && !Array.isArray(item)) {
    const note = item["note"];
    if (typeof note === "string" && note.trim()) return note;
    const message = item["message"];
    if (typeof message === "string" && message.trim()) return message;
  }
  return JSON.stringify(item);
}

function JsonBlock({ label, value }: { label: string; value: JsonValue }) {
  const empty =
    value === null ||
    value === undefined ||
    (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0);
  if (empty) return null;
  return (
    <details className="rounded-lg border border-slate-200 bg-white">
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-slate-600">
        {label}
      </summary>
      <pre className="max-h-64 overflow-auto border-t border-slate-100 bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function SuggestionCard({
  suggestion,
  onAction,
}: {
  suggestion: EvolutionSuggestion;
  onAction: (suggestion: EvolutionSuggestion, action: ActionKind) => void;
}) {
  const canApprove = suggestion.status === "pending";
  const canReject = suggestion.status === "pending" || suggestion.status === "approved";
  const canApply = suggestion.status === "approved";
  const canRollback = suggestion.status === "applied";
  const evidence = suggestion.evidence ?? [];

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge kind="suggestion" status={suggestion.status} />
              <Badge variant="outline">{TYPE_LABELS[suggestion.type] ?? suggestion.type}</Badge>
              <Badge variant="info">{stageLabel(suggestion.target_stage)}</Badge>
            </div>
            <h2 className="mt-2 text-base font-semibold text-slate-900">{suggestion.title}</h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">{suggestion.rationale}</p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {canApprove ? (
              <Button size="sm" onClick={() => onAction(suggestion, "approve")}>
                <ThumbsUp className="h-3.5 w-3.5" aria-hidden="true" />
                批准
              </Button>
            ) : null}
            {canApply ? (
              <Button size="sm" onClick={() => onAction(suggestion, "apply")}>
                <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                应用
              </Button>
            ) : null}
            {canRollback ? (
              <Button size="sm" variant="outline" onClick={() => onAction(suggestion, "rollback")}>
                <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                回滚
              </Button>
            ) : null}
            {canReject ? (
              <Button
                size="sm"
                variant="ghost"
                className="text-red-600 hover:bg-red-50 hover:text-red-700"
                onClick={() => onAction(suggestion, "reject")}
              >
                <ThumbsDown className="h-3.5 w-3.5" aria-hidden="true" />
                拒绝
              </Button>
            ) : null}
          </div>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">
              预期影响
            </p>
            <p className="mt-1 text-xs leading-5 text-slate-600">
              {suggestion.expected_impact || "未提供"}
            </p>
          </div>
          <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              证据
            </p>
            {evidence.length === 0 ? (
              <p className="mt-1 text-xs text-slate-400">无证据条目</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {evidence.map((item, index) => (
                  <li key={index} className="flex gap-1.5 text-xs leading-5 text-slate-600">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                    <span>{evidenceText(item)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="grid gap-2 lg:grid-cols-2">
          <JsonBlock label="补丁内容" value={suggestion.patch} />
          <JsonBlock label="应用前快照" value={suggestion.before_snapshot} />
          <JsonBlock label="应用后快照" value={suggestion.after_snapshot} />
          <JsonBlock label="效果评估" value={suggestion.result} />
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 pt-3 text-[11px] text-slate-400">
          <span>创建于 {formatDate(suggestion.created_at)}</span>
          {suggestion.decided_at ? <span>决策于 {formatDate(suggestion.decided_at)}</span> : null}
          {suggestion.applied_at ? <span>应用于 {formatDate(suggestion.applied_at)}</span> : null}
          {suggestion.decided_note ? (
            <span className="text-slate-500">备注：{suggestion.decided_note}</span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function EvolutionPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [action, setAction] = useState<{ suggestion: EvolutionSuggestion; kind: ActionKind } | null>(
    null,
  );
  const [note, setNote] = useState("");
  const [generatedCount, setGeneratedCount] = useState<number | null>(null);

  const suggestionsQuery = useQuery({
    queryKey: queryKeys.suggestions(filter === "all" ? undefined : filter),
    queryFn: () => api.listSuggestions(filter === "all" ? undefined : filter),
  });

  const generateMutation = useMutation({
    mutationFn: () => api.generateSuggestions(),
    onSuccess: (result) => {
      setGeneratedCount(result.items.length);
      void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });

  const actionMutation = useMutation({
    mutationFn: async ({
      suggestion,
      kind,
      decisionNote,
    }: {
      suggestion: EvolutionSuggestion;
      kind: ActionKind;
      decisionNote: string;
    }) => {
      switch (kind) {
        case "approve":
          return api.approveSuggestion(suggestion.id, decisionNote);
        case "reject":
          return api.rejectSuggestion(suggestion.id, decisionNote);
        case "apply":
          return api.applySuggestion(suggestion.id);
        case "rollback":
          return api.rollbackSuggestion(suggestion.id);
      }
    },
    onSuccess: () => {
      setAction(null);
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillBindings() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.models() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelBindings() });
    },
  });

  const openAction = (suggestion: EvolutionSuggestion, kind: ActionKind) => {
    actionMutation.reset();
    setNote("");
    setAction({ suggestion, kind });
  };

  const items = suggestionsQuery.data?.items ?? [];
  const copy = action ? ACTION_COPY[action.kind] : null;
  const requiresNote = action?.kind === "reject";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Self Evolution"
        title="自进化"
        description="系统根据近期审核、返工与成本信号提出可回滚的改进建议。所有变更都需要人工审批后才可应用。"
        actions={
          <Button
            onClick={() => {
              setGeneratedCount(null);
              generateMutation.mutate();
            }}
            loading={generateMutation.isPending}
          >
            <Bot className="h-4 w-4" aria-hidden="true" />
            生成建议
          </Button>
        }
      />

      <Alert variant="warning" title="变更需人工把关">
        应用建议会修改技能内容、提示词或模型绑定。建议先核对补丁与证据，应用后通过「效果评估」决定是否回滚。
      </Alert>

      {generateMutation.error ? (
        <Alert variant="destructive" title="生成建议失败">
          {toErrorMessage(generateMutation.error)}
        </Alert>
      ) : null}
      {generateMutation.isSuccess ? (
        <Alert variant="success">
          {generatedCount === 0
            ? "分析完成，但近期样本不足或模型没有产生可用建议。"
            : `已生成 ${generatedCount} 条新建议，请审批。`}
        </Alert>
      ) : null}
      {actionMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(actionMutation.error)}</Alert>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((item) => (
          <Button
            key={item.value}
            size="sm"
            variant={filter === item.value ? "default" : "outline"}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </Button>
        ))}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void suggestionsQuery.refetch()}
          className="ml-auto"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          刷新
        </Button>
      </div>

      {suggestionsQuery.isLoading ? <LoadingState label="加载改进建议…" /> : null}
      {suggestionsQuery.isError ? (
        <ErrorState
          message={toErrorMessage(suggestionsQuery.error)}
          onRetry={() => void suggestionsQuery.refetch()}
        />
      ) : null}
      {!suggestionsQuery.isLoading && !suggestionsQuery.isError && items.length === 0 ? (
        <EmptyState
          title={filter === "all" ? "暂无改进建议" : "该状态下没有建议"}
          description="积累一定数量的文章运行信号后，点击「生成建议」进行分析。"
          icon={<FlaskConical className="h-6 w-6" aria-hidden="true" />}
        />
      ) : null}

      <div className="space-y-4">
        {items.map((suggestion) => (
          <SuggestionCard key={suggestion.id} suggestion={suggestion} onAction={openAction} />
        ))}
      </div>

      <Dialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open) {
            setAction(null);
            setNote("");
            actionMutation.reset();
          }
        }}
        labelledBy="evolution-action-title"
      >
        <DialogHeader>
          <DialogTitle id="evolution-action-title">{copy?.title ?? "改进建议"}</DialogTitle>
          <DialogDescription>{copy?.description ?? ""}</DialogDescription>
        </DialogHeader>
        <DialogContent className="space-y-3">
          {action ? (
            <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
              <p className="text-sm font-semibold text-slate-800">{action.suggestion.title}</p>
              <p className="mt-1 text-xs text-slate-500">
                {TYPE_LABELS[action.suggestion.type] ?? action.suggestion.type} ·{" "}
                {stageLabel(action.suggestion.target_stage)}
              </p>
            </div>
          ) : null}
          {action?.kind === "approve" || action?.kind === "reject" ? (
            <div className="space-y-1.5">
              <Label htmlFor="evolution-note">
                审批备注{requiresNote ? "（建议填写）" : "（可选）"}
              </Label>
              <Textarea
                id="evolution-note"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder={
                  action.kind === "reject"
                    ? "说明拒绝原因，例如证据不足或风险较高…"
                    : "记录批准依据或后续观察重点…"
                }
              />
            </div>
          ) : null}
          {action?.kind === "apply" ? (
            <div className="space-y-3 text-xs text-slate-600">
              <p className="inline-flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-amber-800">
                <CircleSlash className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                应用会立即改变运行时配置，并记录快照。建议应用后观察至少 10 篇文章的审核均分与返工率。
              </p>
              {action ? <JsonBlock label="即将应用" value={action.suggestion.patch} /> : null}
            </div>
          ) : null}
          {action?.kind === "rollback" ? (
            <Alert variant="warning">
              回滚后将恢复到应用前快照，当前状态会标记为「已回滚」。
            </Alert>
          ) : null}
          {actionMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(actionMutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setAction(null)}>
            <XCircle className="h-4 w-4" aria-hidden="true" />
            取消
          </Button>
          <Button
            variant={copy?.variant ?? "default"}
            loading={actionMutation.isPending}
            disabled={requiresNote && !note.trim()}
            onClick={() => {
              if (action) {
                actionMutation.mutate({
                  suggestion: action.suggestion,
                  kind: action.kind,
                  decisionNote: note,
                });
              }
            }}
          >
            {action?.kind === "apply" ? (
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            ) : action?.kind === "rollback" ? (
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            ) : null}
            {copy?.confirm ?? "确认"}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
