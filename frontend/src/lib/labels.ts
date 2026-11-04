import type {
  ArticleStatus,
  RunStatus,
  StageKey,
  StageStatus,
  SuggestionStatus,
} from "../types";

export const STAGE_KEYS: StageKey[] = [
  "topic_selection",
  "research",
  "outline",
  "writing",
  "title_optimization",
  "review",
  "formatting",
  "publishing",
];

export const STAGE_LABELS: Record<StageKey, string> = {
  topic_selection: "选题",
  research: "资料搜索",
  outline: "大纲生成",
  writing: "写作",
  title_optimization: "标题优化",
  review: "审核",
  formatting: "分平台排版",
  publishing: "发布",
};

export const SKILL_STAGE_KEYS: StageKey[] = [
  "topic_selection",
  "research",
  "outline",
  "writing",
  "title_optimization",
  "review",
];

export const STAGE_DESCRIPTIONS: Record<StageKey, string> = {
  topic_selection: "选择或推荐文章主题",
  research: "来源、事实与可信度",
  outline: "文章结构与章节要点",
  writing: "正文、版本与生成元数据",
  title_optimization: "候选标题、评分与最终选定",
  review: "五维质量评分与回退建议",
  formatting: "各平台排版产物与预览",
  publishing: "确认发布、状态与手动回填",
};

export const ARTICLE_STATUS_LABELS: Record<ArticleStatus, string> = {
  draft: "草稿",
  running: "运行中",
  paused: "已暂停",
  waiting_topic: "待选题",
  waiting_review: "待审稿确认",
  waiting_publish: "待确认发布",
  published: "已发布",
  needs_human: "需人工处理",
  failed: "失败",
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  pending: "等待开始",
  running: "运行中",
  paused: "已暂停",
  waiting_review: "待审稿确认",
  waiting_publish: "待确认发布",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  cancelled: "已取消",
  needs_human: "需人工处理",
};

export const STAGE_STATUS_LABELS: Record<StageStatus | "warning", string> = {
  pending: "未开始",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
  skipped: "已跳过",
  warning: "待确认",
};

export const PUBLISH_STATUS_LABELS: Record<string, string> = {
  pending: "未发布",
  draft: "已同步至公众号草稿箱",
  waiting_confirm: "待确认",
  publishing: "发布中",
  published: "已发布",
  failed: "失败",
  manual_required: "需手动发布",
  unavailable: "不可用",
  offline: "已下线",
};

export const SUGGESTION_STATUS_LABELS: Record<SuggestionStatus, string> = {
  pending: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
  applied: "已应用",
  rolled_back: "已回滚",
};

export const REVIEW_DIMENSION_LABELS: Record<string, string> = {
  fact: "事实准确",
  structure: "结构逻辑",
  readability: "可读性",
  compliance: "合规性",
  originality: "原创性",
};

export const REVIEW_DIMENSIONS = ["fact", "structure", "readability", "compliance", "originality"];

export const PLATFORM_LABELS: Record<string, string> = {
  wechat: "微信公众号",
  zhihu: "知乎",
  juejin: "掘金",
  csdn: "CSDN",
  mock: "Mock 演示平台",
};

export const DEFAULT_PLATFORMS = ["wechat", "zhihu", "juejin", "csdn"];

export const ACTIVE_RUN_STATUSES: RunStatus[] = [
  "pending",
  "running",
  "paused",
  "waiting_review",
  "waiting_publish",
  "needs_human",
];

export function platformLabel(key: string): string {
  return PLATFORM_LABELS[key] ?? key;
}

export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "—";
  return STAGE_LABELS[stage as StageKey] ?? stage;
}
