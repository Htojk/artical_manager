# Design

## Context

- 工作流由 LangGraph 编排：`WorkflowRunner._execute()` 用 `asyncio.to_thread()` 调 `_run_graph()`，节点是普通方法（`backend/app/article_generation/workflow/nodes.py`），运行配置目前只有 `thread_id`。
- 所有模型调用统一走 `LLMService.structured()` → `build_model()` 返回 `ChatOpenAI`，并已挂载 `CostTracker` 回调；深度研究用 `create_deep_agent()`，工具为自定义 `@tool`。
- 外部 IO 分散在热点源采集（`topic_selection/sources/`）、正文抓取（`topic_selection/articles.py` 的 `UrlFetcher`）、搜索（`research/tools.py`）、平台适配器（`platforms/base.py::publish`）。
- 现有可观测手段：`stage_runs`、`llm_calls`、SSE 事件与 `logs/`；缺少 prompt 级输入输出与跨阶段层级关系。
- 约束：数据不得出内网；Windows 10；Docker Desktop 已安装但引擎未启动；默认关闭不能影响现有测试与运行。
- 目标部署假设：先在本机 Docker Desktop 验证，compose 同时可部署到内网 Docker 主机；具体主机由部署时决定，不影响代码设计。

## Goals / Non-Goals

**Goals:**

- 一次运行可在追踪视图中还原“运行 → 阶段 → 模型/工具 → 外部请求”的完整数据流。
- 所有记录带 `article_id`/`run_id`/`stage`/`attempt`，支持从文章或运行反查。
- 关闭时零行为差异；开启后追踪后端故障不影响工作流。
- 提供可直接使用的自托管编排、配置模板与排障文档。

**Non-Goals:**

- 不替代现有 `stage_runs`/`llm_calls` 业务账本与 SSE 进度。
- 不做提示词评测、数据集管理、告警通知或日志聚合。
- 不采集平台凭据、密钥与完整请求头。
- 不实现跨进程/跨服务的分布式追踪（当前是单进程后端）。

## Decisions

### 1. 采用自托管 Langfuse v3，而非云服务或自研

- 选 Langfuse：开源、可 Docker 自托管、原生 LangChain/LangGraph 回调、UI 直接提供 trace 树与输入输出查看；满足“数据不出内网”。
- 备选 LangSmith 云：接入最省事，但提示词/生成内容会上传外部，已排除。
- 备选 OTel + Tempo/Jaeger/Grafana：通用但需要自建查询与 UI，成本高。
- 备选扩展现有 `stage_runs`：无现成 UI、检索和回放能力，等于自研，放弃。
- 服务端为 Langfuse v3（Web/Worker + Postgres + ClickHouse + Redis + MinIO），Python SDK 固定为 `langfuse==5.1.0`（当前内网镜像可获取的版本，原生支持 v3 服务端）；只在 compose 中暴露 Web 端口（默认 3000），其余仅容器网络可见。

### 2. 接入方式：CallbackHandler + 显式 span，不依赖全局 tracer

- 新增 `backend/app/core/tracing.py`，对外只暴露以下入口：
  - `configure_tracing(settings)`：在 lifespan 启动时初始化，返回是否启用；
  - `get_langfuse_handler()`：返回单例 `CallbackHandler` 或 `None`；
  - `trace_attributes(...)`：用 `propagate_attributes()` 把 `session_id`、`trace_name`、`tags`、`metadata` 传播到当前 trace 内的所有 span；
  - `trace_span(name, input=..., metadata=...)`：上下文管理器，内部调用 SDK 5.1 的 `start_as_current_observation(as_type="span")`，未启用时为 no-op；
  - `shutdown_tracing()`：lifespan 关闭时在受限线程中 flush 并关闭客户端。
- 模型调用：在 `LLMService.build_model()` 的 `callbacks` 中追加 handler（与 `CostTracker` 并存），保证每个 LLM 调用都被采集，包括 deep agent 内部调用。
- **handler 只挂在 `ChatOpenAI.callbacks`，不写入 LangGraph 的 invoke config**：同一 handler 同时出现在局部回调和继承配置时，LangChain 会为同一次 run 触发两次 `on_chain_start`，导致 Langfuse 中出现重复 observation。节点/工具/外部 IO 因此显式埋点，而不是依赖图级回调。
- 运行根 span：在 `WorkflowRunner._run_graph()` 外层先用 `trace_attributes(session_id=run_id, trace_name="workflow.run")` 建立 trace 属性，再开启 `workflow.run` span，元数据含 `run_id`、`article_id`。
- 阶段 span：在节点 `_execute()` 的 `_begin()`/`_finish()` 之间开启 `stage.<name>`，结束时写入产物或错误；`Stage` 是 `StrEnum`，使用 `str(stage)` 保证名称与元数据稳定。
- 上下文传递：`asyncio.to_thread()` 会复制 contextvars；deep agent 的 `ThreadPoolExecutor` 不会，因此在 `run_with_budget()` 中显式 `contextvars.copy_context()` 后提交任务，保证工具 span 仍挂在当前工作流下。
- 备选“只依赖 LangGraph 自动回调”：节点是普通函数，无法保证所有工具/外部 IO 都进入同一棵树，且存在重复回调问题，放弃。

### 3. 元数据与分组

- 统一读取现有 `llm_context`（`article_id`/`run_id`/`stage`），通过 `config.metadata` 传给 handler：
  - `langfuse_session_id = run_id`（同一运行聚合）；
  - `langfuse_tags = [stage, model]`；
  - 业务元数据：`article_id`、`run_id`、`stage`、`attempt`。
- 不设置用户身份（本地单用户系统），避免伪匿名数据。

### 4. 外部 IO 的埋点边界

| 边界 | 位置 | 记录内容 |
| --- | --- | --- |
| 热点源抓取 | `topic_selection/sources/collector.py::HotTopicSource.fetch`（逐源） | 源名称、URL、类型、状态、条目数、耗时 |
| 正文抓取 | `core/web.py::UrlFetcher.fetch` | URL、HTTP 状态、字符数、是否截断；失败时记录错误 |
| 搜索 | `research/tools.py::HttpSearchTool.search` | 查询、上限、结果数、错误；不记录 `Authorization` 头 |
| 平台发布 | `publishing/service.py::PublishingService._publish_adapter`（适配器外层） | 平台、文章标识、尝试次数、状态、`remote_id`；不记录凭据 |

- 以上统一使用 `trace_span`，只记录白名单字段；不写入完整响应体，避免 trace 膨胀。
- deep agent 的 `web_search`/`fetch_url`/`save_source` 在工具函数体内手动开启 `tool.*` span，记录查询/URL/数量或保存结果；这些 span 与外部 IO span 形成嵌套，而模型调用由 `ChatOpenAI.callbacks` 上的 handler 自动记录，二者不重复。

### 5. 配置与降级

新增 `Settings` 字段（均可通过 `APP_` 环境变量覆盖）：

```text
APP_LANGFUSE_ENABLED=false
APP_LANGFUSE_HOST=http://127.0.0.1:3000
APP_LANGFUSE_PUBLIC_KEY=
APP_LANGFUSE_SECRET_KEY=
APP_LANGFUSE_SAMPLE_RATE=1.0        # 0~1，默认全量
APP_LANGFUSE_TIMEOUT_SECONDS=5      # 关闭时 flush 的上限
```

- 启用条件：`enabled` 为真且 host/公钥/私钥齐全；否则按未启用处理并记录一条配置告警。
- 初始化异常、handler 创建失败、flush 超时全部捕获并记录 warning，不向上抛。
- 默认关闭；`tests/conftest.py` 显式设置 `APP_LANGFUSE_ENABLED=false`，保证测试零网络依赖。

### 6. 部署编排

- 新增 `scripts/langfuse/docker-compose.yml`：`langfuse-web`、`langfuse-worker`、`postgres`、`clickhouse`、`redis`、`minio`，命名卷持久化，仅暴露 3000。
- 新增 `scripts/langfuse/.env.example`：数据库密码、ClickHouse 密码、MinIO 凭据、`ENCRYPTION_KEY`、`NEXTAUTH_SECRET`、`SALT`。
- 新增 `scripts/langfuse/start.bat` / `stop.bat`，优先 `docker compose`，回退 `docker-compose`；启动后等待健康检查再提示访问地址。
- 镜像版本固定（Langfuse 3.x、Postgres 16、ClickHouse 24.x、Redis 7、MinIO 最新稳定版），避免漂移。
- 若 Docker Hub 受限，文档给出“内网镜像仓库/离线 `docker save`/`docker load`”路径。

### 7. 测试策略

- 单元测试（不依赖真实 Langfuse）：
  - 开关关闭时 `configure_tracing` 返回未启用、`trace_span` 为 no-op、`build_model` 的 callbacks 不包含 handler；
  - 配置缺项时按未启用处理；
  - 启用时 metadata 映射包含 `langfuse_session_id` 与 article/run/stage；
  - 初始化异常被吞掉并记录 warning；
  - 外部 IO 埋点在关闭时不改变返回值。
- 可选集成测试：仅当设置 `LANGFUSE_TEST_HOST` 时运行，默认 skip，不进入常规 CI。
- 回归：现有后端全量 `pytest` 与前端测试保持通过。

## Risks / Trade-offs

- [Docker Hub/镜像拉取受限] → 文档提供内网仓库与离线导入方式；代码接入不依赖部署先完成。
- [ClickHouse/全套服务资源占用较高] → compose 限制资源、配置 TTL；只在小规模使用，必要时单独部署到内网服务器。
- [trace 含提示词与文章内容] → 仅内网自托管，配置访问控制与保留期；文档明确告知敏感性。
- [追踪 SDK 增加调用开销] → 异步批量上报、可采样；关闭时完全不加载调用路径。
- [模型调用散落在多处，可能漏埋点] → 统一在 `build_model()` 挂 handler，并用测试断言 handler 存在。
- [异步线程上下文丢失导致层级断裂] → 根 span 在 `_run_graph()` 线程内创建；`to_thread` 复制 context；`ThreadPoolExecutor` 中显式 `copy_context()`；用 `session_id` 兜底聚合。
- [版本漂移导致 API 不兼容] → 固定 `langfuse` Python 包与 compose 镜像版本。

## Migration Plan

1. 后端接入与单元测试先落地，默认关闭，合并后行为不变。
2. 本机启动 Docker Desktop，执行 `scripts/langfuse/start.bat` 拉起服务；在 Langfuse UI 创建组织/项目并生成 API Key。
3. 在 `.env` 填入 `APP_LANGFUSE_ENABLED=true`、`APP_LANGFUSE_HOST` 与密钥，重启后端；发起一次测试文章运行，确认 trace 树完整。
4. 回滚：将 `APP_LANGFUSE_ENABLED=false` 并重启后端即可；需要彻底移除时停止 compose，不涉及数据库迁移或业务数据。
5. 保留策略：在 Langfuse UI 或 ClickHouse TTL 配置保留天数，文档给出建议值（如 30 天）。

## Open Questions

- 部署主机选本机还是内网服务器，部署时确定；compose 与配置模板对两者通用。
- trace 保留天数与采样率由运维在部署时按磁盘与流量确定，不阻塞实现。
