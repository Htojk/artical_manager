export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type ArticleStatus =
  | "draft"
  | "running"
  | "paused"
  | "waiting_topic"
  | "waiting_review"
  | "waiting_publish"
  | "published"
  | "needs_human"
  | "failed";

export type RunStatus =
  | "pending"
  | "running"
  | "paused"
  | "waiting_review"
  | "waiting_publish"
  | "completed"
  | "failed"
  | "interrupted"
  | "cancelled"
  | "needs_human";

export type StageKey =
  | "topic_selection"
  | "research"
  | "outline"
  | "writing"
  | "title_optimization"
  | "review"
  | "formatting"
  | "publishing";

export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export type PublishStatus =
  | "pending"
  | "waiting_confirm"
  | "publishing"
  | "published"
  | "failed"
  | "manual_required"
  | "unavailable"
  | "offline";

export type SuggestionStatus = "pending" | "approved" | "rejected" | "applied" | "rolled_back";

export interface Article {
  id: string;
  title: string;
  status: ArticleStatus;
  current_stage: string | null;
  topic_mode: "manual" | "ai" | string;
  target_platforms: string[];
  publish_confirmation: boolean | null;
  current_topic_id: string | null;
  current_outline_version: number | null;
  current_draft_version: number | null;
  current_title_version: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface HotSignal {
  index?: number;
  title?: string;
  source?: string;
  url?: string | null;
  published_at?: string | null;
  heat?: number | null;
  [key: string]: JsonValue | undefined;
}

export interface Topic {
  id: string;
  article_id: string;
  source: string;
  title: string;
  angle: string;
  rationale: string;
  target_platforms: string[];
  hot_signals: HotSignal[];
  discussion_score: number;
  discussion_reason: string;
  entertainment_score: number;
  entertainment_reason: string;
  entertainment_scores: Record<string, number>;
  content_format: string;
  selected: boolean;
  created_at: string;
}

export interface WorkflowRun {
  id: string;
  article_id: string;
  thread_id: string;
  status: RunStatus;
  current_stage: string | null;
  revision_count: number;
  max_revisions: number;
  pause_requested: boolean;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface StageRun {
  id: string;
  run_id: string;
  stage: StageKey;
  attempt: number;
  status: StageStatus;
  started_at: string | null;
  finished_at: string | null;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost: number | null;
  error: string | null;
}

export interface StageArtifactSummary {
  count?: number;
  sources?: boolean;
  facts?: boolean;
  version?: number | null;
  word_count?: number;
  verdict?: string | null;
  total?: number | null;
  platforms?: string[];
  ready?: string[];
  published?: string[];
  [key: string]: JsonValue | undefined;
}

export interface StageSummary {
  stage: StageKey;
  label: string;
  status: StageStatus;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  artifact: StageArtifactSummary;
}

export interface StageTimeline {
  article: Pick<Article, "id" | "status" | "current_stage">;
  run: WorkflowRun | null;
  stages: StageSummary[];
}

export interface Source {
  id: string;
  title: string;
  url: string;
  snippet: string;
  published_at: string | null;
  fetched_at: string | null;
  credibility: string | null;
  credibility_reason: string | null;
  added_by: string;
}

export interface Fact {
  id: string;
  source_id: string | null;
  statement: string;
  status: string;
  created_at: string | null;
}

export interface OutlineSection {
  heading: string;
  key_points: string[];
  source_refs: number[];
  image_hint: string;
}

export interface OutlineContent {
  title: string;
  hook: string;
  sections: OutlineSection[];
  target_words: number;
  summary: string;
  tags: string[];
}

export interface OutlineVersion {
  id: string;
  version: number;
  content: OutlineContent;
  created_by: string;
  note: string;
  created_at: string | null;
}

export interface DraftVersion {
  id: string;
  version: number;
  content_md: string;
  summary: string;
  word_count: number;
  model: string | null;
  skill_snapshot: JsonValue[];
  citation_report: JsonValue[];
  prompt_tokens: number;
  completion_tokens: number;
  duration_ms?: number;
  created_by: string;
  note: string;
  created_at: string | null;
}

export interface TitleCandidate {
  title: string;
  style: string;
  rationale: string;
  score: number;
}

export interface TitleVersion {
  id: string;
  version: number;
  candidates: TitleCandidate[];
  selected_title: string;
  strategy: string;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  duration_ms: number;
  created_by: string;
  note: string;
  created_at: string | null;
}

export interface ReviewIssue {
  location?: string;
  description: string;
  severity?: string;
}

export interface ReviewDimensionScore {
  score: number;
  issues: ReviewIssue[];
  suggestions: string[];
}

export interface ReviewReport {
  id: string;
  draft_version_id: string;
  scores: Record<string, ReviewDimensionScore>;
  total: number;
  verdict: "pass" | "fail" | string;
  rollback_to: string | null;
  rationale: string;
  model: string | null;
  config_version: string;
  created_at: string | null;
}

export interface FormattedOutput {
  id: string;
  platform: string;
  title: string;
  summary: string;
  tags: string[];
  content: string;
  format: string;
  status: string;
  error: string | null;
  warning: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MetricSnapshot {
  id: string;
  publish_record_id: string;
  platform: string;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  revenue_cents: number;
  revenue_yuan: number;
  source: string;
  captured_at: string | null;
}

export interface PublishHistoryItem {
  id: string;
  status: string;
  source: string;
  created_at: string | null;
  platform?: string | null;
}

export interface PublishRecord {
  id: string;
  article_id: string;
  platform: string;
  formatted_output_id: string | null;
  status: PublishStatus | string;
  remote_id: string | null;
  url: string | null;
  published_at: string | null;
  error: string | null;
  attempt: number;
  created_at: string | null;
  updated_at: string | null;
  latest_metric?: MetricSnapshot | null;
  history?: PublishHistoryItem[];
}

export interface TopicStageContent {
  selected: Topic | null;
  topics: Topic[];
}

export interface ResearchStageContent {
  sources: Source[];
  facts: Fact[];
}

export interface OutlineStageContent {
  latest: OutlineVersion | null;
  history: OutlineVersion[];
}

export interface WritingStageContent {
  latest: DraftVersion | null;
  history: DraftVersion[];
}

export interface TitleStageContent {
  latest: TitleVersion | null;
  history: TitleVersion[];
}

export interface ReviewDecision {
  id: string;
  article_id: string;
  run_id: string;
  report_id: string | null;
  decision: "approved" | "rejected" | string;
  feedback: string;
  rollback_to: string | null;
  target_reason: string;
  created_at: string | null;
}

export interface ReviewStageContent {
  latest: ReviewReport | null;
  history: ReviewReport[];
  latest_decision?: ReviewDecision | null;
}

export interface FormattingStageContent {
  outputs: FormattedOutput[];
}

export interface PublishingStageContent {
  records: PublishRecord[];
}

export interface StageContentByKey {
  topic_selection: TopicStageContent;
  research: ResearchStageContent;
  outline: OutlineStageContent;
  writing: WritingStageContent;
  title_optimization: TitleStageContent;
  review: ReviewStageContent;
  formatting: FormattingStageContent;
  publishing: PublishingStageContent;
}

export interface StageDetail<K extends StageKey = StageKey> {
  stage: K;
  label: string;
  stage_run: StageRun | null;
  content: StageContentByKey[K];
}

export interface ArticleDetailResponse {
  article: Article;
  topics: Topic[];
}

export interface ListResponse<T> {
  items: T[];
  total?: number;
}

export interface TopicRecommendationResponse extends ListResponse<Topic> {
  fallback_used: boolean;
  hot_signal_count: number;
  hot_errors: string[];
}

export interface SourceFetchResult {
  ok: boolean;
  source_id: string | null;
  title: string;
  error: string | null;
  reason: string | null;
}

export interface SelectTopicResponse {
  topic: Topic;
  article: Article;
  source_fetch: SourceFetchResult;
}

export interface ArticleCreatePayload {
  title: string;
  topic_mode: "manual" | "ai";
  target_platforms: string[];
  publish_confirmation: boolean;
  angle?: string;
}

export interface ConfirmSummaryItem {
  platform: string;
  display_name: string;
  title: string;
  artifact_ready: boolean;
  available: boolean;
  mode: string;
  reason: string;
}

export interface ConfirmSummary {
  article_id: string;
  title: string;
  platforms: ConfirmSummaryItem[];
}

export interface PublishResponse {
  items: PublishRecord[];
  errors: Record<string, string>;
  skipped?: string[];
}

export interface FormatResponse {
  items: FormattedOutput[];
  errors: Record<string, string>;
  warnings?: string[];
}

export interface AnalyticsPlatformMetrics {
  views: number;
  likes: number;
  comments: number;
  shares: number;
  revenue_cents: number;
  captured_at: string;
}

export interface AnalyticsMetrics {
  views: number;
  likes: number;
  comments: number;
  shares: number;
  revenue_cents: number;
  revenue_yuan: number;
  by_platform: Record<string, AnalyticsPlatformMetrics>;
}

export interface AnalyticsSummary {
  articles: number;
  published_articles: number;
  total_cost: number;
  prompt_tokens: number;
  completion_tokens: number;
  metrics: AnalyticsMetrics;
  revenue_yuan: number;
  roi: number | null;
}

export interface PerformanceRow {
  article_id: string;
  title: string;
  status: ArticleStatus;
  views: number;
  revenue_yuan: number;
  cost: number;
  roi: number | null;
}

export interface SkillSummary {
  id: string;
  slug: string;
  name: string;
  version: string;
  description: string;
  applies_to: string[];
  enabled: boolean;
  source_path: string;
  status: string;
  error: string | null;
  updated_at: string | null;
}

export interface SkillVersion {
  id: string;
  version: string;
  note: string;
  created_at: string;
}

export interface SkillResource {
  path: string;
  size: number;
}

export interface SkillDetail extends SkillSummary {
  standard_name: string;
  resources: SkillResource[];
  entry: string;
  license: string;
  compatibility: string;
  allowed_tools: string[];
  content: string | null;
  versions: SkillVersion[];
}

export interface SkillCreatePayload {
  slug: string;
  description: string;
  display_name?: string;
  content?: string;
  version?: string;
  applies_to?: string[];
}

export interface SkillImportResult extends SkillDetail {
  imported_files: number;
  source_filename: string;
}

export interface SkillBinding {
  id: string;
  stage: string;
  skill_id: string;
  order: number;
  enabled: boolean;
  skill: SkillSummary | null;
}

export interface ModelProfile {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  api_key_env: string;
  model: string;
  input_price_per_1k: number | null;
  output_price_per_1k: number | null;
  currency: string;
  context_window: number;
  enabled: boolean;
  updated_at: string | null;
}

export interface ModelCreatePayload {
  name: string;
  provider: string;
  base_url: string;
  api_key_env: string;
  model: string;
  input_price_per_1k: number | null;
  output_price_per_1k: number | null;
  currency: string;
  context_window: number;
  enabled: boolean;
}

export interface ModelBinding {
  id: string;
  stage: StageKey;
  model_profile_id: string;
  temperature: number;
  max_tokens: number;
  profile: ModelProfile | null;
  updated_at: string | null;
}

export interface PlatformCapabilities {
  format: boolean;
  publish: boolean;
  metrics: boolean;
  official_api: boolean;
}

export interface PlatformInfo {
  key: string;
  display_name: string;
  capabilities: PlatformCapabilities;
  available: boolean;
  mode: string;
  reason: string;
  has_credentials: boolean;
}

export type CredentialValue = string | number | boolean | null;
export type MaskedCredentials = Record<string, CredentialValue>;

export interface CredentialResponse {
  platform: string;
  masked: MaskedCredentials;
}

export interface SettingItem {
  key: string;
  value: JsonValue;
  updated_at?: string | null;
}

export interface ConnectivityItem {
  key: string;
  group: "feed" | "search" | "media" | "model" | "platform";
  name: string;
  target: string;
  status: "ok" | "failed" | "skipped";
  message: string;
  latency_ms: number;
}

export interface ConnectivityReport {
  checked_at: string | null;
  status: "not_checked" | "ok" | "degraded";
  summary: { ok: number; failed: number; skipped: number };
  items: ConnectivityItem[];
}

export interface EvolutionSuggestion {
  id: string;
  type: string;
  target_stage: string;
  title: string;
  rationale: string;
  evidence: JsonValue[];
  patch: JsonValue;
  expected_impact: string;
  status: SuggestionStatus;
  before_snapshot: JsonValue;
  after_snapshot: JsonValue;
  baseline: JsonValue;
  result: JsonValue;
  decided_note: string | null;
  created_at: string | null;
  decided_at: string | null;
  applied_at: string | null;
}

export interface ApiErrorBody {
  code?: string;
  message?: string;
  details?: JsonValue;
}

export interface AppEvent {
  type: string;
  article_id?: string | null;
  run_id?: string | null;
  data?: Record<string, unknown>;
  created_at?: string;
}
