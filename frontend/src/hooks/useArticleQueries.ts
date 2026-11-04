import { useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { StageKey } from "../types";

export const queryKeys = {
  articles: (params?: Record<string, unknown>) => ["articles", params ?? {}] as const,
  article: (articleId: string) => ["article", articleId] as const,
  timeline: (articleId: string) => ["stages", articleId] as const,
  stage: (articleId: string, stage: StageKey) => ["stage", articleId, stage] as const,
  stageRoot: (articleId: string) => ["stage", articleId] as const,
  confirmSummary: (articleId: string) => ["confirm-summary", articleId] as const,
  skills: () => ["skills"] as const,
  skill: (slug: string) => ["skill", slug] as const,
  skillBindings: () => ["skill-bindings"] as const,
  models: () => ["models"] as const,
  modelBindings: () => ["model-bindings"] as const,
  platforms: () => ["platforms"] as const,
  platformCredentials: (platform: string) => ["platform-credentials", platform] as const,
  settings: () => ["settings"] as const,
  suggestions: (status?: string) => ["suggestions", status ?? "all"] as const,
  analyticsSummary: (range: string) => ["analytics", "summary", range] as const,
  analyticsPerformance: (range: string) => ["analytics", "performance", range] as const,
};

export function invalidateArticleData(queryClient: QueryClient, articleId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.article(articleId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.timeline(articleId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.stageRoot(articleId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.articles() });
}

export function useArticle(articleId: string, refetchInterval?: number | false) {
  return useQuery({
    queryKey: queryKeys.article(articleId),
    queryFn: () => api.getArticle(articleId),
    enabled: Boolean(articleId),
    refetchInterval,
  });
}

export function useStageTimeline(articleId: string, refetchInterval?: number | false) {
  return useQuery({
    queryKey: queryKeys.timeline(articleId),
    queryFn: () => api.getStageTimeline(articleId),
    enabled: Boolean(articleId),
    refetchInterval,
  });
}

export function useStageDetail<K extends StageKey>(articleId: string, stage: K) {
  return useQuery({
    queryKey: queryKeys.stage(articleId, stage),
    queryFn: () => api.getStage(articleId, stage),
    enabled: Boolean(articleId),
  });
}
