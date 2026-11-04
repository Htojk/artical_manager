import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  BookOpenCheck,
  CalendarRange,
  Coins,
  Eye,
  FileText,
  Gauge,
  TrendingUp,
} from "lucide-react";
import { api } from "../lib/api";
import { queryKeys } from "../hooks/useArticleQueries";
import { platformLabel } from "../lib/labels";
import {
  dateInputValue,
  formatMoney,
  formatNumber,
  formatRoi,
  isoEnd,
  isoStart,
  toErrorMessage,
} from "../lib/utils";
import type { AnalyticsSummary, PerformanceRow } from "../types";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

function KpiCard({
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
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-slate-500">{label}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">{value}</p>
            <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>
          </div>
          <span className={`rounded-lg p-2 ${tone}`}>{icon}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function platformChartData(summary: AnalyticsSummary | undefined) {
  if (!summary) return [];
  return Object.entries(summary.metrics.by_platform).map(([platform, metrics]) => ({
    name: platformLabel(platform),
    views: metrics.views,
    revenue: Math.round(metrics.revenue_cents) / 100,
  }));
}

function articleChartData(rows: PerformanceRow[]) {
  return [...rows]
    .sort((a, b) => b.views - a.views)
    .slice(0, 8)
    .map((row) => ({
      name: row.title.length > 10 ? `${row.title.slice(0, 10)}…` : row.title,
      views: row.views,
      revenue: row.revenue_yuan,
      cost: row.cost,
    }));
}

export function AnalyticsPage() {
  const today = new Date();
  const initialFrom = new Date();
  initialFrom.setDate(today.getDate() - 29);
  const [fromDate, setFromDate] = useState(dateInputValue(initialFrom));
  const [toDate, setToDate] = useState(dateInputValue(today));
  const [preset, setPreset] = useState<"7" | "30" | "90" | "custom">("30");

  const range = {
    from: fromDate ? isoStart(fromDate) : undefined,
    to: toDate ? isoEnd(toDate) : undefined,
  };
  const rangeKey = `${fromDate}_${toDate}`;
  const validRange = Boolean(fromDate && toDate && fromDate <= toDate);

  const summaryQuery = useQuery({
    queryKey: queryKeys.analyticsSummary(rangeKey),
    queryFn: () => api.analyticsSummary(range),
    enabled: validRange,
  });

  const performanceQuery = useQuery({
    queryKey: queryKeys.analyticsPerformance(rangeKey),
    queryFn: () => api.analyticsPerformance(range),
    enabled: validRange,
  });

  const applyPreset = (days: "7" | "30" | "90") => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (Number(days) - 1));
    setFromDate(dateInputValue(start));
    setToDate(dateInputValue(end));
    setPreset(days);
  };

  const summary = summaryQuery.data;
  const rows = performanceQuery.data?.items ?? [];
  const platformData = platformChartData(summary);
  const articleData = articleChartData(rows);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Operations"
        title="运维分析"
        description="按时间范围查看文章的发布量、阅读、收益、模型成本和 ROI。"
      />

      <Card>
        <CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <CalendarRange className="h-4 w-4 text-slate-400" aria-hidden="true" />
            {(
              [
                ["7", "最近 7 天"],
                ["30", "最近 30 天"],
                ["90", "最近 90 天"],
              ] as const
            ).map(([days, label]) => (
              <Button
                key={days}
                size="sm"
                variant={preset === days ? "default" : "outline"}
                onClick={() => applyPreset(days)}
              >
                {label}
              </Button>
            ))}
            {preset === "custom" ? <span className="text-xs text-slate-400">自定义范围</span> : null}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label htmlFor="analytics-from" className="text-xs">
                开始日期
              </Label>
              <Input
                id="analytics-from"
                type="date"
                value={fromDate}
                max={toDate}
                onChange={(event) => {
                  setFromDate(event.target.value);
                  setPreset("custom");
                }}
                className="w-40"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="analytics-to" className="text-xs">
                结束日期
              </Label>
              <Input
                id="analytics-to"
                type="date"
                value={toDate}
                min={fromDate}
                onChange={(event) => {
                  setToDate(event.target.value);
                  setPreset("custom");
                }}
                className="w-40"
              />
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                void summaryQuery.refetch();
                void performanceQuery.refetch();
              }}
              disabled={!validRange}
            >
              应用筛选
            </Button>
          </div>
        </CardContent>
      </Card>

      {!validRange ? <ErrorState compact message="开始日期不能晚于结束日期。" /> : null}
      {summaryQuery.isLoading ? <LoadingState label="正在汇总指标…" /> : null}
      {summaryQuery.isError ? (
        <ErrorState
          message={toErrorMessage(summaryQuery.error)}
          onRetry={() => void summaryQuery.refetch()}
        />
      ) : null}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-6">
        <KpiCard
          label="文章数"
          value={formatNumber(summary?.articles ?? 0)}
          hint="范围内全部文章"
          icon={<FileText className="h-4 w-4 text-indigo-600" aria-hidden="true" />}
          tone="bg-indigo-50"
        />
        <KpiCard
          label="已发布"
          value={formatNumber(summary?.published_articles ?? 0)}
          hint="发布状态文章"
          icon={<BookOpenCheck className="h-4 w-4 text-emerald-600" aria-hidden="true" />}
          tone="bg-emerald-50"
        />
        <KpiCard
          label="总阅读"
          value={formatNumber(summary?.metrics.views ?? 0)}
          hint="各平台最新快照"
          icon={<Eye className="h-4 w-4 text-sky-600" aria-hidden="true" />}
          tone="bg-sky-50"
        />
        <KpiCard
          label="总收益"
          value={formatMoney(summary?.revenue_yuan ?? 0)}
          hint="平台收益回填"
          icon={<TrendingUp className="h-4 w-4 text-emerald-600" aria-hidden="true" />}
          tone="bg-emerald-50"
        />
        <KpiCard
          label="模型成本"
          value={formatMoney(summary?.total_cost ?? 0)}
          hint={`${formatNumber(summary?.prompt_tokens ?? 0)} 输入 Token`}
          icon={<Coins className="h-4 w-4 text-amber-600" aria-hidden="true" />}
          tone="bg-amber-50"
        />
        <KpiCard
          label="ROI"
          value={formatRoi(summary?.roi)}
          hint="收益 ÷ 成本"
          icon={<Gauge className="h-4 w-4 text-violet-600" aria-hidden="true" />}
          tone="bg-violet-50"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle>平台阅读量</CardTitle>
          </CardHeader>
          <CardContent>
            {platformData.length === 0 ? (
              <EmptyState title="暂无平台指标" description="发布后抓取或回填指标即可看到对比。" compact />
            ) : (
              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={platformData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} />
                    <YAxis tick={{ fontSize: 11, fill: "#64748b" }} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="views" name="阅读量" fill="#6366f1" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle>文章阅读与收益</CardTitle>
          </CardHeader>
          <CardContent>
            {articleData.length === 0 ? (
              <EmptyState title="暂无文章表现" description="发布并采集指标后可查看文章对照。" compact />
            ) : (
              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={articleData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#64748b" }} />
                    <YAxis yAxisId="left" tick={{ fontSize: 11, fill: "#64748b" }} />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tick={{ fontSize: 11, fill: "#64748b" }}
                    />
                    <Tooltip />
                    <Legend />
                    <Bar
                      yAxisId="left"
                      dataKey="views"
                      name="阅读量"
                      fill="#0ea5e9"
                      radius={[4, 4, 0, 0]}
                    />
                    <Bar
                      yAxisId="right"
                      dataKey="revenue"
                      name="收益（元）"
                      fill="#10b981"
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle>文章表现对照</CardTitle>
        </CardHeader>
        <CardContent>
          {performanceQuery.isLoading ? <LoadingState label="正在加载文章表现…" /> : null}
          {performanceQuery.isError ? (
            <ErrorState
              message={toErrorMessage(performanceQuery.error)}
              onRetry={() => void performanceQuery.refetch()}
            />
          ) : null}
          {!performanceQuery.isLoading && !performanceQuery.isError && rows.length === 0 ? (
            <EmptyState title="暂无数据" description="该时间范围内没有文章表现记录。" compact />
          ) : null}
          {rows.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>文章</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">阅读</TableHead>
                  <TableHead className="text-right">收益</TableHead>
                  <TableHead className="text-right">成本</TableHead>
                  <TableHead className="text-right">ROI</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.article_id}>
                    <TableCell className="max-w-md font-medium text-slate-800">{row.title}</TableCell>
                    <TableCell>
                      <StatusBadge kind="article" status={row.status} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(row.views)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatMoney(row.revenue_yuan)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatMoney(row.cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatRoi(row.roi)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
