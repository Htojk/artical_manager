import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, RotateCcw, ShieldCheck } from "lucide-react";
import { invalidateArticleData, useStageDetail } from "../../../hooks/useArticleQueries";
import { api } from "../../../lib/api";
import { REVIEW_DIMENSION_LABELS, REVIEW_DIMENSIONS, stageLabel } from "../../../lib/labels";
import { formatDate, toErrorMessage } from "../../../lib/utils";
import type { ReviewReport } from "../../../types";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Skeleton } from "../../ui/skeleton";
import { Textarea } from "../../ui/textarea";
import { EmptyState, ErrorState } from "../../common/States";
import { PanelShell, StageRunSummary } from "./shared";

interface ReviewPanelProps {
  articleId: string;
  waiting?: boolean;
}

function scoreTone(score: number): string {
  if (score >= 80) return "bg-emerald-500";
  if (score >= 60) return "bg-amber-500";
  return "bg-red-500";
}

function ReportView({ report }: { report: ReviewReport }) {
  const passed = report.verdict === "pass";
  return (
    <div className="space-y-4">
      <div
        className={
          passed
            ? "flex flex-wrap items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4"
            : "flex flex-wrap items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-4"
        }
      >
        {passed ? (
          <CheckCircle2 className="h-6 w-6 text-emerald-600" aria-hidden="true" />
        ) : (
          <AlertTriangle className="h-6 w-6 text-red-600" aria-hidden="true" />
        )}
        <div>
          <p className={passed ? "font-semibold text-emerald-800" : "font-semibold text-red-800"}>
            {passed ? "审核通过" : "审核未通过"}
          </p>
          <p className="text-xs text-slate-500">
            综合得分 {report.total.toFixed(1)} / 100 · 审核模型 {report.model ?? "未记录"} ·{" "}
            {formatDate(report.created_at)}
          </p>
        </div>
        {!passed && report.rollback_to ? (
          <Badge variant="warning" className="ml-auto">
            <RotateCcw className="h-3 w-3" aria-hidden="true" />
            回退至 {stageLabel(report.rollback_to)}
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {REVIEW_DIMENSIONS.map((dimension) => {
          const entry = report.scores[dimension];
          const score = entry?.score ?? 0;
          return (
            <Card key={dimension}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>{REVIEW_DIMENSION_LABELS[dimension] ?? dimension}</span>
                  <span className="font-semibold tabular-nums text-slate-800">{score.toFixed(0)}</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={`h-full rounded-full ${scoreTone(score)}`}
                    style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
                  />
                </div>
                <p className="mt-2 text-[11px] text-slate-400">
                  {entry?.issues.length ?? 0} 个问题 · {entry?.suggestions.length ?? 0} 条建议
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">审核结论</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap text-sm leading-7 text-slate-600">
            {report.rationale || "无详细说明"}
          </p>
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        {REVIEW_DIMENSIONS.map((dimension) => {
          const entry = report.scores[dimension];
          if (!entry || (entry.issues.length === 0 && entry.suggestions.length === 0)) return null;
          return (
            <Card key={dimension}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  {REVIEW_DIMENSION_LABELS[dimension] ?? dimension}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs leading-5">
                {entry.issues.map((issue, index) => (
                  <div key={`${issue.description}-${index}`} className="rounded-lg bg-red-50 px-3 py-2 text-red-700">
                    {issue.location ? <span className="font-semibold">[{issue.location}] </span> : null}
                    {issue.description}
                  </div>
                ))}
                {entry.suggestions.map((suggestion, index) => (
                  <p key={`${suggestion}-${index}`} className="text-slate-500">
                    · {suggestion}
                  </p>
                ))}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

export function ReviewPanel({ articleId, waiting = false }: ReviewPanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "review");
  const [feedback, setFeedback] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const decisionMutation = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api.reviewDecision(articleId, { decision, feedback: feedback.trim() }),
    onSuccess: (_run, decision) => {
      setNotice(decision === "approve" ? "已通过，工作流继续排版。" : "已驳回，工作流按意见回退重生成。");
      setFeedback("");
      invalidateArticleData(queryClient, articleId);
      void stageQuery.refetch();
    },
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="审核" description="五维质量评分与回退建议">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-56 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const latest = stageQuery.data?.content.latest ?? null;
  const history = stageQuery.data?.content.history ?? [];
  const latestDecision = stageQuery.data?.content.latest_decision ?? null;
  const rejecting = decisionMutation.isPending && decisionMutation.variables === "reject";

  return (
    <PanelShell
      title="审核"
      description="按事实、结构、可读性、合规与原创性五维评分；不通过时会给出确定性的回退目标。"
      actions={
        <Button
          variant="outline"
          onClick={() => {
            void queryClient.invalidateQueries({ queryKey: ["stage", articleId, "review"] });
            void stageQuery.refetch();
          }}
        >
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          刷新报告
        </Button>
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {notice ? <Alert variant="success">{notice}</Alert> : null}

      {waiting ? (
        <Card className="border-amber-200 bg-amber-50/60">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">人工审稿确认</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs leading-5 text-slate-600">
              自动审稿已完成。通过会直接进入排版；驳回会根据意见判断回退到资料、大纲或写作阶段并重新生成。
            </p>
            <label className="block text-xs font-medium text-slate-600" htmlFor="review-feedback">
              驳回意见（驳回时必填）
            </label>
            <Textarea
              id="review-feedback"
              rows={3}
              value={feedback}
              placeholder="例如：数据来源不可靠，需要补充权威资料；或章节结构混乱需要调整"
              onChange={(event) => setFeedback(event.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => decisionMutation.mutate("approve")}
                loading={decisionMutation.isPending && !rejecting}
                disabled={decisionMutation.isPending}
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                通过并继续
              </Button>
              <Button
                variant="outline"
                onClick={() => decisionMutation.mutate("reject")}
                loading={rejecting}
                disabled={!feedback.trim() || decisionMutation.isPending}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                驳回并重新生成
              </Button>
            </div>
            {decisionMutation.isError ? (
              <Alert variant="destructive">{toErrorMessage(decisionMutation.error)}</Alert>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {latestDecision ? (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-2 p-4 text-xs text-slate-600">
            <Badge variant={latestDecision.decision === "approved" ? "success" : "warning"}>
              {latestDecision.decision === "approved" ? "人工通过" : "人工驳回"}
            </Badge>
            {latestDecision.rollback_to ? (
              <span>回退至 {stageLabel(latestDecision.rollback_to)}</span>
            ) : null}
            <span className="text-slate-400">{formatDate(latestDecision.created_at)}</span>
            {latestDecision.feedback ? (
              <p className="w-full whitespace-pre-wrap text-slate-500">{latestDecision.feedback}</p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {!latest ? (
        <EmptyState
          title="尚无审核报告"
          description="工作流生成正文后会进入审核阶段，报告将显示在这里。"
        />
      ) : (
        <ReportView report={latest} />
      )}

      {history.length > 1 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">历史报告</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {history.map((report) => (
              <details
                key={report.id}
                className="rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2 text-xs"
              >
                <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-slate-600">
                  <Badge variant={report.verdict === "pass" ? "success" : "destructive"}>
                    {report.verdict === "pass" ? "通过" : "未通过"}
                  </Badge>
                  <span className="font-semibold tabular-nums">{report.total.toFixed(1)} 分</span>
                  <span className="text-slate-400">{formatDate(report.created_at)}</span>
                  <span className="ml-auto text-slate-400">
                    {report.rollback_to ? `回退：${stageLabel(report.rollback_to)}` : "无需回退"}
                  </span>
                </summary>
                <p className="mt-2 whitespace-pre-wrap leading-5 text-slate-500">{report.rationale}</p>
              </details>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </PanelShell>
  );
}
