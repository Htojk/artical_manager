import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Save, Sparkles, Type } from "lucide-react";
import { api } from "../../../lib/api";
import { invalidateArticleData, useStageDetail } from "../../../hooks/useArticleQueries";
import { formatDate, formatNumber, toErrorMessage } from "../../../lib/utils";
import type { TitleCandidate } from "../../../types";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import { Skeleton } from "../../ui/skeleton";
import { EmptyState, ErrorState } from "../../common/States";
import { PanelShell, StageRunSummary } from "./shared";

interface TitlePanelProps {
  articleId: string;
}

function scoreTone(score: number): string {
  if (score >= 85) return "text-emerald-600";
  if (score >= 70) return "text-amber-600";
  return "text-slate-500";
}

export function TitlePanel({ articleId }: TitlePanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "title_optimization");
  const [customTitle, setCustomTitle] = useState("");
  const [loadedVersion, setLoadedVersion] = useState<string | null>(null);

  const latest = stageQuery.data?.content.latest ?? null;
  const history = stageQuery.data?.content.history ?? [];

  useEffect(() => {
    if (!latest || loadedVersion === latest.id) return;
    setLoadedVersion(latest.id);
    setCustomTitle(latest.selected_title);
  }, [latest, loadedVersion]);

  const selectMutation = useMutation({
    mutationFn: (title: string) => api.selectTitle(articleId, title),
    onSuccess: () => {
      invalidateArticleData(queryClient, articleId);
    },
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="标题优化" description="候选标题、评分与最终选定">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-56 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return (
      <ErrorState
        message={toErrorMessage(stageQuery.error)}
        onRetry={() => void stageQuery.refetch()}
      />
    );
  }

  const candidates = latest?.candidates ?? [];

  return (
    <PanelShell
      title="标题优化"
      description="写作完成后自动生成多风格标题候选；选用后会成为审核、排版与发布使用的正式标题。"
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {selectMutation.isSuccess ? (
        <Alert variant="success">标题已更新，审核与排版将使用新标题。</Alert>
      ) : null}
      {selectMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(selectMutation.error)}</Alert>
      ) : null}

      {!latest ? (
        <EmptyState
          title="尚无标题候选"
          description="工作流完成写作后会进入标题优化阶段，自动生成候选标题。"
        />
      ) : (
        <>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Type className="h-4 w-4 text-indigo-500" aria-hidden="true" />
                当前标题
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-lg font-semibold leading-7 text-slate-900">
                {latest.selected_title}
              </p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <Badge variant="outline">第 {latest.version} 版</Badge>
                <span>来源：{latest.created_by === "user" ? "人工选择" : "模型优化"}</span>
                <span>·</span>
                <span>{formatDate(latest.created_at)}</span>
                {latest.model ? <span>· 模型 {latest.model}</span> : null}
                <span>
                  · Token {formatNumber(latest.prompt_tokens)} /{" "}
                  {formatNumber(latest.completion_tokens)}
                </span>
              </div>
              {latest.strategy ? (
                <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                  命名策略：{latest.strategy}
                </p>
              ) : null}
            </CardContent>
          </Card>

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-slate-800">
              候选标题（{candidates.length}）
            </h3>
            <div className="grid gap-3 lg:grid-cols-2">
              {candidates.map((candidate: TitleCandidate) => {
                const selected = candidate.title === latest.selected_title;
                return (
                  <Card
                    key={candidate.title}
                    className={selected ? "border-indigo-300 bg-indigo-50/40" : undefined}
                  >
                    <CardContent className="space-y-2 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <p className="font-medium leading-6 text-slate-900">{candidate.title}</p>
                        <span
                          className={`shrink-0 text-sm font-semibold tabular-nums ${scoreTone(
                            candidate.score,
                          )}`}
                        >
                          {candidate.score.toFixed(0)}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                        {candidate.style ? <Badge variant="outline">{candidate.style}</Badge> : null}
                        {selected ? (
                          <Badge variant="success">
                            <Check className="h-3 w-3" aria-hidden="true" />
                            当前使用
                          </Badge>
                        ) : null}
                      </div>
                      {candidate.rationale ? (
                        <p className="text-xs leading-5 text-slate-500">{candidate.rationale}</p>
                      ) : null}
                      <Button
                        size="sm"
                        variant={selected ? "outline" : "default"}
                        disabled={selected}
                        loading={selectMutation.isPending && selectMutation.variables === candidate.title}
                        aria-label={`选择标题：${candidate.title}`}
                        onClick={() => selectMutation.mutate(candidate.title)}
                      >
                        {selected ? "已选用" : "选用此标题"}
                      </Button>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Sparkles className="h-4 w-4 text-indigo-500" aria-hidden="true" />
                自定义标题
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="custom-title">标题</Label>
                <Input
                  id="custom-title"
                  value={customTitle}
                  maxLength={120}
                  onChange={(event) => setCustomTitle(event.target.value)}
                  placeholder="输入你想使用的标题"
                />
              </div>
              <Button
                onClick={() => selectMutation.mutate(customTitle.trim())}
                disabled={!customTitle.trim()}
                loading={selectMutation.isPending && selectMutation.variables === customTitle.trim()}
              >
                <Save className="h-4 w-4" aria-hidden="true" />
                保存为正式标题
              </Button>
            </CardContent>
          </Card>

          {history.length > 1 ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">历史版本</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {history.map((version) => (
                  <div
                    key={version.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2 text-xs"
                  >
                    <span className="font-medium text-slate-700">
                      第 {version.version} 版 · {version.selected_title}
                    </span>
                    <span className="text-slate-400">
                      {version.created_by === "user" ? "人工选择" : "模型优化"} ·{" "}
                      {formatDate(version.created_at)}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </PanelShell>
  );
}
