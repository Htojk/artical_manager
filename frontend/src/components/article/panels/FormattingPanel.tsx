import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Code2, FileCode2, RefreshCw, Wand2 } from "lucide-react";
import { api } from "../../../lib/api";
import { invalidateArticleData, useStageDetail } from "../../../hooks/useArticleQueries";
import { platformLabel } from "../../../lib/labels";
import { formatDate, toErrorMessage } from "../../../lib/utils";
import type { FormattedOutput } from "../../../types";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Skeleton } from "../../ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../ui/tabs";
import { EmptyState, ErrorState } from "../../common/States";
import { MarkdownPreview } from "../../markdown/MarkdownPreview";
import { SandboxedHtmlPreview } from "../../markdown/SandboxedHtmlPreview";
import { PanelShell, StageRunSummary } from "./shared";

interface FormattingPanelProps {
  articleId: string;
  platforms: string[];
}

function OutputPreview({ output }: { output: FormattedOutput }) {
  const isHtml = output.format === "html" || output.platform === "wechat";
  if (isHtml) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Code2 className="h-3 w-3" aria-hidden="true" />
          HTML 在 sandbox 隔离的 iframe 中渲染，脚本不会执行
        </div>
        <SandboxedHtmlPreview html={output.content} title={`${platformLabel(output.platform)} 预览`} />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
        <FileCode2 className="h-3 w-3" aria-hidden="true" />
        Markdown 预览
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <MarkdownPreview content={output.content} />
      </div>
    </div>
  );
}

export function FormattingPanel({ articleId, platforms }: FormattingPanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "formatting");
  const [active, setActive] = useState("");

  const outputs = stageQuery.data?.content.outputs ?? [];
  const currentValue =
    active && outputs.some((output) => output.platform === active)
      ? active
      : (outputs[0]?.platform ?? "");

  const formatMutation = useMutation({
    mutationFn: () => api.formatArticle(articleId, platforms.length > 0 ? platforms : undefined),
    onSuccess: () => invalidateArticleData(queryClient, articleId),
  });

  const retryMutation = useMutation({
    mutationFn: (platform: string) => api.retryFormat(articleId, platform),
    onSuccess: () => invalidateArticleData(queryClient, articleId),
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="分平台排版" description="各平台排版产物与预览">
        <Skeleton className="h-64 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const errors = formatMutation.data?.errors ?? {};
  const warnings = formatMutation.data?.warnings ?? [];

  return (
    <PanelShell
      title="分平台排版"
      description="为每个目标平台生成可发布产物。同一稿件版本复用配图；修改正文后重新选图。公众号 HTML 仅在沙箱 iframe 中预览。"
      actions={
        <Button
          variant="outline"
          onClick={() => formatMutation.mutate()}
          loading={formatMutation.isPending}
        >
          <Wand2 className="h-4 w-4" aria-hidden="true" />
          {outputs.length === 0 ? "生成排版" : "重新生成全部"}
        </Button>
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {formatMutation.data ? (
        <Alert variant={Object.keys(errors).length || warnings.length ? "warning" : "success"}>
          {Object.keys(errors).length
            ? `部分平台排版失败：${Object.entries(errors)
                .map(([platform, message]) => `${platformLabel(platform)}：${message}`)
                .join("；")}`
            : `排版完成，共 ${formatMutation.data.items.length} 个平台产物。`}
          {warnings.length ? ` ${warnings.join("；")}` : ""}
        </Alert>
      ) : null}
      {formatMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(formatMutation.error)}</Alert>
      ) : null}
      {retryMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(retryMutation.error)}</Alert>
      ) : null}

      {outputs.length === 0 ? (
        <EmptyState
          title="尚未生成排版产物"
          description="工作流进入排版阶段后会自动生成；也可以现在手动触发。"
          action={
            <Button onClick={() => formatMutation.mutate()} loading={formatMutation.isPending}>
              <Wand2 className="h-4 w-4" aria-hidden="true" />
              立即生成
            </Button>
          }
        />
      ) : (
        <Tabs value={currentValue} onValueChange={setActive}>
          <TabsList className="w-full justify-start overflow-x-auto">
            {outputs.map((output) => (
              <TabsTrigger key={output.platform} value={output.platform}>
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className={
                      output.status === "ready"
                        ? "h-1.5 w-1.5 rounded-full bg-emerald-500"
                        : output.status === "failed"
                          ? "h-1.5 w-1.5 rounded-full bg-red-500"
                          : "h-1.5 w-1.5 rounded-full bg-slate-400"
                    }
                    aria-hidden="true"
                  />
                  {platformLabel(output.platform)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          {outputs.map((output) => (
            <TabsContent key={output.platform} value={output.platform}>
              <Card>
                <CardHeader className="gap-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <CardTitle className="text-base">{output.title || platformLabel(output.platform)}</CardTitle>
                      <p className="mt-1 text-xs text-slate-400">
                        更新于 {formatDate(output.updated_at)} · 格式 {output.format}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={output.status === "ready" ? "success" : "destructive"}>
                        {output.status === "ready" ? "可发布" : output.status}
                      </Badge>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => retryMutation.mutate(output.platform)}
                        loading={
                          retryMutation.isPending && retryMutation.variables === output.platform
                        }
                      >
                        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                        重试排版
                      </Button>
                    </div>
                  </div>
                  {output.summary ? <p className="text-sm text-slate-500">{output.summary}</p> : null}
                  <div className="flex flex-wrap gap-1.5">
                    {output.tags.map((tag) => (
                      <Badge key={tag} variant="outline">
                        #{tag}
                      </Badge>
                    ))}
                  </div>
                  {output.error ? <Alert variant="destructive">{output.error}</Alert> : null}
                  {output.warning ? <Alert variant="warning">{output.warning}</Alert> : null}
                </CardHeader>
                <CardContent>
                  <OutputPreview output={output} />
                </CardContent>
              </Card>
            </TabsContent>
          ))}
        </Tabs>
      )}
    </PanelShell>
  );
}
