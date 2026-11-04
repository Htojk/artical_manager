# Proposal

## Why

当前排查文章生成问题只能依赖 `stage_runs` 状态、`llm_calls` 统计和日志，看不到每个阶段、每次 LLM 调用、每次工具/外部请求的真实输入输出与层级关系。agent 出错时无法快速回答“是哪一步、哪个 prompt、哪次工具调用导致的”。需要一套**内网自托管**的链路追踪，既能按文章/运行回放完整数据流，又不把提示词与生成内容传出内网。

## What Changes

- 新增 Langfuse 自托管部署编排：Docker Compose（Langfuse Web/Worker + Postgres + ClickHouse + Redis + MinIO）、环境变量模板与 Windows 启动脚本，可部署在本机 Docker Desktop 或内网 Docker 主机。
- 新增可选追踪层 `backend/app/core/tracing.py`：由 `APP_LANGFUSE_ENABLED` 与连接参数显式开启；未开启或依赖缺失时为 no-op，测试与无 Langfuse 环境完全不受影响。
- 工作流接入：每次 workflow run 建立根 trace，每个 Graph 节点建立 stage span，每次 LLM 调用（含结构化输出回退、deep agent 工具循环）建立子 span，并注入 `article_id`、`run_id`、`stage`、`attempt` 元数据。
- 外部 IO 接入：热点源抓取、正文抓取、搜索、平台发布建立独立 span，记录 URL/查询、耗时、状态与截断后的结果摘要；凭据与密钥不写入 trace。
- 运维配套：`docs/observability.md`、README、`.env.example` 增加开关与排障说明；提供关闭/降级路径。
- **BREAKING**：无。默认关闭，现有 API、数据库与运行行为不变。

## Capabilities

### New Capabilities

- `observability/agent-tracing`: 工作流与 agent 的端到端链路追踪能力，覆盖运行、阶段、LLM 调用与外部 IO 的输入输出、耗时、状态和关联元数据，并保证默认关闭、失败降级与敏感信息不落 trace。

### Modified Capabilities

无。现有规格行为不变；追踪是新增的可选观测能力，不改文章生成、技能、发布等既有需求。

## Impact

- 后端：新增 `app/core/tracing.py`；修改 `app/core/config.py`、`app/core/llm.py`、`app/article_generation/workflow/runner.py`、`workflow/nodes.py` 及热点抓取/搜索/发布等外部 IO 边界；新增依赖 `langfuse`。
- 配置：新增 `APP_LANGFUSE_ENABLED`、`APP_LANGFUSE_HOST`、`APP_LANGFUSE_PUBLIC_KEY`、`APP_LANGFUSE_SECRET_KEY`（可选采样率/超时）。
- 部署：新增 `scripts/langfuse/`（compose、env 模板、启动脚本），默认端口 3000/3030，不影响现有 8000/5173。
- 数据：不新增业务表、不做数据库迁移；trace 数据只存在于 Langfuse 自身的 Postgres/ClickHouse。
- 兼容性：开关关闭时零行为差异；Langfuse 不可达时只记录本地告警，不阻塞工作流。
- 文档：新增 `docs/observability.md`，更新 README 与 `.env.example`。
