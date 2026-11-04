import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Cpu, Hash, Save, Sparkles, Type } from "lucide-react";
import { api } from "../../../lib/api";
import { invalidateArticleData, useStageDetail } from "../../../hooks/useArticleQueries";
import type { DraftVersion, JsonValue } from "../../../types";
import { formatDate, formatNumber, toErrorMessage } from "../../../lib/utils";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import { Select } from "../../ui/select";
import { Skeleton } from "../../ui/skeleton";
import { Textarea } from "../../ui/textarea";
import { EmptyState, ErrorState } from "../../common/States";
import { MarkdownEditor } from "../../markdown/MarkdownEditor";
import { PanelShell, StageRunSummary } from "./shared";

interface WritingPanelProps {
  articleId: string;
}

function skillLabel(value: JsonValue): string {
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const record = value as Record<string, JsonValue>;
    if (typeof record.name === "string") return record.name;
    if (typeof record.slug === "string") return record.slug;
  }
  return JSON.stringify(value);
}

export function WritingPanel({ articleId }: WritingPanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "writing");
  const [markdown, setMarkdown] = useState("");
  const [summary, setSummary] = useState("");
  const [title, setTitle] = useState("");
  const [selectedVersion, setSelectedVersion] = useState("");
  const loadedVersion = useRef<string | null>(null);

  const latest = stageQuery.data?.content.latest ?? null;
  const history = stageQuery.data?.content.history ?? [];

  useEffect(() => {
    if (!latest || loadedVersion.current === latest.id) return;
    loadedVersion.current = latest.id;
    setMarkdown(latest.content_md);
    setSummary(latest.summary);
    setSelectedVersion(latest.id);
  }, [latest]);

  const saveMutation = useMutation({
    mutationFn: () =>
      api.saveDraft(articleId, {
        content_md: markdown,
        summary,
        title: title.trim() || null,
      }),
    onSuccess: () => {
      invalidateArticleData(queryClient, articleId);
    },
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="写作" description="正文、版本与生成元数据">
        <Skeleton className="h-72 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const loadVersion = (version: DraftVersion) => {
    setSelectedVersion(version.id);
    setMarkdown(version.content_md);
    setSummary(version.summary);
    setTitle("");
  };

  const liveWordCount = markdown.replace(/\s+/g, "").length;

  return (
    <PanelShell
      title="写作"
      description="查看最新正文与版本历史，编辑保存会生成新版本，并供后续审核与排版使用。"
      actions={
        latest ? (
          <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
            <Save className="h-4 w-4" aria-hidden="true" />
            保存正文
          </Button>
        ) : null
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {!latest ? (
        <EmptyState
          title="尚无正文"
          description="运行工作流到写作阶段后，正文会显示在这里。你也可以在选题后启动生成。"
        />
      ) : (
        <>
          {saveMutation.isSuccess ? (
            <Alert variant="success">正文已保存为新版本。审核和排版将读取最新内容。</Alert>
          ) : null}
          {saveMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(saveMutation.error)}</Alert>
          ) : null}

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Type className="h-3.5 w-3.5" aria-hidden="true" />
                  当前字数
                </div>
                <p className="mt-1 text-xl font-bold tabular-nums text-slate-900">
                  {formatNumber(liveWordCount)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Hash className="h-3.5 w-3.5" aria-hidden="true" />
                  版本
                </div>
                <p className="mt-1 text-xl font-bold tabular-nums text-slate-900">
                  v{latest.version}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <Cpu className="h-3.5 w-3.5" aria-hidden="true" />
                  模型
                </div>
                <p className="mt-1 truncate text-sm font-semibold text-slate-900">
                  {latest.model ?? "未记录"}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                  <CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />
                  更新时间
                </div>
                <p className="mt-1 truncate text-sm font-semibold text-slate-900">
                  {formatDate(latest.created_at)}
                </p>
              </CardContent>
            </Card>
          </div>

          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-3 text-xs text-slate-500">
            <Sparkles className="h-3.5 w-3.5 text-indigo-500" aria-hidden="true" />
            <span className="font-medium text-slate-700">生成技能</span>
            {latest.skill_snapshot.length === 0 ? (
              <span className="text-slate-400">未使用技能</span>
            ) : (
              latest.skill_snapshot.map((skill, index) => (
                <Badge key={`${skillLabel(skill)}-${index}`} variant="purple">
                  {skillLabel(skill)}
                </Badge>
              ))
            )}
            <span className="ml-auto">Token：{formatNumber(latest.prompt_tokens)} / {formatNumber(latest.completion_tokens)}</span>
            {latest.duration_ms && latest.duration_ms > 0 ? (
              <span>耗时：{(latest.duration_ms / 1000).toFixed(1)} 秒</span>
            ) : null}
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>Markdown 编辑器</CardTitle>
                  <Badge variant="info">v{latest.version}</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="draft-summary">摘要</Label>
                    <Textarea
                      id="draft-summary"
                      value={summary}
                      onChange={(event) => setSummary(event.target.value)}
                      rows={2}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="draft-title">文章标题（可选）</Label>
                    <Input
                      id="draft-title"
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                      placeholder="留空则保持当前标题"
                    />
                  </div>
                </div>
                <MarkdownEditor value={markdown} onChange={setMarkdown} />
                <div className="flex justify-end">
                  <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
                    <Save className="h-4 w-4" aria-hidden="true" />
                    保存为新版本
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card className="h-fit">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">版本历史</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Select
                  value={selectedVersion}
                  onChange={(event) => {
                    const version = history.find((item) => item.id === event.target.value);
                    if (version) loadVersion(version);
                  }}
                  aria-label="选择正文版本"
                >
                  {[...history]
                    .sort((a, b) => b.version - a.version)
                    .map((version) => (
                      <option key={version.id} value={version.id}>
                        v{version.version} · {formatNumber(version.word_count)} 字
                      </option>
                    ))}
                </Select>
                <div className="max-h-[520px] space-y-2 overflow-y-auto pr-1">
                  {history.map((version) => (
                    <button
                      type="button"
                      key={version.id}
                      onClick={() => loadVersion(version)}
                      className="w-full rounded-lg border border-slate-100 px-3 py-2 text-left text-xs transition-colors hover:border-indigo-200 hover:bg-indigo-50/50"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-slate-700">v{version.version}</span>
                        <span className="text-slate-400">{formatDate(version.created_at)}</span>
                      </span>
                      <span className="mt-1 flex items-center justify-between gap-2 text-slate-500">
                        <span className="truncate">{version.note || version.created_by}</span>
                        <span>{formatNumber(version.word_count)} 字</span>
                      </span>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </PanelShell>
  );
}
