import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileSearch, Plus, Quote, Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { invalidateArticleData, useStageDetail } from "../../../hooks/useArticleQueries";
import { formatDate, toErrorMessage } from "../../../lib/utils";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent } from "../../ui/card";
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
import { Skeleton } from "../../ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../ui/table";
import { Textarea } from "../../ui/textarea";
import { EmptyState, ErrorState } from "../../common/States";
import { PanelShell, SectionTitle, StageRunSummary } from "./shared";

interface ResearchPanelProps {
  articleId: string;
}

export function ResearchPanel({ articleId }: ResearchPanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "research");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [snippet, setSnippet] = useState("");

  const addMutation = useMutation({
    mutationFn: () =>
      api.addSource(articleId, {
        title: title.trim(),
        url: url.trim(),
        snippet: snippet.trim(),
      }),
    onSuccess: () => {
      setDialogOpen(false);
      setTitle("");
      setUrl("");
      setSnippet("");
      invalidateArticleData(queryClient, articleId);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (sourceId: string) => api.removeSource(articleId, sourceId),
    onSuccess: () => invalidateArticleData(queryClient, articleId),
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="资料搜索" description="来源、事实与可信度">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const sources = stageQuery.data?.content.sources ?? [];
  const facts = stageQuery.data?.content.facts ?? [];
  const sourceTitle = (sourceId: string | null) =>
    sources.find((source) => source.id === sourceId)?.title ?? "未关联来源";

  return (
    <PanelShell
      title="资料搜索"
      description="查看检索来源、事实要点与可信度。自动运行工作流时会在此阶段积累资料。"
      actions={
        <Button variant="outline" onClick={() => setDialogOpen(true)}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          添加来源
        </Button>
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />
      {removeMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(removeMutation.error)}</Alert>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <Card className="bg-gradient-to-br from-sky-50 to-white">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-sky-600">来源总数</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">{sources.length}</p>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-violet-50 to-white">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-violet-600">事实要点</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">{facts.length}</p>
          </CardContent>
        </Card>
      </div>

      <div>
        <SectionTitle action={<span className="text-xs text-slate-400">{sources.length} 条</span>}>
          <span className="inline-flex items-center gap-1.5">
            <FileSearch className="h-4 w-4 text-slate-400" aria-hidden="true" />
            来源列表
          </span>
        </SectionTitle>
        {sources.length === 0 ? (
          <EmptyState title="暂无来源" description="运行资料搜索阶段后，来源会自动出现在这里。" compact />
        ) : (
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>来源</TableHead>
                    <TableHead>可信度</TableHead>
                    <TableHead>抓取时间</TableHead>
                    <TableHead className="w-12 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sources.map((source) => (
                    <TableRow key={source.id}>
                      <TableCell className="max-w-xl whitespace-normal">
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 font-medium text-indigo-600 hover:underline"
                        >
                          {source.title}
                          <ExternalLink className="h-3 w-3" aria-hidden="true" />
                        </a>
                        {source.snippet ? (
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                            {source.snippet}
                          </p>
                        ) : null}
                        <p className="mt-1 text-[11px] text-slate-400">
                          {source.added_by === "user" ? "人工添加" : "Agent 检索"}
                        </p>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <Badge
                            variant={
                              source.credibility === "high"
                                ? "success"
                                : source.credibility === "medium"
                                  ? "warning"
                                  : source.credibility === "low"
                                    ? "destructive"
                                    : "secondary"
                            }
                          >
                            {source.credibility === "high"
                              ? "高可信"
                              : source.credibility === "medium"
                                ? "中可信"
                                : source.credibility === "low"
                                  ? "低可信"
                                  : "未评级"}
                          </Badge>
                          {source.credibility_reason ? (
                            <span className="max-w-44 text-[11px] leading-4 text-slate-400">
                              {source.credibility_reason}
                            </span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-slate-500">
                        {formatDate(source.fetched_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`删除来源 ${source.title}`}
                          loading={
                            removeMutation.isPending &&
                            removeMutation.variables === source.id
                          }
                          onClick={() => removeMutation.mutate(source.id)}
                        >
                          <Trash2 className="h-4 w-4 text-red-500" aria-hidden="true" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </div>

      <div>
        <SectionTitle>
          <span className="inline-flex items-center gap-1.5">
            <Quote className="h-4 w-4 text-slate-400" aria-hidden="true" />
            事实要点
          </span>
        </SectionTitle>
        {facts.length === 0 ? (
          <EmptyState title="暂无事实要点" description="搜集中提取的事实将用于写作引用。" compact />
        ) : (
          <div className="grid gap-2">
            {facts.map((fact) => (
              <div
                key={fact.id}
                className="flex flex-col gap-1 rounded-xl border border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-start sm:justify-between"
              >
                <p className="text-sm leading-6 text-slate-700">{fact.statement}</p>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant={fact.status === "verified" ? "success" : "secondary"}>
                    {fact.status === "verified" ? "已验证" : "待核验"}
                  </Badge>
                  <span className="text-[11px] text-slate-400">{sourceTitle(fact.source_id)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen} labelledBy="add-source-title">
        <DialogHeader>
          <DialogTitle id="add-source-title">添加来源</DialogTitle>
          <DialogDescription>
            手动录入可引用的来源，保存后立即出现在来源列表并参与后续检索去重。
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (title.trim() && url.trim()) addMutation.mutate();
          }}
        >
          <DialogContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="source-title">标题</Label>
              <Input
                id="source-title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="source-url">链接</Label>
              <Input
                id="source-url"
                type="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="source-snippet">摘录</Label>
              <Textarea
                id="source-snippet"
                value={snippet}
                onChange={(event) => setSnippet(event.target.value)}
                rows={3}
              />
            </div>
            {addMutation.error ? (
              <Alert variant="destructive">{toErrorMessage(addMutation.error)}</Alert>
            ) : null}
          </DialogContent>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button
              type="submit"
              loading={addMutation.isPending}
              disabled={!title.trim() || !url.trim()}
            >
              保存来源
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </PanelShell>
  );
}
