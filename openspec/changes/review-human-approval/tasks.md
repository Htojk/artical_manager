# Tasks

## 1. 放宽并校准自动审稿

- [x] 1.1 让 `ReviewService` 从 `settings` 表读取 `review_pass_threshold`（缺失/非法回退配置默认值），并加入“阈值减 5 分且无 blocking/critical/major 即通过”的容差；在 `tests/test_quality.py` 覆盖阈值生效、容差通过、有 major 不通过。
- [x] 1.2 调整确定性闸门：有有效引用时少量无效引用降为 major 不阻断，无有效引用或无效占比 >50% 阻断；标题超限/标题党阻断，标题过短不阻断；补充对应单元测试并通过。
- [x] 1.3 增加维度别名规范化（中英文、大小写）并防止未识别维度覆盖有效分数；补充 `_normalize` 单元测试。
- [x] 1.4 更新 `prompts/review.md` 的评分区间与 severity 边界说明，并运行审核相关测试确认提示词渲染正常。

## 2. 人工审核数据与状态

- [x] 2.1 新增 `ReviewDecision` ORM 模型与 Alembic 迁移，应用迁移后确认表存在。
- [x] 2.2 在 `RunStatus`、`ArticleStatus` 增加 `waiting_review`，同步 `runner.ACTIVE_STATUSES` 与前端状态标签/活动状态；运行后端与前端类型检查。
- [x] 2.3 在审稿阶段内容中返回最近一次人工决策（`latest_decision`），并在 `ReviewStageContent` 类型中补齐；通过阶段详情接口测试验证。

## 3. 人工审批流程

- [x] 3.1 新增 `review_decision` 图节点：进入时置 `waiting_review` 并 `interrupt`，恢复后按 approve/reject 返回状态；审核通过/失败且 `auto_review_advance` 关闭时都路由到该节点，开启时保持原自动行为；补充图路由单元测试。
- [x] 3.2 实现驳回收支：`review_rejection.md` + `RejectionRoute` 结构化输出，LLM 失败时用关键词兜底；写入 `ReviewDecision` 并重置下游阶段；补充意图路由测试（资料/结构/不明确）。
- [x] 3.3 扩展 `WorkflowRunner.resume_run` 与 `POST /api/articles/{article_id}/review/decision`，校验 `waiting_review` 状态、approve/reject 取值与驳回意见非空；补充 API 测试覆盖通过、驳回、空意见与非等待状态。
- [x] 3.4 人工通过后无论自动结论 pass/fail 都继续排版；人工驳回不增加自动返工次数；补充端到端测试验证两条路径。

## 4. 驳回意见驱动重新生成

- [x] 4.1 `ResearchService` 与 `DeepResearchRunner` 接收驳回意见并注入提示词/研究任务；补充研究提示词渲染测试。
- [x] 4.2 `OutlineService` 接收驳回意见并注入 `outline.md`、`outline_revision.md`；回退目标为大纲时用驳回意见构造修订问题；补充测试。
- [x] 4.3 `WritingService` 接收驳回意见并注入三个写作提示词；人工驳回时整篇 `revise()` 而非定向修订；补充测试验证意见出现在提示词且生成新版本。
- [x] 4.4 工作流节点把 `human_feedback` 传给研究/大纲/写作服务，并确认研究→大纲→写作全链路都携带意见；补充一次驳回后完整重跑测试。

## 5. 前端人工审批面板

- [x] 5.1 `api.ts`、`types` 增加审稿决策请求与 `latest_decision` 类型，补充 `waiting_review` 标签；运行类型检查。
- [x] 5.2 `ReviewPanel` 在 `waiting_review` 时显示通过按钮、驳回意见输入框与驳回按钮（空意见禁用），成功/失败给出提示并刷新文章、时间线与阶段数据；补充组件测试覆盖展示条件、通过请求与驳回请求。
- [x] 5.3 `ArticleDetailPage` 不对 `waiting_review` 显示通用“继续运行”，并确保人工决策后刷新状态；运行前端测试与构建。

## 6. 文档与集成验证

- [x] 6.1 更新 `docs/quality.md` 的审核规则与人工审批说明，确认描述与实际行为一致。
- [x] 6.2 运行后端全量 pytest、前端测试、lint 与构建，全部通过。
- [x] 6.3 使用测试库或 mock 平台走一遍“审稿通过→人工驳回→回退重生成→再次审稿→人工通过→排版”的端到端流程，确认无真实外发。

## Workflow follow-up

- 功能与集成验证完成后，归档 `review-human-approval` 变更。
