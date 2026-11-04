# Design

## Context

项目为全新代码库，仅有 OpenSpec 规划目录，无历史实现与兼容负担。运行目标是 Windows 10/11 本地单用户使用：双击脚本即可启动前后端，数据落在本地 SQLite 文件。外部能力（OpenAI 兼容 LLM、平台发布与指标接口）在开发期可能不可用，因此所有外部依赖都必须有可用的降级路径。

平台范围：微信公众号（草稿/发布 API）、知乎、掘金、CSDN。除公众号外，平台官方发布与数据接口不稳定或未开放，适配器需同时支持「接口模式」与「导出/手动回填模式」。参见 `proposal.md` 与 `specs/`。

## Goals / Non-Goals

**Goals:**

- 单机可运行、可观测、可人工介入的完整文章生产闭环。
- 工作流节点、平台适配器、技能三个维度都可插拔扩展。
- 每次模型调用都能归属到文章与阶段，成本可聚合、可对照表现。
- 审核不通过时按原因确定性回退，并能防止无限返工。
- 同一套适配器契约覆盖排版、发布、指标抓取三种能力。

**Non-Goals:**

- Docker 镜像、容器编排与生产级部署（本轮仅保留目录与文档预留）。
- 多用户、权限体系、水平扩展、分布式任务队列。
- 模拟登录、验证码绕过或任何非官方后台抓取。
- 平台收益数据的计费级准确性（以平台展示值为准，允许手动回填）。
- 自动应用自进化建议（默认必须人工批准）。

## Decisions

### D1. 技术栈与进程模型

- 后端：Python 3.11+、FastAPI、Pydantic v2、SQLAlchemy 2.0（同步 Session）+ Alembic、SQLite（WAL 模式）。
- 编排：LangGraph `StateGraph` + `langgraph-checkpoint-sqlite`；`deepagents` 用于需要工具探索的节点（资料搜索、写作修订）。
- 前端：React 18 + TypeScript + Vite + React Router + TanStack Query + Tailwind CSS + shadcn/ui；图表用 Recharts；Markdown 用 react-markdown + remark-gfm。
- 长任务：应用内 `asyncio` 后台任务运行工作流，单 Uvicorn worker；全局并发信号量默认 1（可在设置中调整）。SQLite 写操作串行化，避免多写冲突。
- 实时更新：SSE（`/api/events`），断线后前端重新拉取文章状态；不做 WebSocket 双向通道。

**替代方案**：Celery/Redis 队列（部署过重，单机无收益）；前端直接轮询（延迟与请求量更高）；Vue（团队未指定，React 生态与流程图组件更成熟）。

### D2. 目录结构

按功能纵向分包，文章生成主目录下每个阶段独立成包；平台相关代码全部收敛到 `platforms/<platform>/`，通过统一适配器接口接入。

```
backend/
  app/
    main.py
    api/                     # 路由：articles, topics, runs, stages, publishing,
                             # analytics, skills, models, evolution, platforms, settings, events
    core/                    # config, db, security, event_bus, scheduler, logging
    models/                  # SQLAlchemy ORM 模型
    schemas/                 # Pydantic 请求/响应
    article_generation/
      workflow/              # graph.py state.py routing.py runner.py checkpointer.py
      topic_selection/       # agent.py service.py prompts.py
      research/              # agent.py tools.py service.py prompts.py
      outline/               # generator.py service.py prompts.py
      writing/               # agent.py service.py prompts.py
      review/                # reviewer.py routing.py prompts.py
      formatting/            # service.py
      publishing/            # service.py
    platforms/
      base.py                # PlatformAdapter 抽象基类与数据类型
      registry.py            # 扫描/注册/能力查询
      wechat/                # adapter.py client.py formatter.py metrics.py templates/
      zhihu/
      juejin/
      csdn/
      mock/                  # 无凭据演示适配器
    skills/
      loader.py registry.py manager.py versions.py
    analytics/
      cost.py collector.py service.py
    self_evolution/
      signals.py analyzer.py applier.py scheduler.py
    prompts/                 # 各阶段提示词模板（Jinja2）
  tests/
  alembic/
  requirements.txt
frontend/
  src/
    api/ components/ pages/ hooks/ lib/ types/
    components/workflow/     # StageRail, StagePanel, StatusBadge
  package.json
skills/                      # 用户技能，内置示例 writing-style-tech-review/
data/                        # SQLite、密钥、日志（gitignore）
scripts/                     # start.ps1, setup.ps1
start.bat
README.md
.env.example
```

### D3. LangGraph 工作流

状态只保存 ID 与轻量元数据，正文内容按需从 DB 读取，避免 checkpoint 膨胀。

```python
class ArticleState(TypedDict):
    article_id: str
    run_id: str
    topic_id: str
    revision_count: int
    max_revisions: int
    review_verdict: str | None
    rollback_target: str | None
    stage_error: str | None
    formatted_platforms: list[str]
    publish_requested: bool
```

节点：`research → outline → write → review → format → publish`。选题在启动工作流前完成（`POST /run` 要求已选选题），保证「选题」节点在 UI 中存在但不参与自动回退。

- **条件边**：`review` 后由代码而非模型决定路由。事实/引用类严重问题 → `research`；结构类 → `outline`；其余 → `write`；通过 → `format`。
- **返工计数**：每次不通过路由前 `revision_count += 1`；达到上限时结束运行并置文章 `needs_human`，不进入死循环。
- **人工确认**：发布前条件边检查设置；需要确认时以 LangGraph `interrupt()` 暂停并等待 `POST /api/articles/{id}/confirm-publish` 用 `Command(resume=...)` 恢复。取消则结束运行，文章保持 `waiting_publish`。
- **暂停/继续**：协程式暂停——当前节点执行完后在阶段边界停住并标记 `paused`；用户继续时从下一节点恢复。不强行中断进行中的 LLM 调用。
- **断点续跑**：`thread_id = run_id`，checkpoint 存 `data/checkpoints.sqlite`。应用启动时将遗留 `running` 运行标记为 `interrupted`，允许用户继续。
- **用户编辑**：用户在大纲/正文节点的编辑产生新版本；下一节点总读取最新版本，因此编辑可在暂停或阶段间隙生效。运行中的编辑不会中断当前节点。
- **单文章单运行**：同一文章同一时刻只允许一个活动运行；重复启动返回冲突。

**修订回退时的数据处理**：不删除旧产物；下游阶段状态重置为 `pending`，生成新的 `stage_run` 记录与产物版本，保留比较历史。

### D4. deepagents 的使用边界

- **资料搜索节点**：deep agent + 工具（`web_search`、`fetch_url`、`save_source`），只允许有限轮次（默认 8），最终以结构化结果提交来源与事实要点。工具失败可降级为无外部资料的模型摘要。
- **写作节点**：deep agent + 工具（`read_outline`、`read_sources`、`check_citation`），系统提示注入写作风格技能，产出 Markdown。定向修订时只提供问题段落与审核意见，避免整篇重写。
- **其余节点**（选题推荐、大纲、审核、自进化分析）：直接结构化 LLM 调用，成本更低、结果更可控。
- 所有 deep agent 调用都套一层 `run_with_budget`：限制最大步数、超时与累计 Token，超限即中止并记录。

**替代方案**：全流程都用 deep agent（成本与不确定性高，偏离确定性工作流要求）；全流程直连 LLM（无法利用工具检索）。

### D5. 模型接入、路由与成本核算

- 所有模型通过 OpenAI 兼容配置接入：`base_url + api_key + model`。`models` 表保存模型档案与输入/输出单价（CNY/1K tokens）；`stage_model_bindings` 表把阶段映射到模型档案与温度/max_tokens。
- 结构化输出：优先 `with_structured_output`（JSON Schema）；对不支持 function calling 的兼容服务回退到 JSON 模式，并做 Pydantic 校验 + 一次修复重试 + 最终失败降级。
- 成本回调：LangChain `BaseCallbackHandler` 读取 `usage_metadata`，按调用时生效价格写入 `llm_calls`（含 article_id/run_id/stage）。缺少 usage 时用 tiktoken 估算并标 `estimated=true`；模型无价格时成本记 `NULL` 并标 `price_missing`，不写 0。
- 自进化的模型建议只修改阶段绑定，不删除历史价格；回滚即恢复上一绑定快照。

### D6. 平台适配器

统一接口（`platforms/base.py`）：

```python
class PlatformAdapter(ABC):
    key: str
    display_name: str
    capabilities: AdapterCapabilities  # format / publish / metrics / official_api
    def validate(self, credentials: dict) -> AdapterAvailability: ...
    def format(self, article: ArticleForFormat) -> FormatResult: ...
    def publish(self, artifact: FormatResult, credentials: dict) -> PublishResult: ...
    def fetch_metrics(self, record: PublishRecord, credentials: dict) -> MetricsSnapshot | None: ...
```

- 注册表扫描 `app.platforms.*` 下的 `adapter.py`，导入其中继承 `PlatformAdapter` 的类；不依赖手写清单，新增平台目录即可出现在平台列表。
- 每个平台目录自包含：`client.py`（HTTP/鉴权）、`formatter.py`（或模板）、`metrics.py`、`adapter.py`。公众号 `templates/` 存放内联样式 HTML 模板。
- 能力声明驱动 UI：无发布能力的平台只显示「导出/手动回填」；缺少凭据的平台显示「不可用」。
- 微信：使用 access_token 缓存 + 素材上传 + 草稿箱接口；默认推草稿。知乎：优先官方能力，否则导出 Markdown + 手动回填。掘金/CSDN：接口模式需用户提供 Cookie/Token，默认导出模式并明确风险提示。
- `mock` 适配器用于无凭据开发与测试，可完整跑通排版、发布、指标流程。
- 发布幂等：`(article_id, platform)` 唯一记录 + 平台远端 ID 校验；重试只针对失败/未发布平台。

### D7. 技能系统

- 技能目录：`skills/<slug>/SKILL.md`，YAML frontmatter：`name`、`description`、`version`、`applies_to`、`entry`、`files`。正文为规则说明，可附参考文件。
- 加载器：启动时扫描 + 校验 frontmatter、入口文件、版本号；无效技能标记 `invalid` 并记录原因，不阻断启动。内容按文件 mtime 缓存。
- 绑定：`skill_bindings(stage, skill_id, order, enabled)`。写作阶段支持多个技能按顺序拼接；注入位置为系统提示的技能区块。
- 版本：用户编辑或自进化应用时生成新版本，内容快照写入 `skill_versions`；回滚恢复指定版本并重新写回文件。
- 与 deepagents 的集成：把技能正文与参考文件映射为 deep agent 可用的技能上下文；若框架技能机制可用则通过其接口加载，否则由 `skills/manager.py` 渲染进系统提示，保持行为一致。
- 内置 `writing-style-tech-review` 示例技能，作为用户自定义模板。

### D8. 数据模型（SQLite）

| 表 | 关键字段与用途 |
|---|---|
| `articles` | 标题、状态、当前阶段、选题模式、目标平台、发布确认开关、时间戳 |
| `workflow_runs` | article_id、thread_id、status、current_stage、revision_count、max_revisions |
| `stage_runs` | run_id、stage、attempt、status、开始/结束、模型、token、成本、错误 |
| `topics` | 来源（手动/热点/AI）、标题、角度、理由、热点依据、是否选中 |
| `sources` | 标题、URL、摘要、发布时间、抓取时间、可信度、去重键 |
| `facts` | 事实要点、source_id、是否待核实 |
| `outline_versions` | 版本号、结构化内容 JSON、创建者、修订说明 |
| `draft_versions` | 版本号、Markdown、字数、模型、技能绑定快照、创建者 |
| `review_reports` | draft_version_id、维度评分 JSON、总分、结论、回退目标、配置版本 |
| `formatted_outputs` | 平台、标题、摘要、标签、HTML/Markdown、状态、错误 |
| `publish_records` | article_id+platform 唯一、远端 ID、URL、状态、错误、尝试次数 |
| `metric_snapshots` | publish_record_id、阅读/点赞/评论/分享/收益、来源（api/manual）、采集时间 |
| `llm_calls` | article/run/stage、模型、输入输出 token、单价、成本、耗时、是否估算 |
| `models` / `stage_model_bindings` | 模型档案与价格、阶段绑定、温度、max_tokens |
| `skills` / `skill_versions` / `skill_bindings` | 技能元数据、内容版本、阶段绑定 |
| `evolution_suggestions` | 类型、目标、证据、补丁、状态、前后快照 |
| `settings` / `credentials` | 键值配置；平台凭据 Fernet 加密存储 |

索引：`articles(status, updated_at)`、`llm_calls(article_id, stage)`、`metric_snapshots(publish_record_id, captured_at)`、`publish_records(article_id, platform)` 唯一。

### D9. API 表面

- 文章：`POST/GET /api/articles`、`GET/DELETE /api/articles/{id}`。
- 选题：`POST /api/articles/{id}/topics/recommend`、`POST /topics/{topic_id}/select`、`GET /topics`。
- 运行：`POST /articles/{id}/run`、`POST /runs/{run_id}/pause|resume|revision`、`POST /articles/{id}/confirm-publish`。
- 阶段：`GET /articles/{id}/stages`、`GET /articles/{id}/stages/{stage}`、`PUT /articles/{id}/outline|draft`。
- 排版发布：`GET /articles/{id}/formats`、`POST /articles/{id}/publish`、`POST /articles/{id}/publish/{platform}/retry`、`POST /publish/{platform}/manual`。
- 分析：`GET /api/analytics/summary`、`GET /api/analytics/articles/{id}`。
- 配置：`/api/skills`、`/api/skill-bindings`、`/api/models`、`/api/model-bindings`、`/api/settings`、`/api/platforms`、`/api/platforms/{key}/credentials`。
- 自进化：`/api/evolution/suggestions`（列表/生成/批准/拒绝/回滚）。
- 事件：`GET /api/events`（SSE），事件类型 `stage.status`、`artifact.created`、`review.completed`、`publish.updated`、`run.finished`。

错误约定：统一 `{code, message, details}`；冲突（重复运行/重复发布）返回 409；凭据缺失返回 422 并在 details 标明平台。

### D10. 前端流程可视化

- 文章详情页采用两栏布局：左栏固定宽度 240–280px，`position: sticky; top: 16px; align-self: start`，在整页滚动时保持可见；右栏渲染阶段内容。
- 流程条为自绘竖向时间线（7 个节点 + 连接线），状态色：未开始灰、进行中蓝（脉冲）、完成绿、失败红、待确认橙。每个节点显示名称、状态与耗时。
- 选择自绘而非 React Flow：节点固定且有序，自绘更轻、可访问性更好，也更容易做固定布局；React Flow 更适合可编辑 DAG。
- 点击节点切换右侧面板：选题（候选/已选）、资料（来源列表/事实）、大纲（版本编辑器）、写作（Markdown 编辑器 + 版本）、审核（报告与回退目标）、排版（平台 Tab + 预览）、发布（平台状态 + 操作）。
- 内容编辑使用受控编辑器（Markdown 用 textarea + 预览，公众号 HTML 用 sandboxed iframe 预览），保存即生成新版本。
- SSE 通过 `EventSource` 接入，收到事件后 invalidate 对应 query；断线自动重连并全量刷新。
- 小屏（<1024px）流程条折叠为顶部横向步骤条，可展开为抽屉；桌面端保持左侧固定。

### D11. 运维分析与自进化

- 指标采集：应用内 APScheduler 定时任务（默认每 6 小时，可配置）+ 手动刷新；逐平台调用 `fetch_metrics`，失败记录原因，不重试无限次。无接口平台支持手动回填并标记来源。
- 成本聚合：按文章/阶段/模型/日期汇总 `llm_calls`；收益与成本对照在 SQL 层聚合，避免前端重复计算。
- 自进化信号：模型稿与用户最终稿的 diff（difflib 段落级）、审核报告、指标快照。
- 建议生成：按固定周期或手动触发，输出结构化建议（类型、目标、证据、补丁、预期影响）。技能/提示词补丁先落库为草稿，批准后由 `applier` 写新版本并快照；模型建议批准后更新绑定并记录观察窗口。
- 效果追踪：建议应用后记录基线指标（审核均分、返工率、单篇成本），后续文章累计到 N 篇时计算对比；低于质量阈值的模型建议提示回滚。
- 安全护栏：自动任务永不自动应用建议；应用操作写审计日志。

### D12. 安全与凭据

- 默认仅监听 `127.0.0.1`，无登录（单用户本地应用）；若修改绑定地址，README 明确风险。
- 平台凭据使用 Fernet 加密存 SQLite；密钥来自 `APP_SECRET_KEY` 或首次启动生成的 `data/secret.key`。API 只返回掩码（末 4 位）。
- 外部 HTML 预览使用 `sandbox` iframe，禁止脚本执行；Markdown 渲染禁用原始 HTML。
- 日志脱敏：API Key、Cookie、access_token 不写入日志。
- 热点抓取遵守 robots 与频率限制，仅使用公开源。

### D13. Windows 一键启动

- `start.bat` 调用 `scripts/start.ps1`：检查 Python ≥3.11 与 Node ≥20；首次运行创建 `.venv`、安装后端依赖、执行 `alembic upgrade head`、播种默认模型价格/设置/技能、安装前端依赖；随后并行启动 Uvicorn 与 Vite，轮询 `/api/health` 后打开浏览器。
- 日志写入 `logs/backend.log`、`logs/frontend.log`；端口冲突时自动提示并允许通过 `.env` 修改。
- 提供 `scripts/setup.ps1` 仅安装不启动，便于排错。
- Docker 本轮不实现，README 保留后续章节占位。

## Risks / Trade-offs

- **平台接口不稳定或缺失** → 适配器声明能力并支持导出/手动回填；`mock` 适配器保证开发闭环；平台相关失败不阻断其他平台。
- **SQLite 并发写锁** → WAL + 单写者 + 全局工作流并发 1；运行状态与产物写入事务化。
- **OpenAI 兼容服务结构化输出不一致** → JSON Schema 优先、JSON 模式兜底、Pydantic 校验与修复重试，失败则显式报错而非静默降级。
- **Token/成本统计偏差** → 缺少 usage 时估算并标记，缺价格时置空并提示；不把估算值当精确账单。
- **自进化误改配置** → 默认仅建议、人工批准、版本快照与一键回滚；应用记录审计日志。
- **工作流长时间运行与崩溃** → checkpoint 持久化、启动时标记中断、支持续跑；节点内超时与 Token 预算限制。
- **深度 agent 成本与不可控** → 仅用于检索与写作，限制步数/超时/Token；其余节点用结构化直调。
- **凭据泄露** → 本地绑定、Fernet 加密、日志脱敏、掩码返回；单机无鉴权仍是已知限制，README 明示。
- **前端 SSE 断线** → 自动重连 + 全量刷新兜底，不依赖事件回放。

## Migration Plan

- 全新项目，无数据迁移。首次启动由 Alembic 建表，播种：默认设置、模型价格示例、`writing-style-tech-review` 技能、`mock` 平台。
- 升级：启动脚本执行 `alembic upgrade head`；升级前自动备份 `data/app.sqlite` 到 `data/backups/`。
- 回滚：停止服务，恢复备份文件并切回上一代码版本；不涉及外部服务迁移。

## Open Questions

- 各平台实际可用凭据与接口权限需在接入时用真实账号验证；接口模式不可用时以导出/手动回填交付，不影响规格。
- 周期分析任务的默认频率与观察样本量（N 篇）可在设置页调整，属于运行期配置，不改变设计。
