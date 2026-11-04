import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Link2,
  RefreshCw,
  Send,
  XCircle,
} from "lucide-react";
import { api } from "../../../lib/api";
import {
  invalidateArticleData,
  queryKeys,
  useStageDetail,
} from "../../../hooks/useArticleQueries";
import type { ArticleStatus, PublishRecord, RunStatus } from "../../../types";
import { PUBLISH_STATUS_LABELS, platformLabel } from "../../../lib/labels";
import { formatDate, formatMoney, formatNumber, toErrorMessage } from "../../../lib/utils";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../../ui/dialog";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import { Select } from "../../ui/select";
import { Skeleton } from "../../ui/skeleton";
import { StatusBadge } from "../../common/StatusBadge";
import { EmptyState, ErrorState } from "../../common/States";
import { PanelShell, StageRunSummary } from "./shared";

interface PublishingPanelProps {
  articleId: string;
  articleStatus: ArticleStatus;
  runStatus: RunStatus | null;
  platforms: string[];
}

function canRetry(record: PublishRecord): boolean {
  return !["published", "draft", "publishing"].includes(record.status);
}

function RecordCard({
  record,
  onRetry,
  onManual,
  retrying,
}: {
  record: PublishRecord;
  onRetry: () => void;
  onManual: () => void;
  retrying: boolean;
}) {
  return (
    <Card>
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">{platformLabel(record.platform)}</CardTitle>
            <StatusBadge kind="publish" status={record.status} />
            {record.attempt > 0 ? (
              <span className="text-[11px] text-slate-400">第 {record.attempt} 次尝试</span>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {canRetry(record) ? (
              <Button size="sm" variant="outline" onClick={onRetry} loading={retrying}>
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                重试
              </Button>
            ) : null}
            <Button size="sm" variant="outline" onClick={onManual}>
              <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
              手动回填
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {record.url ? (
          <a
            href={record.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 font-medium text-indigo-600 hover:underline"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
            {record.url}
          </a>
        ) : (
          <p className="text-slate-400">尚无发布链接</p>
        )}
        <div className="grid grid-cols-2 gap-2 text-slate-500">
          <span>远端 ID：{record.remote_id ?? "—"}</span>
          <span>发布时间：{formatDate(record.published_at)}</span>
          <span>更新时间：{formatDate(record.updated_at)}</span>
          <span>
            最新阅读：{formatNumber(record.latest_metric?.views ?? 0)} · 收益{" "}
            {formatMoney(record.latest_metric?.revenue_yuan ?? 0)}
          </span>
        </div>
        {record.error ? (
          <div className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{record.error}</div>
        ) : null}
        {record.history && record.history.length > 0 ? (
          <details className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2">
            <summary className="cursor-pointer text-slate-600">
              状态历史（{record.history.length}）
            </summary>
            <div className="mt-2 space-y-1">
              {record.history.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="text-slate-600">
                    {PUBLISH_STATUS_LABELS[item.status] ?? item.status}
                    <span className="ml-1 text-slate-400">· {item.source}</span>
                  </span>
                  <span className="text-slate-400">{formatDate(item.created_at)}</span>
                </div>
              ))}
            </div>
          </details>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function PublishingPanel({
  articleId,
  articleStatus,
  runStatus,
  platforms,
}: PublishingPanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "publishing");
  const awaitingConfirmation =
    runStatus === "waiting_publish" || articleStatus === "waiting_publish";
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [manualPlatform, setManualPlatform] = useState<string | null>(null);
  const [manualUrl, setManualUrl] = useState("");
  const [manualRemoteId, setManualRemoteId] = useState("");
  const [manualStatus, setManualStatus] = useState<"published" | "offline" | "failed">("published");
  const [message, setMessage] = useState<string | null>(null);

  const summaryQuery = useQuery({
    queryKey: queryKeys.confirmSummary(articleId),
    queryFn: () => api.confirmSummary(articleId),
    enabled: confirmOpen,
  });

  const publishMutation = useMutation({
    mutationFn: async () => {
      if (awaitingConfirmation) {
        return api.confirmPublish(articleId, "approve");
      }
      return api.publishNow(articleId, platforms.length > 0 ? platforms : undefined);
    },
    onSuccess: () => {
      setConfirmOpen(false);
      setMessage(
        awaitingConfirmation
          ? "已确认发布，工作流将继续执行。"
          : "发布请求已提交，请查看各平台状态。",
      );
      invalidateArticleData(queryClient, articleId);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => api.confirmPublish(articleId, "cancel"),
    onSuccess: () => {
      setConfirmOpen(false);
      setMessage("已取消本次发布。");
      invalidateArticleData(queryClient, articleId);
    },
  });

  const retryMutation = useMutation({
    mutationFn: (platform: string) => api.retryPublish(articleId, platform),
    onSuccess: () => {
      setMessage("重试请求已提交。");
      invalidateArticleData(queryClient, articleId);
    },
  });

  const manualMutation = useMutation({
    mutationFn: (platform: string) =>
      api.manualPublish(articleId, platform, {
        url: manualUrl.trim(),
        remote_id: manualRemoteId.trim() || null,
        status: manualStatus,
      }),
    onSuccess: () => {
      setManualPlatform(null);
      setManualUrl("");
      setManualRemoteId("");
      setMessage("已回填发布链接与状态。");
      invalidateArticleData(queryClient, articleId);
    },
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="发布" description="确认发布、状态与手动回填">
        <Skeleton className="h-40 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const records = stageQuery.data?.content.records ?? [];
  const publishedCount = records.filter((record) => record.status === "published").length;
  const failedCount = records.filter((record) =>
    ["failed", "manual_required", "unavailable"].includes(record.status),
  ).length;
  const publishError = publishMutation.error;
  const cancelError = cancelMutation.error;

  return (
    <PanelShell
      title="发布"
      description="发布前需人工确认摘要。平台不支持自动发布时，可通过手动回填记录链接与状态。"
      actions={
        <>
          {awaitingConfirmation ? (
            <Button
              variant="outline"
              onClick={() => cancelMutation.mutate()}
              loading={cancelMutation.isPending}
            >
              <XCircle className="h-4 w-4" aria-hidden="true" />
              取消发布
            </Button>
          ) : null}
          <Button onClick={() => setConfirmOpen(true)}>
            <Send className="h-4 w-4" aria-hidden="true" />
            {awaitingConfirmation ? "确认发布" : "发布就绪平台"}
          </Button>
        </>
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {message ? <Alert variant="success">{message}</Alert> : null}
      {publishError ? <Alert variant="destructive">{toErrorMessage(publishError)}</Alert> : null}
      {cancelError ? <Alert variant="destructive">{toErrorMessage(cancelError)}</Alert> : null}
      {retryMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(retryMutation.error)}</Alert>
      ) : null}

      {awaitingConfirmation ? (
        <Alert variant="warning" title="工作流正在等待发布确认">
          批准后工作流将继续发布；取消会结束本次运行并保留当前发布状态。
        </Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-slate-500">发布平台</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">{records.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-slate-500">成功发布</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-emerald-600">{publishedCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-slate-500">需要处理</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-amber-600">{failedCount}</p>
          </CardContent>
        </Card>
      </div>

      {records.length === 0 ? (
        <EmptyState
          title="尚无发布记录"
          description="确认发布后，每个目标平台都会产生一条发布记录。"
          icon={<Send className="h-5 w-5" aria-hidden="true" />}
        />
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          {records.map((record) => (
            <RecordCard
              key={record.id}
              record={record}
              retrying={
                retryMutation.isPending && retryMutation.variables === record.platform
              }
              onRetry={() => retryMutation.mutate(record.platform)}
              onManual={() => {
                setManualPlatform(record.platform);
                setManualUrl(record.url ?? "");
                setManualRemoteId(record.remote_id ?? "");
                setManualStatus("published");
              }}
            />
          ))}
        </div>
      )}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          setConfirmOpen(open);
          if (!open) publishMutation.reset();
        }}
        labelledBy="confirm-publish-title"
      >
        <DialogHeader>
          <DialogTitle id="confirm-publish-title">确认发布</DialogTitle>
          <DialogDescription>
            请核对目标平台、排版产物与凭据状态。发布会产生真实的外部操作。
          </DialogDescription>
        </DialogHeader>
        <DialogContent className="space-y-3">
          {summaryQuery.isLoading ? <Skeleton className="h-24 w-full" /> : null}
          {summaryQuery.isError ? (
            <ErrorState
              compact
              message={toErrorMessage(summaryQuery.error)}
              onRetry={() => void summaryQuery.refetch()}
            />
          ) : null}
          {summaryQuery.data ? (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-slate-800">{summaryQuery.data.title}</p>
              <div className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                {summaryQuery.data.platforms.map((platform) => (
                  <div key={platform.platform} className="flex items-start gap-3 px-3 py-2.5 text-xs">
                    {platform.artifact_ready && platform.available ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" aria-hidden="true" />
                    ) : (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden="true" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-slate-700">
                        {platform.display_name} · {platform.mode}
                      </p>
                      <p className="mt-0.5 text-slate-400">
                        {platform.artifact_ready ? "排版产物已就绪" : "排版产物未就绪"} ·{" "}
                        {platform.available ? "凭据可用" : platform.reason || "凭据不可用"}
                      </p>
                    </div>
                    <Badge variant={platform.artifact_ready && platform.available ? "success" : "warning"}>
                      {platform.artifact_ready && platform.available ? "可发布" : "将转手动/失败"}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {publishMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(publishMutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              if (awaitingConfirmation) {
                cancelMutation.mutate();
              } else {
                setConfirmOpen(false);
              }
            }}
            loading={cancelMutation.isPending}
          >
            {awaitingConfirmation ? "取消发布" : "取消"}
          </Button>
          <Button
            type="button"
            onClick={() => publishMutation.mutate()}
            loading={publishMutation.isPending}
          >
            {awaitingConfirmation ? "批准并发布" : "确认发布"}
          </Button>
        </DialogFooter>
      </Dialog>

      <Dialog
        open={manualPlatform !== null}
        onOpenChange={(open) => {
          if (!open) setManualPlatform(null);
        }}
        labelledBy="manual-publish-title"
      >
        <DialogHeader>
          <DialogTitle id="manual-publish-title">
            手动回填 · {manualPlatform ? platformLabel(manualPlatform) : ""}
          </DialogTitle>
          <DialogDescription>
            平台不支持自动发布时，手动发布后在此记录链接与状态。
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (manualPlatform && manualUrl.trim()) manualMutation.mutate(manualPlatform);
          }}
        >
          <DialogContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="manual-url">发布链接</Label>
              <Input
                id="manual-url"
                type="url"
                required
                value={manualUrl}
                onChange={(event) => setManualUrl(event.target.value)}
                placeholder="https://"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="manual-remote-id">平台文章 ID（可选）</Label>
              <Input
                id="manual-remote-id"
                value={manualRemoteId}
                onChange={(event) => setManualRemoteId(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="manual-status">状态</Label>
              <Select
                id="manual-status"
                value={manualStatus}
                onChange={(event) =>
                  setManualStatus(event.target.value as "published" | "offline" | "failed")
                }
              >
                <option value="published">已发布</option>
                <option value="offline">已下线</option>
                <option value="failed">失败</option>
              </Select>
            </div>
            {manualMutation.error ? (
              <Alert variant="destructive">{toErrorMessage(manualMutation.error)}</Alert>
            ) : null}
          </DialogContent>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setManualPlatform(null)}>
              取消
            </Button>
            <Button
              type="submit"
              loading={manualMutation.isPending}
              disabled={!manualUrl.trim()}
            >
              保存回填
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </PanelShell>
  );
}
