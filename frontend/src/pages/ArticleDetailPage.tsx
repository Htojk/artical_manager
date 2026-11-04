import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ListTree,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { api } from "../lib/api";
import {
  invalidateArticleData,
  queryKeys,
  useArticle,
  useStageTimeline,
} from "../hooks/useArticleQueries";
import { useEventSource } from "../hooks/useEventSource";
import {
  ACTIVE_RUN_STATUSES,
  RUN_STATUS_LABELS,
  STAGE_KEYS,
  stageLabel,
} from "../lib/labels";
import { formatDate, toErrorMessage } from "../lib/utils";
import type { ArticleStatus, RunStatus, StageKey } from "../types";
import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import {
  Dialog,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Skeleton } from "../components/ui/skeleton";
import { PageSkeleton, ErrorState } from "../components/common/States";
import { StatusBadge } from "../components/common/StatusBadge";
import { StageRail } from "../components/workflow/StageRail";
import { TopicPanel } from "../components/article/panels/TopicPanel";
import { ResearchPanel } from "../components/article/panels/ResearchPanel";
import { OutlinePanel } from "../components/article/panels/OutlinePanel";
import { WritingPanel } from "../components/article/panels/WritingPanel";
import { TitlePanel } from "../components/article/panels/TitlePanel";
import { ReviewPanel } from "../components/article/panels/ReviewPanel";
import { FormattingPanel } from "../components/article/panels/FormattingPanel";
import { PublishingPanel } from "../components/article/panels/PublishingPanel";

function isStageKey(value: string | null | undefined): value is StageKey {
  return Boolean(value) && STAGE_KEYS.includes(value as StageKey);
}

const ACTIVE_ARTICLE_STATUSES: ArticleStatus[] = [
  "running",
  "paused",
  "waiting_topic",
  "waiting_review",
  "waiting_publish",
  "needs_human",
];

export function ArticleDetailPage() {
  const { id = "" } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refreshAll = () => {
    if (!id) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.article(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.timeline(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.stageRoot(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.confirmSummary(id) });
  };

  const live = useEventSource({
    enabled: Boolean(id),
    onEvent: (event) => {
      if (event.article_id && event.article_id !== id) return;
      if (
        [
          "stage.status",
          "artifact.created",
          "review.completed",
          "review.waiting",
          "review.decided",
          "publish.updated",
          "run.status",
          "run.finished",
        ].includes(event.type)
      ) {
        refreshAll();
      }
    },
    onReconnect: refreshAll,
  });

  const articleQuery = useArticle(id);
  const timelineQuery = useStageTimeline(id);
  const activeArticleStatus =
    !!articleQuery.data && ACTIVE_ARTICLE_STATUSES.includes(articleQuery.data.article.status);
  const shouldFallbackPoll = live.status === "error" && activeArticleStatus;

  useEffect(() => {
    if (!shouldFallbackPoll || !id) return;
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.article(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.timeline(id) });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [shouldFallbackPoll, id, queryClient]);

  const startMutation = useMutation({
    mutationFn: () => api.startRun(id),
    onSuccess: () => {
      setMessage("工作流已启动。阶段状态会实时更新。");
      invalidateArticleData(queryClient, id);
    },
  });

  const pauseMutation = useMutation({
    mutationFn: (runId: string) => api.pauseRun(runId),
    onSuccess: () => {
      setMessage("已请求暂停，将在当前阶段结束后停止。");
      invalidateArticleData(queryClient, id);
    },
  });

  const resumeMutation = useMutation({
    mutationFn: (runId: string) => api.resumeRun(runId),
    onSuccess: () => {
      setMessage("工作流已继续。");
      invalidateArticleData(queryClient, id);
    },
  });

  if (!id) {
    return <ErrorState message="缺少文章 ID。" />;
  }

  if (articleQuery.isLoading || timelineQuery.isLoading) {
    return <PageSkeleton />;
  }

  if (articleQuery.isError || !articleQuery.data) {
    return (
      <div className="space-y-4">
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          返回文章列表
        </Link>
        <ErrorState
          message={toErrorMessage(articleQuery.error)}
          onRetry={() => void articleQuery.refetch()}
        />
      </div>
    );
  }

  const article = articleQuery.data.article;
  const timeline = timelineQuery.data;
  const run = timeline?.run ?? null;
  const stages = timeline?.stages ?? [];
  const stageParam = searchParams.get("stage");
  const fallbackStage: StageKey = isStageKey(timeline?.article.current_stage)
    ? (timeline?.article.current_stage as StageKey)
    : "topic_selection";
  const activeStage: StageKey = isStageKey(stageParam) ? stageParam : fallbackStage;
  const autoRecommend = searchParams.get("recommend") === "1";
  const domain = searchParams.get("domain") ?? "";

  const selectStage = (stage: StageKey) => {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set("stage", stage);
        return next;
      },
      { replace: true },
    );
    setDrawerOpen(false);
  };

  const articleIsActive = ACTIVE_ARTICLE_STATUSES.includes(article.status);
  const activeRun = !!run && ACTIVE_RUN_STATUSES.includes(run.status);
  const canStart =
    !articleIsActive &&
    !activeRun &&
    Boolean(article.current_topic_id) &&
    !startMutation.isPending;
  const canPause =
    !!run &&
    ["pending", "running"].includes(run.status) &&
    !run.pause_requested &&
    !pauseMutation.isPending;
  const canResume =
    !!run && ["paused", "interrupted"].includes(run.status) && !resumeMutation.isPending;
  const actionError =
    startMutation.error ?? pauseMutation.error ?? resumeMutation.error ?? null;
  const liveLabel =
    live.status === "open"
      ? "实时已连接"
      : live.status === "error"
        ? "连接中断 · 轮询中"
        : live.status === "connecting"
          ? "正在连接"
          : "未连接";

  const panel = (() => {
    switch (activeStage) {
      case "topic_selection":
        return <TopicPanel articleId={id} domain={domain} autoRecommend={autoRecommend} />;
      case "research":
        return <ResearchPanel articleId={id} />;
      case "outline":
        return <OutlinePanel articleId={id} />;
      case "writing":
        return <WritingPanel articleId={id} />;
      case "title_optimization":
        return <TitlePanel articleId={id} />;
      case "review":
        return (
          <ReviewPanel
            articleId={id}
            waiting={article.status === "waiting_review" || run?.status === "waiting_review"}
          />
        );
      case "formatting":
        return <FormattingPanel articleId={id} platforms={article.target_platforms} />;
      case "publishing":
        return (
          <PublishingPanel
            articleId={id}
            articleStatus={article.status}
            runStatus={(run?.status as RunStatus | undefined) ?? null}
            platforms={article.target_platforms}
          />
        );
      default:
        return null;
    }
  })();

  return (
    <div className="space-y-5">
      <div>
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-slate-500 transition-colors hover:text-slate-800"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          返回文章列表
        </Link>
        <div className="mt-3 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
              {article.title || "未命名选题"}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge kind="article" status={article.status} />
              {run ? <StatusBadge kind="run" status={run.status} /> : null}
              <Badge variant="outline">当前阶段：{stageLabel(article.current_stage)}</Badge>
              <Badge variant={live.status === "open" ? "success" : live.status === "error" ? "warning" : "outline"}>
                {live.status === "open" ? (
                  <Wifi className="h-3 w-3" aria-hidden="true" />
                ) : (
                  <WifiOff className="h-3 w-3" aria-hidden="true" />
                )}
                {liveLabel}
              </Badge>
            </div>
            <p className="mt-2 text-xs text-slate-400">
              创建于 {formatDate(article.created_at)} · 更新于 {formatDate(article.updated_at)}
              {run ? ` · 返工 ${run.revision_count}/${run.max_revisions}` : ""}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={refreshAll}>
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              刷新
            </Button>
            {canPause ? (
              <Button
                variant="warning"
                onClick={() => run && pauseMutation.mutate(run.id)}
                loading={pauseMutation.isPending}
              >
                <Pause className="h-4 w-4" aria-hidden="true" />
                {run?.pause_requested ? "暂停中…" : "暂停"}
              </Button>
            ) : null}
            {canResume ? (
              <Button
                variant="outline"
                onClick={() => run && resumeMutation.mutate(run.id)}
                loading={resumeMutation.isPending}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                继续运行
              </Button>
            ) : null}
            <Button
              onClick={() => startMutation.mutate()}
              loading={startMutation.isPending}
              disabled={!canStart}
              title={
                !article.current_topic_id
                  ? "请先在选题节点选择一个选题"
                  : activeRun || articleIsActive
                    ? "已有活动运行"
                    : undefined
              }
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              启动工作流
            </Button>
          </div>
        </div>
      </div>

      {message ? <Alert variant="success">{message}</Alert> : null}
      {actionError ? <Alert variant="destructive">{toErrorMessage(actionError)}</Alert> : null}
      {article.error ? <Alert variant="destructive" title="文章错误">{article.error}</Alert> : null}
      {live.status === "error" ? (
        <Alert variant="warning" title="实时连接中断">
          正在按指数退避重连；文章处于活动状态时每 5 秒轮询一次工作流。已触发的阶段内容仍可查看与编辑。
        </Alert>
      ) : null}
      {!article.current_topic_id && activeStage !== "topic_selection" ? (
        <Alert variant="info">
          尚未选择选题，工作流无法启动。请切换到「选题」节点选择或创建一个主题。
        </Alert>
      ) : null}
      {timelineQuery.isError ? (
        <ErrorState
          compact
          message={`流程状态加载失败：${toErrorMessage(timelineQuery.error)}`}
          onRetry={() => void timelineQuery.refetch()}
        />
      ) : null}

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:gap-6" data-testid="article-scroll-container">
        <aside className="hidden w-[264px] shrink-0 self-start lg:sticky lg:top-20 lg:block" data-testid="sticky-stage-rail">
          <Card>
            <CardContent className="p-4">
              {timeline ? (
                <StageRail
                  stages={stages}
                  activeStage={activeStage}
                  onSelect={selectStage}
                  articleStatus={article.status}
                  runStatus={run?.status ?? null}
                  currentStage={timeline.article.current_stage}
                />
              ) : (
                <div className="space-y-3">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              )}
            </CardContent>
          </Card>
          {run ? (
            <Card className="mt-3">
              <CardContent className="space-y-2 p-4 text-xs text-slate-500">
                <div className="flex items-center justify-between">
                  <span>运行状态</span>
                  <StatusBadge kind="run" status={run.status} />
                </div>
                <div className="flex items-center justify-between">
                  <span>当前阶段</span>
                  <span className="font-medium text-slate-700">{stageLabel(run.current_stage)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>运行 ID</span>
                  <span className="font-mono text-[10px] text-slate-400">{run.id.slice(0, 8)}</span>
                </div>
              </CardContent>
            </Card>
          ) : null}
        </aside>

        <div className="min-w-0 flex-1 space-y-3">
          <div className="lg:hidden">
            <Card>
              <CardContent className="flex items-center gap-2 p-2.5">
                <div className="scrollbar-thin min-w-0 flex-1 overflow-x-auto">
                  <StageRail
                    variant="horizontal"
                    stages={stages}
                    activeStage={activeStage}
                    onSelect={selectStage}
                    articleStatus={article.status}
                    runStatus={run?.status ?? null}
                    currentStage={timeline?.article.current_stage}
                    showLegend={false}
                  />
                </div>
                <Button variant="outline" size="sm" onClick={() => setDrawerOpen(true)}>
                  <ListTree className="h-3.5 w-3.5" aria-hidden="true" />
                  流程
                </Button>
              </CardContent>
            </Card>
          </div>

          <Card className="min-h-[520px]">
            <CardContent className="p-4 sm:p-6">{panel}</CardContent>
          </Card>
        </div>
      </div>

      <Dialog
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        side="left"
        labelledBy="mobile-stage-title"
      >
        <DialogHeader>
          <DialogTitle id="mobile-stage-title">生成流程</DialogTitle>
        </DialogHeader>
        <div className="px-4 pb-6">
          <StageRail
            stages={stages}
            activeStage={activeStage}
            onSelect={selectStage}
            articleStatus={article.status}
            runStatus={run?.status ?? null}
            currentStage={timeline?.article.current_stage}
          />
          {run ? (
            <div className="mt-4 border-t border-slate-100 pt-4 text-xs text-slate-500">
              运行状态：{RUN_STATUS_LABELS[run.status] ?? run.status} · 返工{" "}
              {run.revision_count}/{run.max_revisions}
            </div>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
