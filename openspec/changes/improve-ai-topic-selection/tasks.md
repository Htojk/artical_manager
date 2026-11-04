# Tasks

## 1. 依赖与配置

- [x] 1.1 在 `backend/.requirements.txt` 增加 `beautifulsoup4>=4.12`，安装后运行 `..\.venv\Scripts\python.exe -c "import bs4"` 确认导入成功
- [x] 1.2 在 `backend/app/core/config.py` 新增 `hot_topic_sources: str = ""` 与 `topic_article_max_chars: int = Field(default=4000, ge=500, le=20000)`，以及解析信源配置的 `hot_source_specs` 属性（JSON → 旧 `feed_urls` → 默认量子位 RSS），在 `backend/tests/test_config.py` 覆盖三种分支并运行 `pytest tests/test_config.py -q`
- [x] 1.3 更新 `.env.example`，加入 `APP_HOT_TOPIC_SOURCES` 的 JSON 与 HTML 选择器示例、`APP_TOPIC_ARTICLE_MAX_CHARS`，并用注释说明旧 `APP_HOT_TOPICS_FEEDS` 仍兼容

## 2. 信源注册与解析

- [x] 2.1 新建 `backend/app/article_generation/topic_selection/sources/` 包（`base.py` 定义 `HotSignal`、`HotSourceSpec`、标题归一化与配置解析），把 `hot_topics.py` 的完整实现拆为 `rss.py`，`hot_topics.py` 改为 re-export，运行现有 `pytest tests/test_services.py -q` 确认导入与行为不变
- [x] 2.2 在 `sources/html.py` 用 BeautifulSoup + `html.parser` 实现列表页解析（条目/标题/链接选择器、`urljoin`、跳过 javascript 与空标题、可选发布时间），新增 `backend/tests/test_hot_sources.py` 覆盖正常解析与选择器不匹配两种场景并运行通过
- [x] 2.3 在 `sources/collector.py` 实现 `HotTopicSource.fetch()`：按配置顺序抓取、单源超时/非 2xx/解析失败隔离进 `errors`、按标题去重后赋予 1-based `index`、按 `limit` 截断；测试覆盖 RSS+HTML 混合、单源失败不影响其他源、标题去重，并运行 `pytest tests/test_hot_sources.py -q`

## 3. 标题级提示词输入与候选契约

- [x] 3.1 扩展 `backend/app/schemas/artifacts.py` 的 `TopicCandidate`：`hot_signal_index`（≥0）、`discussion_score`（0–100）、`discussion_reason`，并为评分增加缺失/越界归一化；在 `tests/test_services.py` 增加 schema 用例并运行通过
- [x] 3.2 修改 `TopicService` 渲染逻辑，只向模板传 `index/title/source/published_at`，并新增测试断言假 LLM 收到的提示词包含标题与序号、不包含信号 URL 或正文
- [x] 3.3 更新 `backend/app/prompts/topic_selection.md`：删除热度字段，加入信号序号与讨论度评分/理由要求，保留 `count/domain/platforms/hot_signals/exclude_titles` 变量；用一次假 LLM 渲染测试确认模板可正常渲染

## 4. 讨论度筛选与信号关联

- [x] 4.1 在 `TopicService._generate_candidates()` 中实现讨论度过滤与最多两次补生成，最终不足 5 个时报 `ValidationError`；测试覆盖「首批含低分候选被替换」与「模型持续低分时报错」并运行通过
- [x] 4.2 落库时为每个候选只保存其 `hot_signal_index` 指向的一条信号（越界则为空），修复共用前 5 条信号的问题；测试断言两个候选的 `hot_signals` 分别对应各自序号
- [x] 4.3 为 `Topic` 模型新增 `discussion_score`（float，默认 0）与 `discussion_reason`（text，默认空串）两列，生成 Alembic 迁移并对现有数据库执行 `alembic upgrade head`，运行 `alembic check` 确认模型与迁移一致
- [x] 4.4 更新 `backend/app/api/serializers.py` 的 `topic_payload`，输出 `discussion_score` 与 `discussion_reason`（缺省为 0/空串），运行 `pytest tests/test_api.py -q` 确认推荐接口响应字段

## 5. 选定后抓取正文

- [x] 5.1 新建 `backend/app/core/web.py`，把 `UrlFetcher` 从 `research/tools.py` 迁入并在原模块 re-export；运行 `pytest tests/test_services.py tests/test_api.py -q` 确认无回归
- [x] 5.2 新建 `backend/app/article_generation/topic_selection/articles.py` 的 `ArticleContentFetcher`：按 `content_selector` → `<article>` → 文本密度 → `<body>` 顺序提取正文、压缩空白、按 `topic_article_max_chars` 截断；新增单元测试覆盖四种提取路径与截断
- [x] 5.3 在 `TopicService.select()` 提交后抓取关联信号正文，按 `normalize_url` 查重后写入 `Source(added_by="topic", snippet=正文)`，返回 `source_fetch`；测试覆盖成功入库、重复链接复用、robots/超时失败仍确认成功三种场景
- [x] 5.4 更新 `backend/app/api/topics.py` 两个选定端点返回 `source_fetch`，并在 `tests/test_api.py` 断言成功与失败响应结构；运行 `pytest tests/test_api.py -q`

## 6. 研究阶段复用预抓取来源

- [x] 6.1 修改 `ResearchService.run()` 清理条件为保留 `user` 与 `topic` 来源，并收集现有 `dedupe_key`；测试断言重跑研究后 `topic` 来源仍在
- [x] 6.2 修改 `_persist_deep_sources()` 与普通搜索路径，跳过已存在 URL 并把复用来源纳入事实引用映射；测试覆盖「预抓取链接不再新建」「事实引用指向复用来源」两个场景
- [x] 6.3 确认 `topic` 来源的正文（`snippet`）进入研究提示词参数；测试断言假 LLM 收到的来源内容包含预抓取正文，运行 `pytest tests/test_services.py -q`

## 7. 前端展示

- [x] 7.1 更新 `frontend/src/types/index.ts`：话题增加 `discussion_score`、`discussion_reason`，选定响应增加 `source_fetch`，运行 `npm run build` 确认类型通过
- [x] 7.2 更新 `TopicPanel.tsx`：候选卡片展示讨论度分数/理由与关联信号外链，选定后展示「已抓取正文」或失败原因；新增/更新 `TopicPanel.test.tsx` 并运行 `npm test -- TopicPanel`
- [x] 7.3 更新 `frontend/src/lib/api.ts` 的 `selectTopic` 返回类型（不改调用方式），运行 `npm run lint && npm test` 确认无回归

## 8. 文档

- [x] 8.1 新增 `docs/prompts.md`：列出 `topic_selection.md` 的变量、讨论度设计说明、修改步骤、生效时机与示例；对照模板逐一核对变量名
- [x] 8.2 更新 `README.md` 配置表与功能概览（RSS/HTML 信源、标题级选题、选定抓取），并核对文档中的命令可执行

## 9. 集成验证

- [x] 9.1 运行后端全量 `pytest -q` 与前端 `npm run lint && npm test && npm run build`，全部通过
- [x] 9.2 手动冒烟：以默认量子位 RSS 推荐 5 个候选，确认响应只含标题级字段、讨论度齐全；选定一个候选并确认 `source_fetch.ok` 与来源入库；随后启动研究阶段确认预抓取来源保留且未被重复抓取

## Workflow follow-up

- 归档前先归档基础变更 `add-article-autopilot`（本变更的 topic-selection/research 是 MODIFIED 增量，主规格不存在时归档会被拒绝）。
- 完成评审后归档本变更并确认主规格已合并。
