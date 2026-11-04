# Article Autopilot

自动写稿与发布 Agent：从选题、资料研究、大纲、写作、审核、分平台排版到发布，并提供阅读/收益/Token 成本分析与基于反馈的自进化建议。前后端分离，本地 SQLite 存储，工作流由 LangGraph 编排，研究与写作修订使用 deepagents。

## 功能概览

- **文章生成**：手动选题或 AI 推荐恰好 5 个热点候选 → deep agent 资料研究（直接调用百度/必应国内版/360/搜狗微信/DuckDuckGo/Google 免费搜索接口，可回退普通搜索）→ 结构化大纲 → 注入写作风格技能的正文 → 标题优化（多风格候选、评分与人工选定）→ 五维审核 → 微信/知乎/掘金/CSDN 排版 → 发布（默认人工确认）。
- **技能管理**：遵循 Agent Skills 标准（`SKILL.md` + YAML frontmatter，仅 `name`/`description` 必填），页面支持创建、导入 ZIP 技能包、编辑、启停与删除；导入会连同 `references/`、`scripts/`、`assets/` 一并落盘并做安全解压校验；技能可绑定到选题/资料/大纲/写作/标题/审核六个 LLM 阶段，仅在当前阶段渐进加载，支持资源清单与版本回滚，删除移入 `data/skill-trash/`。
- **智能选题**：热点信源支持 RSS/Atom 与 HTML 列表页（可配置多个，默认量子位、爱范儿、少数派、Product Hunt 和 OpenAI 官方）；先按来源过滤 AI 相关条目，再轮流从各来源取最多 10 条标题级信号交给模型，按娱乐适配分筛选（低于 60 分丢弃）。用户选定候选后才抓取对应正文并保存为来源，研究阶段直接复用、不重复抓取。
- **审核回退**：事实/引用问题回资料搜索，结构问题回大纲，表达/合规/原创问题回写作；写作回退只重写被指出章节，其余段落保持原文；超过返工上限标记 `needs_human`。
- **运维分析**：发布状态、阅读/点赞/评论/分享/收益快照、按文章/阶段/模型/日期聚合 Token 与成本，缺价格与估算值分别标记。
- **自进化**：从用户修改、审核报告与指标中提炼建议（写作规则/技能/提示词/模型路由），默认只生成待审批建议；应用后可追踪效果并提示回滚。
- **实时进度**：每篇文章左侧固定八阶段流程图，SSE 推送阶段状态，点击节点查看该阶段产物。

## 目录结构

```text
backend/
  app/
    api/                    # FastAPI 路由、序列化、错误处理、SSE
    article_generation/     # 文章生成父模块
      topic_selection/      # 选题（RSS/HTML 热点信源、正文抓取）
      research/             # 资料搜索（含 deep agent）
      outline/              # 大纲
      writing/              # 写作（含定向修订）
      title_optimization/   # 标题优化（候选、评分与人工选定）
      review/               # 审核与回退路由
      formatting/           # 分平台排版
      publishing/           # 发布
      workflow/             # LangGraph 图、节点、运行器
    platforms/              # 平台适配器：base/registry + 每个平台独立目录
    skills/                 # 技能加载、注册表、绑定、版本
    analytics/              # 指标采集、成本台账与聚合
    self_evolution/         # 信号、建议、审批应用、调度
    core/                   # 配置、数据库、LLM、日志、安全、事件、预算
    models/                 # SQLAlchemy ORM
    prompts/                # Jinja2 提示词模板
  alembic/                  # 数据库迁移
  tests/                    # pytest（浏览器外的全部核心行为）
frontend/                   # React + TypeScript + Vite 工作台
skills/                     # 用户可编辑技能（内置 writing-style-tech-review）
scripts/                    # Windows 安装/启动脚本；langfuse/ 为自托管追踪编排
docs/                       # 适配器、技能与提示词维护文档
data/                       # SQLite、检查点、密钥（git 忽略）
logs/                       # 运行日志（git 忽略）
```

## 环境要求

- Windows 10+（其他平台可手动执行等价命令）
- Python 3.11+
- Node.js 18+

## 快速开始（Windows 一键）

```powershell
# 首次安装：venv、依赖、数据库迁移、默认数据
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 复制配置并填写 LLM Key
Copy-Item .env.example .env

# 启动：直接双击根目录 start.bat，或执行
.venv\Scripts\python.exe scripts\start.py
```

`start.bat` 调用纯 Python 启动器 `scripts/start.py`，不依赖 PowerShell 脚本执行权限；即使系统禁止运行未签名 `.ps1`，也能正常启动。启动窗口会保持打开，按 Enter 停止前后端。若依赖尚未安装且 PowerShell 同样被限制，可按下方“手动启动”安装依赖并执行迁移。

启动后：

- 前端：<http://127.0.0.1:5173>
- 后端健康检查：<http://127.0.0.1:8000/api/health>
- 外部服务检测：前端「设置 → 服务检测」点击「立即检测」；也可调用 `POST /api/health/connectivity/check` 触发，`GET /api/health/connectivity` 读取最近一次 JSON 报告。报告保存在本地数据库，包含逐项状态、耗时和不含凭据的失败原因。检测会实际请求已配置的 RSS、搜索、Memecub、默认模型和公众号草稿接口；默认模型会产生一次极短的调用。
- OpenAPI 文档：<http://127.0.0.1:8000/docs>（JSON：`/openapi.json`）
- 日志：`logs/backend.*.log`、`logs/frontend.*.log`
- 停止：在启动窗口按 Enter；或结束对应 Python/Node 进程

## 手动启动（开发）

```powershell
# 后端
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm run dev
```

## 配置

所有配置使用 `APP_` 前缀，可通过 `.env` 或环境变量覆盖，完整清单见 `.env.example`。关键项：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_SECRET_KEY` | 空 | 平台凭据加密密钥；为空时自动生成 `data/secret.key` |
| `APP_LLM_BASE_URL` / `APP_LLM_API_KEY` / `APP_LLM_MODEL` | OpenAI 兼容 / `gpt-4o-mini` | 初始化时写入默认模型档案；也可在设置页配置模型与阶段绑定 |
| `APP_LLM_INPUT_PRICE_PER_1K` / `APP_LLM_OUTPUT_PRICE_PER_1K` | 空 | 每 1K token 单价；未设置时用量照常记录，成本标记为 `price_missing` |
| `APP_SEARCH_ENGINES` | `baidu,bing,360,wechat` | 免费搜索引擎，按顺序直接请求并本地解析 HTML；`baidu` 百度、`bing` 必应国内版、`360` 360 搜索、`wechat` 搜狗微信文章搜索，另支持 `duckduckgo`/`google`；无需 MCP 或 API Key，留空则禁用免费搜索 |
| `APP_SEARCH_ENDPOINT` | 空 | 可选的 JSON 搜索服务；配置后优先使用，免费搜索引擎作为回退 |
| `APP_SEARCH_THROTTLE_ENABLED` | `true` | 是否启用免费搜索防护（限流、失败冷却、结果缓存、单次预算）；设为 `false` 时全部跳过 |
| `APP_SEARCH_MIN_INTERVAL_SECONDS` | `1` | 同一搜索引擎两次请求之间的最小间隔（秒），进程级生效 |
| `APP_SEARCH_CACHE_TTL_SECONDS` | `600` | 搜索结果缓存时长（秒）；`0` 关闭缓存 |
| `APP_SEARCH_COOLDOWN_SECONDS` | `60` | 某引擎请求失败后的冷却时长（秒）；冷却期间直接切换到下一引擎 |
| `APP_SEARCH_MAX_REQUESTS_PER_CALL` | `6` | 单次搜索最多发起的引擎请求数；缓存命中不计入预算 |
| `APP_HOT_TOPIC_SOURCES` | 空 | 选题热点信源，JSON 数组；每项 `name`、`type`（`rss`/`html`）、`url`，可加 `include_keywords` 过滤标题、`priority_keywords` 优先选择账号感兴趣的话题；产品名不含 AI 的源可设 `match_summary: true`，同时检查摘要。HTML 可加 `item_selector`/`title_selector`/`link_selector`/`content_selector`。为空时回退旧 `APP_HOT_TOPICS_FEEDS`，再回退默认五个 RSS |
| `APP_HOT_TOPICS_FEEDS` | 空 | 旧版 RSS 源列表，逗号分隔；仅在 `APP_HOT_TOPIC_SOURCES` 为空时生效，两者都为空时使用默认五个 RSS |
| `APP_TOPIC_ARTICLE_MAX_CHARS` | `4000` | 选定候选后抓取的正文最大字符数（500–20000） |
| `APP_PUBLISH_CONFIRMATION` | `true` | 发布前是否人工确认 |
| `APP_MAX_REVISIONS` | `3` | 审核返工上限 |
| `APP_REVIEW_PASS_THRESHOLD` | `75` | 审核通过总分阈值 |
| `APP_MAX_CONCURRENT_RUNS` | `1` | 同时运行的工作流数量 |
| `APP_DEEP_RESEARCH_ENABLED` | `true` | 资料研究 deep agent 开关 |
| `APP_DEEP_REVISION_ENABLED` | `true` | 定向修订 deep agent 开关 |
| `APP_LANGFUSE_ENABLED` | `false` | 自托管 Langfuse 链路追踪开关；同时配置 `APP_LANGFUSE_HOST`、`APP_LANGFUSE_PUBLIC_KEY`、`APP_LANGFUSE_SECRET_KEY`，部署与排障见 [docs/observability.md](docs/observability.md) |

## AI 娱乐账号内容策略

在「设置 → 账号画像」编辑账号名称、目标读者、内容承诺、语气、栏目、排除话题和幽默边界。画像持久化为 `account_profile` 配置，后续选题、大纲、写作、标题和审核都会读取。已有数据库更新代码后，先在 `backend` 目录运行 `..\.venv\Scripts\python.exe -m alembic upgrade head`。

AI 推荐固定返回 5 个候选，按照账号匹配、新鲜反差、读者共鸣、可展示性、自然笑点的加权分数筛选。候选会保存分项分数、推荐理由和内容形式。手动添加选题时也可以选择内容形式。当前提供「热点轻解读」「AI 工具实测」「AI 脑洞实验」三种模板，选定后会影响大纲结构、默认字数和写作要求；手动传入目标字数仍可覆盖模板默认值。无热点信号的候选不会标记为热点。

## 平台凭据与安全

- 微信、知乎、掘金、CSDN 凭据在设置页录入，使用 Fernet 加密后存入 SQLite；接口只返回 `***` 掩码。
- `APP_SECRET_KEY` 或自动生成的 `data/secret.key` 决定密文；更换密钥后旧凭据无法解密，需要重新录入。
- 日志会对密钥/Token 做脱敏；不要提交 `.env`、`data/`、`logs/`。
- 服务默认仅监听 `127.0.0.1`，不应直接暴露到公网。如需远程访问，请自行增加反向代理、认证与 HTTPS。
- 公众号 HTML 仅在前端沙箱 iframe 中预览，脚本不会执行。
- 同步公众号草稿箱：在「设置 → 平台凭据 → 微信公众号」填写 `app_id`、`app_secret`、封面永久素材 `thumb_media_id`，以及 `publish_mode: "draft"`。还需在公众号后台把运行本项目的机器出口公网 IP 加入接口白名单，并确认账号有草稿箱接口权限。正文 Memecub 图片会在建草稿前上传为微信图片；同步成功后本地状态为「已同步至公众号草稿箱」，不会自动公开发表。
- 可选 Memecub 配图：在 `.env` 中设置 `APP_MEMECUB_ENABLED=true` 与 `APP_MEMECUB_API_KEY`。分平台排版时会根据正文选两处插图，只采用标注可商用的图片并附上要求的署名；符合条件的图片不足两张时保留原文，提示会保存在排版产物中。同一稿件版本复用配图，单个平台重试不会换图；修改正文生成新版本后会重新选图。公众号发布前会将 Memecub 图片上传至微信正文图片接口。检索结果目前可能以 Emoji 为主，建议发布前检查画风和授权信息。

## 测试

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run lint
npm run test
npm run build
```

测试使用临时 SQLite、假 LLM 与 mock 适配器，不会调用真实模型或平台。

## 新增平台 / 技能

- 平台适配器：见 [docs/adapters.md](docs/adapters.md)。每个平台一个目录（如 `backend/app/platforms/wechat/`），启动时自动发现。
- 技能：见 [docs/skills.md](docs/skills.md)。可在「技能管理」页创建标准 `SKILL.md`、导入包含 `references/scripts/assets` 的 ZIP 技能包、编辑正文、删除（移入 `data/skill-trash/`），并绑定到六个 LLM 阶段；文件修改后热加载，无需重启。
- 选题提示词：见 [docs/prompts.md](docs/prompts.md)。修改 `backend/app/prompts/topic_selection.md` 后下一次推荐即生效，无需重启。
- 链路追踪：见 [docs/observability.md](docs/observability.md)。`scripts/langfuse/` 提供自托管 Langfuse 的 Compose、`start.bat` 与 `stop.bat`；默认关闭，开启后可在内网查看运行、阶段、LLM、工具与外部请求的完整输入输出。

## Docker

Docker 部署暂未实现（规划中）。当前以 Windows 本地一键启动为准；容器化时沿用同一套 `APP_*` 环境变量、SQLite 数据卷与 `alembic upgrade head`。
