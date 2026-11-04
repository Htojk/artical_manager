import type {
  AnalyticsSummary,
  ApiErrorBody,
  Article,
  ArticleCreatePayload,
  ArticleDetailResponse,
  ConfirmSummary,
  ConnectivityReport,
  CredentialResponse,
  EvolutionSuggestion,
  FormatResponse,
  FormattedOutput,
  JsonValue,
  ListResponse,
  MaskedCredentials,
  ModelBinding,
  ModelCreatePayload,
  ModelProfile,
  OutlineContent,
  OutlineVersion,
  PerformanceRow,
  PlatformInfo,
  PublishRecord,
  PublishResponse,
  SelectTopicResponse,
  SettingItem,
  SkillBinding,
  Source,
  SkillCreatePayload,
  SkillDetail,
  SkillImportResult,
  SkillSummary,
  StageDetail,
  StageKey,
  StageTimeline,
  TitleVersion,
  Topic,
  TopicRecommendationResponse,
  WorkflowRun,
} from "../types";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: JsonValue | undefined;

  constructor(status: number, message: string, code = "http_error", details?: JsonValue) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type QueryValue = string | number | boolean | null | undefined;

interface RequestOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
  body?: BodyInit | null;
}

function queryString(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const result = search.toString();
  return result ? `?${result}` : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, headers, body, ...rest } = options;
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Accept", "application/json");
  if (json !== undefined) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: requestHeaders,
    body: json !== undefined ? JSON.stringify(json) : body,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const errorBody = isRecord(payload) ? (payload as ApiErrorBody) : undefined;
    const message =
      errorBody?.message ??
      (typeof payload === "string" && payload ? payload : `请求失败（HTTP ${response.status}）`);
    throw new ApiError(
      response.status,
      message,
      errorBody?.code ?? "http_error",
      errorBody?.details,
    );
  }

  return payload as T;
}

function stageDetailPath(articleId: string, stage: StageKey): string {
  return `/articles/${encodeURIComponent(articleId)}/stages/${stage}`;
}

export interface AnalyticsRange {
  from?: string;
  to?: string;
}

export const api = {
  listArticles(params: { status?: string; limit?: number; offset?: number } = {}) {
    return request<ListResponse<Article>>(`/articles${queryString(params)}`);
  },

  getArticle(articleId: string) {
    return request<ArticleDetailResponse>(`/articles/${encodeURIComponent(articleId)}`);
  },

  createArticle(payload: ArticleCreatePayload) {
    return request<ArticleDetailResponse>("/articles", { method: "POST", json: payload });
  },

  updateArticle(articleId: string, payload: Partial<ArticleCreatePayload>) {
    return request<Article>(`/articles/${encodeURIComponent(articleId)}`, {
      method: "PATCH",
      json: payload,
    });
  },

  deleteArticle(articleId: string) {
    return request<void>(`/articles/${encodeURIComponent(articleId)}`, { method: "DELETE" });
  },

  listTopics(articleId: string) {
    return request<ListResponse<Topic>>(`/articles/${encodeURIComponent(articleId)}/topics`);
  },

  createTopic(articleId: string, payload: { title: string; angle?: string; rationale?: string; content_format?: string }) {
    return request<Topic>(`/articles/${encodeURIComponent(articleId)}/topics`, {
      method: "POST",
      json: payload,
    });
  },

  recommendTopics(
    articleId: string,
    payload: { domain?: string; exclude_titles?: string[] } = {},
  ) {
    return request<TopicRecommendationResponse>(
      `/articles/${encodeURIComponent(articleId)}/topics/recommend`,
      { method: "POST", json: payload },
    );
  },

  selectTopic(articleId: string, topicId: string) {
    return request<SelectTopicResponse>(
      `/articles/${encodeURIComponent(articleId)}/topics/${encodeURIComponent(topicId)}/select`,
      { method: "POST" },
    );
  },

  addSource(
    articleId: string,
    payload: {
      title: string;
      url: string;
      snippet?: string;
      credibility?: "high" | "medium" | "low" | null;
    },
  ) {
    return request<Source>(`/articles/${encodeURIComponent(articleId)}/sources`, {
      method: "POST",
      json: payload,
    });
  },

  listSources(articleId: string) {
    return request<ListResponse<Source>>(
      `/articles/${encodeURIComponent(articleId)}/sources`,
    );
  },

  removeSource(articleId: string, sourceId: string) {
    return request<void>(
      `/articles/${encodeURIComponent(articleId)}/sources/${encodeURIComponent(sourceId)}`,
      { method: "DELETE" },
    );
  },

  startRun(articleId: string) {
    return request<WorkflowRun>(`/articles/${encodeURIComponent(articleId)}/run`, {
      method: "POST",
    });
  },

  listRuns(articleId: string) {
    return request<ListResponse<WorkflowRun>>(
      `/articles/${encodeURIComponent(articleId)}/runs`,
    );
  },

  pauseRun(runId: string) {
    return request<WorkflowRun>(`/runs/${encodeURIComponent(runId)}/pause`, { method: "POST" });
  },

  resumeRun(runId: string) {
    return request<WorkflowRun>(`/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
  },

  reviewDecision(
    articleId: string,
    payload: { decision: "approve" | "reject"; feedback?: string },
  ) {
    return request<WorkflowRun>(
      `/articles/${encodeURIComponent(articleId)}/review/decision`,
      { method: "POST", json: payload },
    );
  },

  confirmPublish(articleId: string, decision: "approve" | "cancel" = "approve") {
    return request<WorkflowRun>(
      `/articles/${encodeURIComponent(articleId)}/confirm-publish`,
      { method: "POST", json: { decision } },
    );
  },

  getStageTimeline(articleId: string) {
    return request<StageTimeline>(`/articles/${encodeURIComponent(articleId)}/stages`);
  },

  getStage<K extends StageKey>(articleId: string, stage: K) {
    return request<StageDetail<K>>(stageDetailPath(articleId, stage));
  },

  saveOutline(articleId: string, content: OutlineContent, note = "用户编辑") {
    return request<OutlineVersion>(`/articles/${encodeURIComponent(articleId)}/stages/outline`, {
      method: "PUT",
      json: { content, note },
    });
  },

  saveDraft(
    articleId: string,
    payload: { content_md: string; summary?: string; title?: string | null },
  ) {
    return request<unknown>(`/articles/${encodeURIComponent(articleId)}/stages/writing`, {
      method: "PUT",
      json: payload,
    });
  },

  selectTitle(articleId: string, title: string, note = "用户选择") {
    return request<TitleVersion>(
      `/articles/${encodeURIComponent(articleId)}/stages/title_optimization`,
      { method: "PUT", json: { title, note } },
    );
  },

  listFormats(articleId: string) {
    return request<ListResponse<FormattedOutput>>(
      `/articles/${encodeURIComponent(articleId)}/formats`,
    );
  },

  formatArticle(articleId: string, platforms?: string[]) {
    return request<FormatResponse>(`/articles/${encodeURIComponent(articleId)}/formats`, {
      method: "POST",
      json: { platforms: platforms ?? null },
    });
  },

  retryFormat(articleId: string, platform: string) {
    return request<FormattedOutput>(
      `/articles/${encodeURIComponent(articleId)}/formats/${encodeURIComponent(platform)}/retry`,
      { method: "POST" },
    );
  },

  confirmSummary(articleId: string) {
    return request<ConfirmSummary>(
      `/articles/${encodeURIComponent(articleId)}/confirm-summary`,
    );
  },

  publishNow(articleId: string, platforms?: string[]) {
    return request<PublishResponse>(`/articles/${encodeURIComponent(articleId)}/publish`, {
      method: "POST",
      json: { platforms: platforms ?? null },
    });
  },

  retryPublish(articleId: string, platform: string) {
    return request<PublishResponse>(
      `/articles/${encodeURIComponent(articleId)}/publish/${encodeURIComponent(platform)}/retry`,
      { method: "POST" },
    );
  },

  manualPublish(
    articleId: string,
    platform: string,
    payload: { url: string; remote_id?: string | null; status?: "published" | "offline" | "failed" },
  ) {
    return request<PublishRecord>(
      `/articles/${encodeURIComponent(articleId)}/publish/${encodeURIComponent(platform)}/manual`,
      { method: "POST", json: payload },
    );
  },

  listPublishHistory(articleId: string) {
    return request<ListResponse<PublishRecord>>(
      `/articles/${encodeURIComponent(articleId)}/publish/records`,
    );
  },

  analyticsSummary(range: AnalyticsRange = {}) {
    return request<AnalyticsSummary>(
      `/analytics/summary${queryString({ from: range.from, to: range.to })}`,
    );
  },

  analyticsPerformance(range: AnalyticsRange = {}) {
    return request<ListResponse<PerformanceRow>>(
      `/analytics/performance${queryString({ from: range.from, to: range.to })}`,
    );
  },

  listSkills() {
    return request<ListResponse<SkillSummary>>("/skills");
  },

  getSkill(slug: string) {
    return request<SkillDetail>(`/skills/${encodeURIComponent(slug)}`);
  },

  createSkill(payload: SkillCreatePayload) {
    return request<SkillSummary>("/skills", { method: "POST", json: payload });
  },

  importSkill(file: File, slug = "") {
    const form = new FormData();
    form.append("file", file);
    if (slug.trim()) form.append("slug", slug.trim());
    return request<SkillImportResult>("/skills/import", {
      method: "POST",
      body: form,
    });
  },

  async exportSkill(slug: string) {
    const response = await fetch(
      `${API_BASE}/skills/${encodeURIComponent(slug)}/export`,
      { headers: { Accept: "application/zip" } },
    );
    if (!response.ok) {
      const text = await response.text();
      let message = `导出失败（HTTP ${response.status}）`;
      if (text) {
        try {
          message = (JSON.parse(text) as ApiErrorBody).message ?? message;
        } catch {
          message = text;
        }
      }
      throw new ApiError(response.status, message);
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = `${slug}.zip`;
    link.click();
    URL.revokeObjectURL(url);
  },

  deleteSkill(slug: string) {
    return request<void>(`/skills/${encodeURIComponent(slug)}`, { method: "DELETE" });
  },

  saveSkillContent(slug: string, content: string, note = "用户编辑") {
    return request<SkillSummary>(`/skills/${encodeURIComponent(slug)}/content`, {
      method: "PUT",
      json: { content, note },
    });
  },

  toggleSkill(slug: string, enabled: boolean) {
    return request<SkillSummary>(`/skills/${encodeURIComponent(slug)}/toggle`, {
      method: "POST",
      json: { enabled },
    });
  },

  listSkillBindings(stage?: string) {
    return request<ListResponse<SkillBinding>>(
      `/skill-bindings${queryString({ stage })}`,
    );
  },

  createSkillBinding(payload: { stage: string; slug: string; order?: number; enabled?: boolean }) {
    return request<SkillBinding>("/skill-bindings", { method: "POST", json: payload });
  },

  deleteSkillBinding(bindingId: string) {
    return request<void>(`/skill-bindings/${encodeURIComponent(bindingId)}`, {
      method: "DELETE",
    });
  },

  listModels() {
    return request<ListResponse<ModelProfile>>("/models");
  },

  createModel(payload: ModelCreatePayload) {
    return request<ModelProfile>("/models", { method: "POST", json: payload });
  },

  updateModel(modelId: string, payload: Partial<ModelCreatePayload>) {
    return request<ModelProfile>(`/models/${encodeURIComponent(modelId)}`, {
      method: "PATCH",
      json: payload,
    });
  },

  deleteModel(modelId: string) {
    return request<void>(`/models/${encodeURIComponent(modelId)}`, { method: "DELETE" });
  },

  listModelBindings() {
    return request<ListResponse<ModelBinding>>("/model-bindings");
  },

  saveModelBinding(
    stage: string,
    payload: { model_profile_id: string; temperature: number; max_tokens: number },
  ) {
    return request<ModelBinding>(`/model-bindings/${encodeURIComponent(stage)}`, {
      method: "PUT",
      json: payload,
    });
  },

  listPlatforms() {
    return request<ListResponse<PlatformInfo>>("/platforms");
  },

  setPlatformCredentials(platform: string, payload: Record<string, string>) {
    return request<CredentialResponse>(
      `/platforms/${encodeURIComponent(platform)}/credentials`,
      { method: "PUT", json: { payload } },
    );
  },

  deletePlatformCredentials(platform: string) {
    return request<void>(`/platforms/${encodeURIComponent(platform)}/credentials`, {
      method: "DELETE",
    });
  },

  listSettings() {
    return request<ListResponse<SettingItem>>("/settings");
  },

  getConnectivityReport() {
    return request<ConnectivityReport>("/health/connectivity");
  },

  runConnectivityCheck() {
    return request<ConnectivityReport>("/health/connectivity/check", { method: "POST" });
  },

  updateSetting(key: string, value: JsonValue) {
    return request<SettingItem>(`/settings/${encodeURIComponent(key)}`, {
      method: "PUT",
      json: { value },
    });
  },

  listSuggestions(status?: string) {
    return request<ListResponse<EvolutionSuggestion>>(
      `/evolution/suggestions${queryString({ status })}`,
    );
  },

  generateSuggestions() {
    return request<ListResponse<EvolutionSuggestion>>("/evolution/suggestions/generate", {
      method: "POST",
    });
  },

  approveSuggestion(suggestionId: string, note = "") {
    return request<EvolutionSuggestion>(
      `/evolution/suggestions/${encodeURIComponent(suggestionId)}/approve`,
      { method: "POST", json: { note } },
    );
  },

  rejectSuggestion(suggestionId: string, note = "") {
    return request<EvolutionSuggestion>(
      `/evolution/suggestions/${encodeURIComponent(suggestionId)}/reject`,
      { method: "POST", json: { note } },
    );
  },

  applySuggestion(suggestionId: string) {
    return request<EvolutionSuggestion>(
      `/evolution/suggestions/${encodeURIComponent(suggestionId)}/apply`,
      { method: "POST" },
    );
  },

  rollbackSuggestion(suggestionId: string) {
    return request<EvolutionSuggestion>(
      `/evolution/suggestions/${encodeURIComponent(suggestionId)}/rollback`,
      { method: "POST" },
    );
  },

  getMaskedCredentials(platform: string) {
    return request<{ platform: string; masked: MaskedCredentials }>(
      `/platforms/${encodeURIComponent(platform)}/credentials`,
    );
  },
};
