# Design

## Context

现有审核链路：`review` 节点调用 `ReviewService` 写入 `ReviewReport`，`route_after_review` 直接决定排版或回退；
`auto_review_advance` 关闭时复用通用 `pause` 节点暂停。通用 `pause` 只接受“继续”，无法承载通过/驳回与意见。
审核阈值来自进程配置 `Settings.review_pass_threshold`，设置页写入的 `settings.review_pass_threshold` 实际未生效。
返工提示词依赖 `latest_failed_issues()`，只有自动审核问题，没有人工意见入口。详见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 让自动审核的实际判定与设置页一致，并降低“个别小问题即整体失败”的误杀率。
- 用一个独立的人工决策节点承载通过/驳回，避免在 stage 节点内 `interrupt` 导致重跑整段审核。
- 让驳回意见成为该次运行后续研究、大纲、写作上下文的一部分。

**Non-Goals:**

- 不改变排版、发布与发布确认流程。
- 不新增多轮人工协作/评论线程；每次审稿只接受一次通过或驳回。
- 不调整自动返工上限的配置来源（仍使用运行启动时的 `max_revisions`）。

## Decisions

### 1. 新增 `review_decision` 节点，而不是复用 `pause`

`pause` 节点只携带 `next_node`，恢复值被忽略，无法按通过/驳回分流。新增节点在 `interrupt` 前将运行置为
`waiting_review`，恢复后读取结构化决策并返回 `review_human_decision`；图新增条件边路由到 `format`
或研究/大纲/写作之一。这样中断恢复时只重放少量状态更新，不会重新执行审核 LLM 调用。

- 备选：在 `review` 节点内部 `interrupt`。LangGraph 会从头重放节点，可能重复调用审核模型，放弃。
- 备选：让 API 直接改写运行状态再恢复 `pause`。状态路由依赖 checkpoint 中的 `next_node`，跨进程不可靠，放弃。

### 2. 新增运行/文章状态 `waiting_review`

`RunStatus`、`ArticleStatus` 增加 `waiting_review`；加入 `ACTIVE_STATUSES`，避免等待期间被重复启动。
`resume_run` 对 `waiting_review` 接受 `approve` / `reject` 决策，并校验驳回意见非空。
前端 `StatusBadge`、标签与活动状态列表同步，`ArticleDetailPage` 不再对 `waiting_review` 显示通用“继续运行”。

### 3. 人工决策落库

新增 `ReviewDecision` 表：`article_id`、`run_id`、`report_id`、`decision`（approved/rejected）、`feedback`、
`rollback_to`、`target_reason`、`created_at`。审稿阶段内容额外返回 `latest_decision`，供面板展示最近一次人工决策。
驳回意见的“生效范围”通过图状态携带，而不是全局缓存：`review_decision` 返回 `human_feedback`，后续节点将其传入
研究/大纲/写作服务；新运行没有该状态，历史意见自然不会串入。

### 4. 驳回意图识别

新增 `review_rejection.md` 与 `RejectionRoute` 结构化输出（`rollback_to`: research|outline|writing、`reason`）。
输入包含驳回意见、最近审核报告摘要与文章标题。LLM 失败或返回非法值时使用关键词兜底：
资料/数据/引用/来源/事实 → 研究；结构/大纲/章节/逻辑 → 大纲；其余 → 写作。

### 5. 意见注入与整篇重写

`ResearchService`、`OutlineService`、`WritingService` 增加可选 `feedback`，并向对应提示词追加
“人工驳回意见（必须落实）”段落；`DeepResearchRunner` 同样把意见加入研究任务。节点从图状态读取
`human_feedback` 传入。
写作节点在 `human_rejection` 为真时调用整篇 `revise()`，不再走 `revise_targeted()`；大纲节点在回退目标为大纲时
用驳回意见构造修订问题；研究回退直接重新检索，后续大纲/写作生成仍携带意见。

### 6. 审核放宽策略

- 阈值：`ReviewService` 优先读取 `settings` 表中的 `review_pass_threshold`，缺失/非法时回退配置。
- 容差：`total >= threshold - 5` 且无 blocking、无 critical/major 时判 pass。
- 闸门：有有效引用时，少量无效引用记 major 并压分，不阻断；无有效引用或无效占比 > 50% 阻断。
  标题超限/标题党阻断；标题过短记 major 不阻断。
- 维度名规范化：建立中英文别名映射，统一小写；未识别维度不得覆盖已识别维度。
- 提示词：给出评分区间（80+ 优秀、70–79 合格、<70 需返工）、severity 边界，要求可优化项写入 suggestions。

## Risks / Trade-offs

- [人工通过自动未通过的稿子] → 审核报告仍保留 fail 结论与问题，决策记录写明人工放行，发布确认摘要仍显示质量信息。
- [意图识别错误] → 返回 `target_reason` 暴露判断依据；命中不明确时回退写作，用户可再次驳回并补充意见。
- [驳回后自动审核再次失败] → 开关关闭时仍回到人工闸门，不会陷入无人值守循环；开关开启时遵循原有返工上限。
- [旧数据] → 新表与状态为增量，旧运行继续按原状态恢复；状态标签对未知值保持现有兜底。
- [放宽闸门导致低质通过] → 只放宽“少量无效引用/标题过短/接近阈值”，完全无引用与平台硬限制仍阻断。

## Migration Plan

1. Alembic 新增 `review_decisions` 表（无数据回填）。
2. 前端/后端同时发布；旧客户端不调用新端点不受影响。
3. 回滚：删除新节点路由与新端点即可恢复旧行为；新表保留不影响旧代码。
