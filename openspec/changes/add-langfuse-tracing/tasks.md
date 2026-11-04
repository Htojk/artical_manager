# Tasks

## 1. 依赖与配置

- [x] 1.1 在 `backend/requirements.txt` 增加固定版本的 `langfuse==5.1.0`（适配 Langfuse v3 服务端），安装后验证 `.venv` 中 `import langfuse` 成功；版本与 compose 镜像主版本保持一致
- [x] 1.2 在 `backend/app/core/config.py` 增加 `langfuse_enabled`、`langfuse_host`、`langfuse_public_key`、`langfuse_secret_key`、`langfuse_sample_rate`、`langfuse_timeout_seconds`，并补充 `.env.example`；新增配置测试覆盖默认关闭、采样率范围与缺项判定，运行 `pytest tests/test_config.py -q`
- [x] 1.3 在 `backend/tests/conftest.py` 显式设置 `APP_LANGFUSE_ENABLED=false`；确认现有测试不产生任何外部网络请求

## 2. 追踪核心模块

- [x] 2.1 新建 `backend/app/core/tracing.py`：实现启用判定、Langfuse 客户端与 CallbackHandler 单例、`trace_span()` no-op/上报两种路径、`shutdown_tracing()` flush 与超时保护；初始化与上报异常只记录 warning；补充单元测试覆盖关闭、缺项、初始化异常与 span 元数据写入，运行 `pytest tests/test_tracing.py -q`
- [x] 2.2 在 `backend/app/main.py` lifespan 中启动时调用 `configure_tracing()`、关闭时调用 `shutdown_tracing()`；验证应用启动/退出在启用与关闭两种配置下均正常，补充 lifespan 测试

## 3. 工作流与模型接入

- [x] 3.1 修改 `backend/app/core/llm.py::build_model()`，启用时把 Langfuse handler 与 `CostTracker` 一起挂到 `callbacks`，并在调用时通过 `config.metadata` 注入 `langfuse_session_id`、`article_id`、`run_id`、`stage`；补充测试断言启用时包含 handler、关闭时 callbacks 不变
- [x] 3.2 在 `backend/app/article_generation/workflow/runner.py::_run_graph()` 外层建立 `workflow.run` 根 span，注入 run/article 元数据；在 `nodes` 的阶段执行入口建立 `stage.<name>` span，结束时记录状态、耗时与产物/错误摘要；补充测试断言阶段 span 名称与元数据映射
- [x] 3.3 验证深度研究路径：确认 `create_deep_agent()` 的模型与工具调用进入同一 trace；在 `web_search`/`fetch_url`/`save_source` 工具体内手动开启 `tool.*` span，补充参数与结果映射的单元测试

## 4. 外部 IO 埋点

- [x] 4.1 在 `backend/app/article_generation/topic_selection/sources/collector.py` 为热点源抓取增加逐源 span，记录源名称、URL、类型、状态、条目数与耗时；补充测试断言关闭时为 no-op、启用时字段齐全
- [x] 4.2 在 `backend/app/core/web.py::UrlFetcher.fetch` 增加 span，记录 URL、HTTP 状态、字符数与是否截断；补充测试覆盖成功与失败
- [x] 4.3 在 `backend/app/article_generation/research/tools.py::HttpSearchTool.search` 增加 span，记录查询、结果数、耗时与错误；补充测试覆盖未配置/失败路径
- [x] 4.4 在 `backend/app/article_generation/publishing/service.py::_publish_adapter` 的 `publish` 调用边界增加 span，记录平台、文章标识、尝试次数与结果状态；补充测试断言凭据与请求头不出现在 span 属性中

## 5. 部署编排与文档

- [x] 5.1 新增 `scripts/langfuse/docker-compose.yml`、`scripts/langfuse/.env.example`、`start.bat`、`stop.bat`：包含 web/worker/Postgres/ClickHouse/Redis/MinIO、命名卷、健康检查与固定镜像版本，仅暴露 3000；用 `docker-compose config`（或 `docker compose config`）验证编排可解析
- [x] 5.2 新增 `docs/observability.md`：说明部署步骤、创建 API Key、后端开关、trace 树结构与排障用法、保留期/采样建议、敏感信息边界、离线镜像导入路径；同步更新 `README.md` 与 `.env.example` 链接，核对文档中的命令可执行

## 6. 集成验证

- [x] 6.1 运行后端全量 `pytest -q`、前端 `npm run lint && npm test && npm run build`，确认全部通过；运行 `openspec validate add-langfuse-tracing --strict` 通过
- [ ] 6.2 启动本机 Langfuse（Docker Desktop）与后端，创建一篇测试文章并跑完一次工作流；确认 trace 树包含根运行、八个阶段、LLM 调用、工具与外部 IO，且 `article_id`/`run_id`/`stage` 可检索
- [ ] 6.3 人工检查 trace 与日志：平台凭据、API Key、Authorization 头均未出现；停掉 Langfuse 后再跑一次运行，确认工作流正常完成且只有本地 warning

## Workflow follow-up

- 评审通过后归档本变更；若基础规格 `add-article-autopilot` 尚未归档，按仓库现有归档顺序处理。
- 部署到内网服务器后，补充实际 `LANGFUSE_HOST` 与保留期配置。
