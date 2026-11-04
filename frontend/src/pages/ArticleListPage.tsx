import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Coins,
  FileText,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { api } from "../lib/api";
import { queryKeys } from "../hooks/useArticleQueries";
import { ARTICLE_STATUS_LABELS, platformLabel, stageLabel } from "../lib/labels";
import { formatMoney, formatNumber, formatRelative, toErrorMessage } from "../lib/utils";
import type { Article, ArticleStatus, PerformanceRow } from "../types";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States";
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
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { CreateArticleDialog } from "../components/article/CreateArticleDialog";

const STATUS_OPTIONS: { value: "" | ArticleStatus; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "draft", label: "草稿" },
  { value: "running", label: "运行中" },
  { value: "waiting_publish", label: "待确认发布" },
  { value: "published", label: "已发布" },
  { value: "needs_human", label: "需人工处理" },
  { value: "failed", label: "失败" },
];

function StatCard({
  label,
  value,
  hint,
  icon,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  icon: ReactNode;
  tone: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 p-4">
        <span className={`rounded-lg p-2 ${tone}`}>{icon}</span>
        <div>
          <p className="text-xs font-medium text-slate-500">{label}</p>
          <p className="mt-0.5 text-2xl font-bold tabular-nums text-slate-900">{value}</p>
          <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ArticleListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Article | null>(null);
  const [status, setStatus] = useState<"" | ArticleStatus>("");
  const [search, setSearch] = useState("");

  const articlesQuery = useQuery({
    queryKey: queryKeys.articles({ status: status || undefined, limit: 200 }),
    queryFn: () => api.listArticles({ status: status || undefined, limit: 200 }),
  });

  const performanceQuery = useQuery({
    queryKey: ["analytics", "performance", "article-list"],
    queryFn: () => api.analyticsPerformance(),
    retry: false,
    staleTime: 30_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (articleId: string) => api.deleteArticle(articleId),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.articles() });
    },
  });

  const articles = articlesQuery.data?.items ?? [];
  const visibleArticles = search.trim()
    ? articles.filter((article) =>
        article.title.toLowerCase().includes(search.trim().toLowerCase()),
      )
    : articles;

  const costByArticle = new Map<string, number>(
    (performanceQuery.data?.items ?? []).map((row: PerformanceRow) => [row.article_id, row.cost]),
  );

  const running = articles.filter((article) => article.status === "running").length;
  const published = articles.filter((article) => article.status === "published").length;
  const totalCost = (performanceQuery.data?.items ?? []).reduce(
    (total, row) => total + row.cost,
    0,
  );

  const handleCreated = (article: Article, options: { aiMode: boolean; domain: string }) => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.articles() });
    if (options.aiMode) {
      const params = new URLSearchParams({
        stage: "topic_selection",
        recommend: "1",
      });
      if (options.domain) params.set("domain", options.domain);
      navigate(`/articles/${article.id}?${params.toString()}`);
    } else {
      navigate(`/articles/${article.id}`);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Workspace"
        title="文章工作台"
        description="从选题到发布，跟踪每篇文章的工作流状态，随时介入编辑、审核与发布。"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            新建文章
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="文章总数"
          value={formatNumber(articlesQuery.data?.total ?? articles.length)}
          hint="全部文章"
          icon={<FileText className="h-4 w-4 text-indigo-600" aria-hidden="true" />}
          tone="bg-indigo-50"
        />
        <StatCard
          label="运行中"
          value={formatNumber(running)}
          hint="正在生成的工作流"
          icon={<ArrowRight className="h-4 w-4 text-blue-600" aria-hidden="true" />}
          tone="bg-blue-50"
        />
        <StatCard
          label="已发布"
          value={formatNumber(published)}
          hint="至少一个平台已发布"
          icon={<CheckCircle2 className="h-4 w-4 text-emerald-600" aria-hidden="true" />}
          tone="bg-emerald-50"
        />
        <StatCard
          label="累计成本"
          value={formatMoney(totalCost)}
          hint="已记录的模型调用成本"
          icon={<Coins className="h-4 w-4 text-amber-600" aria-hidden="true" />}
          tone="bg-amber-50"
        />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full sm:max-w-sm">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                aria-hidden="true"
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="搜索文章标题…"
                className="pl-9"
                aria-label="搜索文章标题"
              />
            </div>
            <div className="w-full sm:w-44">
              <Select
                value={status}
                onChange={(event) => setStatus(event.target.value as "" | ArticleStatus)}
                aria-label="按状态筛选"
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option.value || "all"} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {articlesQuery.isLoading ? <LoadingState label="正在加载文章…" /> : null}
          {articlesQuery.isError ? (
            <ErrorState
              message={toErrorMessage(articlesQuery.error)}
              onRetry={() => void articlesQuery.refetch()}
            />
          ) : null}
          {deleteMutation.error ? (
            <div className="mb-3">
              <Alert variant="destructive">{toErrorMessage(deleteMutation.error)}</Alert>
            </div>
          ) : null}

          {!articlesQuery.isLoading && !articlesQuery.isError && visibleArticles.length === 0 ? (
            <EmptyState
              title={search || status ? "没有匹配的文章" : "还没有文章"}
              description={
                search || status
                  ? "调整筛选条件，或新建一篇文章开始。"
                  : "创建手动主题，或让 AI 为你推荐 5 个候选选题。"
              }
              action={
                <Button onClick={() => setCreateOpen(true)}>
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  新建文章
                </Button>
              }
            />
          ) : null}

          {visibleArticles.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文章</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>当前阶段</TableHead>
                  <TableHead>目标平台</TableHead>
                  <TableHead className="text-right">成本</TableHead>
                  <TableHead>更新时间</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleArticles.map((article) => (
                  <TableRow key={article.id}>
                    <TableCell className="max-w-md">
                      <Link
                        to={`/articles/${article.id}`}
                        className="font-medium text-slate-800 hover:text-indigo-700 hover:underline"
                      >
                        {article.title || "未命名选题"}
                      </Link>
                      <p className="mt-0.5 text-[11px] text-slate-400">
                        {article.topic_mode === "ai" ? "AI 选题" : "手动主题"} ·{" "}
                        {article.id.slice(0, 8)}
                      </p>
                    </TableCell>
                    <TableCell>
                      <StatusBadge kind="article" status={article.status} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-slate-500">
                      {stageLabel(article.current_stage)}
                    </TableCell>
                    <TableCell>
                      <div className="flex max-w-56 flex-wrap gap-1">
                        {article.target_platforms.length === 0 ? (
                          <span className="text-xs text-slate-400">默认</span>
                        ) : (
                          article.target_platforms.slice(0, 3).map((platform) => (
                            <Badge key={platform} variant="outline">
                              {platformLabel(platform)}
                            </Badge>
                          ))
                        )}
                        {article.target_platforms.length > 3 ? (
                          <Badge variant="secondary">+{article.target_platforms.length - 3}</Badge>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap text-xs text-slate-500">
                      {formatMoney(costByArticle.get(article.id) ?? 0)}
                    </TableCell>
                    <TableCell
                      className="whitespace-nowrap text-xs text-slate-500"
                      title={article.updated_at}
                    >
                      {formatRelative(article.updated_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => navigate(`/articles/${article.id}`)}
                        >
                          打开
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`删除文章：${article.title || "未命名选题"}`}
                          onClick={() => setDeleteTarget(article)}
                          className="text-slate-400 hover:bg-red-50 hover:text-red-600"
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
        </CardContent>
      </Card>

      <CreateArticleDialog open={createOpen} onOpenChange={setCreateOpen} onCreated={handleCreated} />

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
            deleteMutation.reset();
          }
        }}
        labelledBy="delete-article-title"
      >
        <DialogHeader>
          <DialogTitle id="delete-article-title">删除文章</DialogTitle>
          <DialogDescription>
            确定删除「{deleteTarget?.title || "未命名选题"}」吗？工作流产物与发布记录将一并移除，此操作不可撤销。
          </DialogDescription>
        </DialogHeader>
        <DialogContent>
          <Alert variant="warning">
            删除后不会保留历史版本。若只想停止生成，请回到详情页暂停工作流。
          </Alert>
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteTarget(null)}>
            取消
          </Button>
          <Button
            variant="destructive"
            loading={deleteMutation.isPending}
            onClick={() => {
              if (deleteTarget) deleteMutation.mutate(deleteTarget.id);
            }}
          >
            确认删除
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

export function articleStatusLabel(status: string): string {
  return ARTICLE_STATUS_LABELS[status as ArticleStatus] ?? status;
}
