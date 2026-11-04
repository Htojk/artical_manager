# Proposal

## Why

自动审稿反复无法通过：审核阈值实际没有读取设置页保存的值，确定性闸门把单处无效引用或轻微标题问题直接判失败，
模型评分提示也偏严。与此同时，审核通过后只能继续或暂停，没有人工放行与带意见驳回的能力；驳回意见也无法
可靠地传导到研究、大纲和写作阶段。

## What Changes

- 放宽并校准自动审稿条件：
  - 审核阈值改为读取运行时设置 `review_pass_threshold`（缺失时回退环境默认值）。
  - 增加“接近阈值且无 critical/major 问题即通过”的容差。
  - 确定性闸门按严重度处理：存在有效引用时，个别无效引用降为 major 且不直接判失败；仅在完全无有效引用或
    无效引用占比过高时阻断。标题超限/标题党仍阻断，标题过短不再直接阻断。
  - 规范化模型返回的维度名称（英文/中文/大小写别名），避免整维被记 0 分。
  - 调整审核提示词：明确评分区间、problem severity 的判定边界，可优化项放入 suggestions 而非扣分。
- 新增人工审批闸门：当设置 `auto_review_advance` 关闭时，每次审稿结束（通过或未通过）都进入
  `waiting_review`，等待人工决策；开启时保持现有自动推进/自动回退行为。
- 审稿面板新增通过按钮、驳回意见输入框与驳回按钮：
  - 通过：跳过自动结论，直接进入排版。
  - 驳回：后端用 LLM 意图识别将意见路由到研究、大纲或写作阶段，并基于驳回意见重新生成。
  - 人工驳回不占用自动返工次数。
- 驳回意见持久化并在后续研究、大纲、写作提示词中持续生效；写作阶段采用整篇重写而不是局部修补。
- 新增审稿决策 API，并让运行状态、事件与前端状态标签支持 `waiting_review`。

## Capabilities

### New Capabilities

- `article-generation/review`: 自动审稿的通过条件、人工审批闸门、驳回意图路由与驳回意见再生成。

### Modified Capabilities

<!-- 本次没有已存在的相关 capability 规范需要修改。 -->

## Impact

- 后端：`app/article_generation/review/*`、`quality.py`、`workflow/{graph,nodes,routing,runner,state}.py`、
  `core/constants.py`、`api/{runs,articles,schemas}.py`、`models/article.py`、`seed.py`、
  `prompts/{review,research,research_fallback,outline,outline_revision,writing,writing_revision,writing_targeted_revision}.md`、
  Alembic 迁移。
- 前端：`ReviewPanel.tsx`、`ArticleDetailPage.tsx`、`lib/api.ts`、`lib/labels.ts`、`types/index.ts`、相关测试。
- 数据库：新增人工审核决策记录表；审核报告增加产生方式字段（自动/人工）。
- 兼容性：`waiting_review` 是新运行状态；旧暂停/发布确认流程保持不变。
