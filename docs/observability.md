# 可观测性：自托管 Langfuse 追踪

文章生成工作流的链路追踪默认关闭。开启后，每次运行会在本地 Langfuse 中生成一棵 trace 树，记录运行、阶段、LLM、deep agent 工具与外部 HTTP 请求的输入输出和耗时，用于排查 agent 问题。所有数据都留在内网；不接入任何云服务。

## 追踪边界

| 层级 / span | 来源 | 主要内容 |
| --- | --- | --- |
| `workflow.run` | `WorkflowRunner._run_graph()` | `run_id`、`article_id`、初始状态摘要；trace 的 `session_id` 为 `run_id` |
| `stage.<stage>` | 工作流节点 `_execute()` | 阶段名、尝试次数、产物摘要或错误 |
| LLM 调用 | `ChatOpenAI.callbacks` 上的 `CallbackHandler` | 模型、消息、输出、token 用量（由 Langfuse 集成生成） |
| `tool.web_search` / `tool.fetch_url` / `tool.save_source` | deep agent 工具函数体 | 查询、URL、结果数或保存结果 |
| `source.fetch` | 热点源采集，逐源一个 span | 源名称、URL、类型、状态、条目数 |
| `fetch.url` | `core/web.py::UrlFetcher.fetch` | URL、HTTP 状态、字符数、是否截断 |
| `search.query` | `HttpSearchTool.search` | 查询、结果上限、结果数、实际命中的搜索引擎、错误 |
| `publish.platform` | `PublishingService._publish_adapter` | 平台、文章标识、尝试次数、状态、`remote_id` |

不写入追踪的数据：平台凭据、LLM API Key、`Authorization` 请求头、完整响应体。提示词与文章内容会进入 trace，因此 Langfuse 只应部署在内网，并限制访问。

现有 `stage_runs`、`llm_calls`、SSE 事件与 `logs/` 仍是业务账本和运行依据；追踪用于补充 prompt 级输入输出与层级关系，不替代它们。

## 部署 Langfuse（Docker Desktop）

1. 启动 Docker Desktop，确认 `docker version` 可用。
2. 进入 `scripts/langfuse/`，复制配置并填入密钥：

   ```powershell
   cd scripts\langfuse
   copy .env.example .env
   ```

   至少修改 `POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`CLICKHOUSE_PASSWORD`、`MINIO_ROOT_PASSWORD`、`SALT`、`ENCRYPTION_KEY`、`NEXTAUTH_SECRET`、`LANGFUSE_INIT_PROJECT_PUBLIC_KEY`、`LANGFUSE_INIT_PROJECT_SECRET_KEY`、`LANGFUSE_INIT_USER_PASSWORD`。可用 PowerShell 生成随机值：

   ```powershell
   [Convert]::ToHexString((1..32 | ForEach-Object { Get-Random -Max 256 })).ToLower()   # ENCRYPTION_KEY
   [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Max 256 }))          # SALT / NEXTAUTH_SECRET
   ```

3. 启动（优先 `docker compose`，回退 `docker-compose`）：

   ```powershell
   .\start.bat
   ```

   首次启动会拉取镜像并初始化数据库，通常需要数分钟。脚本会在 web 容器健康后提示地址（默认 http://localhost:3000）。

4. 首次启动时，`.env` 中的 `LANGFUSE_INIT_*` 会创建组织、项目、登录用户和一对 API Key。用 `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` 登录即可。
   - 若数据库已存在，`LANGFUSE_INIT_*` 不再生效；此时在 UI 的 **Settings → API Keys** 中新建密钥，并同步到后端 `.env`。
   - `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `LANGFUSE_INIT_PROJECT_SECRET_KEY` 必须与后端使用的密钥一致。

5. 停止服务：

   ```powershell
   .\stop.bat
   ```

   停止不会删除数据；需要清空全部 trace 时执行 `docker-compose down -v`（或 `docker compose down -v`），会删除命名卷。

部署到内网服务器时，把 `LANGFUSE_NEXTAUTH_URL` 改为实际访问地址（如 `http://10.0.0.20:3000`），并按需修改 `LANGFUSE_WEB_PORT`。Compose 只发布 web 端口，Postgres、ClickHouse、Redis、MinIO 仅在容器网络内可见。

## 后端启用

在项目根目录 `.env` 中填写：

```text
APP_LANGFUSE_ENABLED=true
APP_LANGFUSE_HOST=http://127.0.0.1:3000
APP_LANGFUSE_PUBLIC_KEY=pk-lf-...
APP_LANGFUSE_SECRET_KEY=sk-lf-...
APP_LANGFUSE_SAMPLE_RATE=1.0
APP_LANGFUSE_TIMEOUT_SECONDS=5
```

重启后端。启动日志出现 `Langfuse tracing enabled` 表示成功；若缺少任一密钥，会记录一条 warning 并按未启用运行。

- `APP_LANGFUSE_SAMPLE_RATE`：0~1，调试期保持 `1.0`。
- `APP_LANGFUSE_TIMEOUT_SECONDS`：退出时 flush 的上限，超时只记录 warning。
- `APP_ENV` 会作为 Langfuse `environment` 标签；值只允许小写字母、数字、`_`、`-`，否则不写入。

## 查看与排障

- 用 `sessionId = <run_id>` 过滤一次运行；`run_id` 可在文章详情的运行记录或 `stage_runs` 中取得。
- 用 `article_id`、`stage`、`run_id` 作为 metadata 检索；阶段 span 名为 `stage.topic_selection`、`stage.research` 等。
- 定位 agent 问题：先看失败的 `stage.*`，再展开其下的 LLM 调用与 `tool.*`。工具参数、结果数量、外部请求状态都在对应 span 的 input/output 中。
- 外部服务失败：`source.fetch`、`search.query`、`fetch.url`、`publish.platform` 的 output 含 `status=error` 与错误文本，可直接区分网络、解析与平台返回问题。
- 阶段结果为空或异常时，对照 `stage_runs` 的产物与 SSE 事件判断是模型输出问题还是持久化问题。

## 故障与降级

- Langfuse 不可达、SDK 初始化失败或 flush 超时：只写本地 warning，工作流继续执行，不改变业务结果。
- 关闭 `APP_LANGFUSE_ENABLED` 后完全不加载 SDK 调用路径，测试与运行不需要 Langfuse。
- 采样会按 trace 丢弃数据，排障期间不要开启采样。

## 保留期与容量

- 在 Langfuse 项目设置中配置数据保留天数（建议 30 天）；磁盘紧张时先缩短保留期，再考虑采样。
- trace 含提示词与正文，增长较快；ClickHouse 与 MinIO 使用命名卷，扩容前先评估磁盘。
- 备份：需要长期保留的 trace 应在 Langfuse UI 中导出，或单独备份 `article-manager-langfuse_langfuse_clickhouse_data` 等命名卷。

## 离线 / 内网镜像

Docker Hub 受限时，在可联网机器上拉取并导出以下镜像，再在内网执行 `docker load`：

```text
langfuse/langfuse:3
langfuse/langfuse-worker:3
postgres:16-alpine
clickhouse/clickhouse-server:24.3
redis:7-alpine
minio/minio:latest
```

`LANGFUSE_VERSION`、`MINIO_VERSION` 可在 `scripts/langfuse/.env` 中固定为实际导入的 tag。内网有镜像仓库时，把 compose 中 `image:` 改为仓库地址即可。
