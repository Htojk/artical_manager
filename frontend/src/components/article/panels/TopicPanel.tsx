import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Flame,
  Lightbulb,
  MessageCircle,
  Plus,
  RefreshCw,
  Sparkles,
  Target,
} from "lucide-react";
import { api } from "../../../lib/api";
import { invalidateArticleData, useStageDetail, queryKeys } from "../../../hooks/useArticleQueries";
import { toErrorMessage } from "../../../lib/utils";
import { platformLabel } from "../../../lib/labels";
import type { Topic } from "../../../types";
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
import { Textarea } from "../../ui/textarea";
import { EmptyState, ErrorState } from "../../common/States";
import { MetaLine, PanelShell, SectionTitle, StageRunSummary } from "./shared";

interface TopicPanelProps {
  articleId: string;
  domain?: string;
  autoRecommend?: boolean;
}

const FORMAT_LABELS: Record<string, string> = {
  hot_take: "热点轻解读",
  tool_test: "AI 工具实测",
  creative_experiment: "AI 脑洞实验",
};

function CandidateCard({
  topic,
  selected,
  disabled,
  onSelect,
}: {
  topic: Topic;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  return (
    <Card
      className={
        selected
          ? "border-indigo-300 bg-gradient-to-br from-indigo-50/80 to-white"
          : "bg-white"
      }
      data-testid={`topic-candidate-${topic.id}`}
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              <Badge variant={topic.source === "ai_hot" ? "warning" : "info"}>
                {topic.source === "ai_hot" ? "热点" : topic.source === "ai" ? "AI 候选" : "手动"}
              </Badge>
              {topic.selected ? (
                <Badge variant="success">
                  <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                  当前选题
                </Badge>
              ) : null}
              {topic.content_format ? (
                <Badge variant="outline">{FORMAT_LABELS[topic.content_format] ?? topic.content_format}</Badge>
              ) : null}
              {topic.entertainment_score ? (
                <Badge
                  variant={topic.entertainment_score >= 80 ? "success" : "outline"}
                  title={topic.entertainment_reason || "账号适配评分"}
                >
                  娱乐适配 {Math.round(topic.entertainment_score)}
                </Badge>
              ) : topic.discussion_score ? (
                <Badge
                  variant={topic.discussion_score >= 80 ? "success" : "outline"}
                  title={topic.discussion_reason || "讨论度评分"}
                >
                  讨论度 {Math.round(topic.discussion_score)}
                </Badge>
              ) : null}
            </div>
            <h3 className="text-sm font-semibold leading-6 text-slate-900">{topic.title}</h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">{topic.angle}</p>
          </div>
          <Button
            size="sm"
            variant={selected ? "secondary" : "outline"}
            disabled={selected || disabled}
            onClick={onSelect}
            aria-label={`选择选题：${topic.title}`}
          >
            {selected ? "已选择" : "选择"}
          </Button>
        </div>

        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-500">
          {topic.rationale}
        </p>

        {topic.entertainment_reason || topic.discussion_reason ? (
          <p className="flex items-start gap-1.5 text-xs leading-5 text-indigo-700">
            <MessageCircle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            <span>{topic.entertainment_reason ? `推荐理由：${topic.entertainment_reason}` : `讨论度理由：${topic.discussion_reason}`}</span>
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-1.5">
          {topic.target_platforms.map((platform) => (
            <Badge key={platform} variant="outline">
              {platformLabel(platform)}
            </Badge>
          ))}
          {topic.hot_signals.slice(0, 2).map((signal, index) => {
            const label = signal.title ?? signal.source ?? "热点信号";
            const className =
              "inline-flex items-center gap-1 text-[11px] text-amber-600";
            return signal.url ? (
              <a
                key={`${label}-${index}`}
                href={signal.url}
                target="_blank"
                rel="noreferrer"
                className={className}
              >
                <Flame className="h-3 w-3" aria-hidden="true" />
                {label}
              </a>
            ) : (
              <span key={`${label}-${index}`} className={className}>
                <Flame className="h-3 w-3" aria-hidden="true" />
                {label}
              </span>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

export function TopicPanel({ articleId, domain, autoRecommend = false }: TopicPanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "topic_selection");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [angle, setAngle] = useState("");
  const [contentFormat, setContentFormat] = useState("hot_take");
  const [message, setMessage] = useState<string | null>(null);
  const autoTriggered = useRef(false);

  const content = stageQuery.data?.content;
  const selected = content?.selected ?? null;
  const topics = content?.topics ?? [];

  const recommendMutation = useMutation({
    mutationFn: () =>
      api.recommendTopics(articleId, {
        domain: domain ?? "",
        exclude_titles: topics.map((topic) => topic.title),
      }),
    onSuccess: (result) => {
      setMessage(
        `已生成 ${result.items.length} 个候选选题${result.fallback_used ? "（热点源不可用，已使用模型知识）" : ""}。`,
      );
      invalidateArticleData(queryClient, articleId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.stage(articleId, "topic_selection") });
    },
  });

  const selectMutation = useMutation({
    mutationFn: (topicId: string) => api.selectTopic(articleId, topicId),
    onSuccess: (result) => {
      const fetchNote = result.source_fetch?.ok
        ? "已抓取关联正文并保存为来源。"
        : result.source_fetch?.error
          ? `正文抓取失败：${result.source_fetch.error}`
          : result.source_fetch?.reason === "候选未关联文章链接"
            ? "该候选未关联文章链接，未抓取正文。"
            : "";
      setMessage(
        `已选择「${result.topic.title}」。${fetchNote ? `${fetchNote}` : ""}现在可以启动工作流。`,
      );
      invalidateArticleData(queryClient, articleId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.stage(articleId, "topic_selection") });
    },
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      const topic = await api.createTopic(articleId, {
        title: title.trim(),
        angle: angle.trim(),
        rationale: "用户手动输入",
        content_format: contentFormat,
      });
      await api.selectTopic(articleId, topic.id);
      return topic;
    },
    onSuccess: (topic) => {
      setDialogOpen(false);
      setTitle("");
      setAngle("");
      setContentFormat("hot_take");
      setMessage(`已添加并选择「${topic.title}」。`);
      invalidateArticleData(queryClient, articleId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.stage(articleId, "topic_selection") });
    },
  });

  useEffect(() => {
    if (!autoRecommend || autoTriggered.current || !stageQuery.data) return;
    if (stageQuery.data.content.topics.length !== 0) return;
    autoTriggered.current = true;
    recommendMutation.mutate();
  }, [autoRecommend, stageQuery.data, recommendMutation]);

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="选题" description="选择或推荐一个可执行的文章主题">
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const mutationError =
    recommendMutation.error ?? selectMutation.error ?? createMutation.error ?? null;

  return (
    <PanelShell
      title="选题"
      description="手动创建主题，或让 AI 结合热点推荐 5 个候选选题。"
      actions={
        <>
          <Button variant="outline" onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            手动添加
          </Button>
          <Button onClick={() => recommendMutation.mutate()} loading={recommendMutation.isPending}>
            {topics.length === 0 ? (
              <Sparkles className="h-4 w-4" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            {topics.length === 0 ? "推荐 5 个选题" : "刷新推荐"}
          </Button>
        </>
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {message ? <Alert variant="success">{message}</Alert> : null}
      {mutationError ? <Alert variant="destructive">{toErrorMessage(mutationError)}</Alert> : null}
      {recommendMutation.data ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <Badge variant="info">本轮 5 个候选</Badge>
          <span>热点信号 {recommendMutation.data.hot_signal_count} 条</span>
          {recommendMutation.data.hot_errors.length > 0 ? (
            <span className="text-amber-600">
              热点源降级：{recommendMutation.data.hot_errors.join("；")}
            </span>
          ) : null}
        </div>
      ) : null}

      <Card className="border-indigo-100 bg-gradient-to-br from-white to-indigo-50/40">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Target className="h-4 w-4 text-indigo-600" aria-hidden="true" />
            <CardTitle>当前选题</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          {selected ? (
            <div className="space-y-2">
              <h3 className="text-base font-semibold text-slate-900">{selected.title}</h3>
              <p className="text-sm leading-6 text-slate-600">{selected.angle}</p>
              <MetaLine>
                来源：{selected.source} · 目标平台：
                {selected.target_platforms.map(platformLabel).join("、") || "默认平台"}
              </MetaLine>
            </div>
          ) : (
            <div className="flex items-center gap-2 py-2 text-sm text-amber-700">
              <Lightbulb className="h-4 w-4" aria-hidden="true" />
              尚未选择选题。选择下方候选，或手动添加一个主题。
            </div>
          )}
        </CardContent>
      </Card>

      <div>
        <SectionTitle
          action={<span className="text-xs text-slate-400">{topics.length} 个候选</span>}
        >
          候选选题
        </SectionTitle>
        {topics.length === 0 ? (
          <EmptyState
            title="还没有候选选题"
            description="点击「推荐 5 个选题」生成 AI 候选，或手动添加主题。"
            action={
              <Button size="sm" onClick={() => recommendMutation.mutate()} loading={recommendMutation.isPending}>
                <Sparkles className="h-4 w-4" aria-hidden="true" />
                开始推荐
              </Button>
            }
          />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {topics.map((topic) => (
              <CandidateCard
                key={topic.id}
                topic={topic}
                selected={selected?.id === topic.id || topic.selected}
                disabled={selectMutation.isPending}
                onSelect={() => selectMutation.mutate(topic.id)}
              />
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen} labelledBy="manual-topic-title">
        <DialogHeader>
          <DialogTitle id="manual-topic-title">手动添加选题</DialogTitle>
          <DialogDescription>创建后会立即设为当前选题。</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (title.trim()) createMutation.mutate();
          }}
        >
          <DialogContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="topic-title">主题</Label>
              <Input
                id="topic-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：AI Agent 如何改变软件开发流程"
                required
                minLength={5}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="topic-angle">切入角度</Label>
              <Textarea
                id="topic-angle"
                value={angle}
                onChange={(event) => setAngle(event.target.value)}
                placeholder="从工程实践与团队协作切入，结合真实案例…"
                rows={3}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="topic-format">内容形式</Label>
              <Select id="topic-format" value={contentFormat} onChange={(event) => setContentFormat(event.target.value)}>
                {Object.entries(FORMAT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </Select>
            </div>
            {createMutation.error ? (
              <Alert variant="destructive">{toErrorMessage(createMutation.error)}</Alert>
            ) : null}
          </DialogContent>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button
              type="submit"
              loading={createMutation.isPending}
              disabled={title.trim().length < 5}
            >
              添加并选择
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </PanelShell>
  );
}
