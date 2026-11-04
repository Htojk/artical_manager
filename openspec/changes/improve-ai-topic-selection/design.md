# Design

## Context

See `proposal.md` — Why. 现有实现的相关约束：

- `backend/app/article_generation/topic_selection/hot_topics.py` 仅解析 RSS/Atom：`HotSignal` 只有标题、来源、链接、热度；`HotTopicSource` 顺序抓取逗号分隔的 URL，单源失败记录错误后继续，按标题去重并截断。
- `TopicService.recommend()` 已把 `signal.__dict__` 交给 `topic_selection.md`，但每个候选落库时都写入同一批 `signals[:5]`，候选与具体信号没有关联。
- `TopicCandidate` 无讨论度与被引信号字段；`TopicService.select()` 只更新选中状态与文章标题。
- `Source` 无正文字段，已有 `dedupe_key`、`added_by`（`user` / `agent`）；`ResearchService.run()` 开始时删除所有非 `user` 来源。
- `UrlFetcher`（`research/tools.py`）已实现 robots.txt 检查与 200KB 截断，可复用。
- 前端选题面板只展示前 2 条热点信号，无讨论度或抓取结果反馈。
- 提示词由 `PromptLoader` 在每次渲染时从 `settings.prompts_dir` 读取。

## Goals / Non-Goals

**Goals:**

- 新增可配置的 RSS/HTML 信源注册与解析，单源失败隔离，保持既有 `HotTopicSource.fetch()` 调用形状。
- 把「只传标题」固化为可测试的提示词契约，候选与热点信号一一关联。
- 选定候选后抓取正文并以 `Source(added_by="topic")` 持久化，研究阶段保留并复用。
- 提示词与变量说明可被非开发者修改。

**Non-Goals:**

- 不做站内爬虫、登录态抓取、JS 渲染页面或站点地图遍历。
- 不引入向量检索、去重聚类或热度算法；讨论度由模型评分。
- 不改数据库表结构，不新增迁移。
- 不做信源的后台管理页面；配置通过环境变量完成。

## Decisions

### 1. 信源配置：新增 `APP_HOT_TOPIC_SOURCES` JSON，兼容旧的逗号分隔写法

新增 `Settings.hot_topic_sources: str = ""`，内容为 JSON 数组：

```json
[
  {"name": "量子位", "type": "rss", "url": "https://www.qbitai.com/feed"},
  {"name": "示例列表页", "type": "html", "url": "https://example.com/news",
   "item_selector": "article.post", "title_selector": "h2 a", "link_selector": "h2 a"}
]
```

解析规则：

1. `APP_HOT_TOPIC_SOURCES` 非空且可解析为数组时使用它；
2. 否则回退到 `APP_HOT_TOPICS_FEEDS`（每个 URL 视为 `type=rss`，来源名取域名）；
3. 两者都为空或全部条目无效时使用默认 `[{"name": "量子位", "type": "rss", "url": "https://www.qbitai.com/feed"}]`。

`Settings.feed_urls` 保持不变，避免现有测试与调用方破坏。选择 JSON 环境变量而非新增 YAML 文件：与项目现有 `APP_*` 配置方式一致，部署时无需额外挂载文件；代价是 HTML 选择器写在环境变量里可读性一般，因此同时在 `.env.example` 与 `docs/prompts.md` 给出示例。

**Alternatives considered:** 独立 `config/hot_sources.yaml`（可读性好，但与现有配置体系分叉）；数据库表（需要管理界面与迁移，超出本次范围）。

### 2. 目录拆分：`topic_selection/sources/` 放信源实现，`articles.py` 放正文抓取

遵循项目「平级功能各占目录」的约定：

```text
backend/app/article_generation/topic_selection/
  sources/
    __init__.py     # 导出 HotSignal / HotSourceSpec / HotTopicSource
    base.py         # HotSignal、HotSourceSpec、配置解析、标题归一化
    rss.py          # RSS/Atom 解析（迁移自 hot_topics.py）
    html.py         # HTML 列表页解析（BeautifulSoup）
    collector.py    # 多信源编排：顺序抓取、错误隔离、去重、截断
  articles.py       # ArticleContentFetcher：单篇正文抓取与提取
  hot_topics.py     # 兼容层：从 sources 重新导出，保留旧导入路径
  service.py
  prompt_builder.py # 组装信号索引与标题级输入（可选，见决策 4）
```

`hot_topics.py` 保留为薄 re-export，现有测试和 `TopicService` 的导入无需大改。

**Alternatives considered:** 把 HTML 解析塞进 `hot_topics.py`（文件职责混杂，且违反目录约定）。

### 3. HTML 解析用 BeautifulSoup + 内置 `html.parser`

新增依赖 `beautifulsoup4>=4.12`，不引入 `lxml`（Windows 上避免本地编译问题）。解析逻辑：

- 条目：`item_selector`（缺省 `article, li`）。
- 标题与链接：`title_selector`；若配置了 `link_selector` 则从该元素取 `href`，否则取标题元素自身或其最近的 `<a>`。
- 链接用 `urljoin(source_url, href)` 转绝对地址；无标题或 `javascript:`/`#` 链接跳过。
- 发布时间：条目内 `<time datetime>` 或 `time` 文本，缺失则为 `None`。
- 每个信源最多取 `limit_per_source`（默认 20）条，异常统一归类为 `解析失败`。

正文提取（`articles.py`）优先顺序：

1. 信源配置的 `content_selector`；
2. `<article>`；
3. 文本密度启发式：取包含最多 `<p>` 文本的 `div/section`，剔除 `script/style/nav/footer/aside`；
4. `<body>` 全文兜底。

提取结果按 `\n` 合并段落，压缩空白，截断到 `APP_TOPIC_ARTICLE_MAX_CHARS`（默认 4000）。

**Alternatives considered:** readability-lxml（效果更好但依赖重、需要 lxml）；只存标题与链接不抓正文（无法满足研究复用与节省 token 的目标）。

### 4. 标题级输入：`HotSignal.index` + 提示词只渲染允许字段

`HotSignal` 扩展为：`index`（按去重后顺序的 1-based 序号）、`title`、`source`、`url`、`published_at`、`heat`（保留字段，RSS 无热度时为 0）。`TopicService` 渲染提示词时显式构造字典：

```python
{"index": s.index, "title": s.title, "source": s.source, "published_at": s.published_at}
```

不再传 `__dict__`，从结构上保证 URL、正文等不会进入提示词。`hot_topics.md` 模板只遍历这些字段。

`TopicCandidate` 新增：

```python
hot_signal_index: int = Field(default=0, ge=0)
discussion_score: float = Field(default=0, ge=0, le=100)
discussion_reason: str = ""
```

落库时只保存该候选关联的一条信号（`index` 命中时），否则为空列表；修复现有「所有候选共用前 5 条信号」的问题。

讨论度需要持久化才能在前端刷新后继续展示，而 `Topic` 原本没有对应字段。因此给 `topics` 表增加 `discussion_score`（float，默认 0）与 `discussion_reason`（text，默认空串）两列，配套 Alembic 迁移；`topic_payload` 直接输出这两列。此前「无需数据库结构变更」的假设在实现阶段被推翻，已同步更新 proposal。

**Alternatives considered:** 给模型传完整列表再靠提示词约束（无法验证，仍可能夹带正文）。

### 5. 讨论度：模型评分 + 一次定向补生成

提示词要求每个候选给出 `discussion_score` 与 `discussion_reason`，并优先「有争议空间 / 有真实利益相关方 / 有明确对立观点 / 信息足以支撑 1500+ 字」的话题。服务端：

1. 第一次生成后按标题去重，保留 `discussion_score >= 60` 的候选；
2. 不足 5 个时，以已保留候选为 `exclude_titles` 追加一次「补充生成」，提示词强调讨论度门槛；
3. 第二次后仍不足 5 个，再补一次；三次后仍不足则抛 `ValidationError("模型未能生成足够讨论度的候选选题，请重试")`，不返回低讨论度候选。

评分裁剪到 0–100，缺失时按 0 处理（会被补生成替换）。该策略与规格一致，代价是极端情况下多一次模型调用。

**Alternatives considered:** 只排序不补生成（可能凑不满 5 个）；本地规则打分（无法判断讨论度）。

### 6. 选定后抓取：同步抓取、失败不影响确认、存 `Source.snippet`

`TopicService.select()` 完成选题落库与提交后，调用 `ArticleContentFetcher.fetch_for_topic(article_id, topic)`：

- 取 `topic.hot_signals` 的第一条 `url`；无 URL 时返回 `{"ok": False, "reason": "候选未关联文章链接"}`，不视为错误。
- 使用 `UrlFetcher`（robots 检查、超时、200KB 上限）取 HTML，用决策 3 的提取器取正文。`UrlFetcher` 从 `research/tools.py` 迁移到 `core/web.py`（主题阶段不应依赖研究模块），`research/tools.py` 保留 re-export 以兼容现有导入与测试。
- 以 `normalize_url(url)` 查重；已存在则复用（不覆盖用户来源）。
- 新建来源：`added_by="topic"`、`title` 用信号标题（正文提取到 `<title>` 时可覆盖）、`snippet` 存正文前 4000 字、`published_at`、`credibility` 沿用 `assess_credibility`。
- 任何异常只写入返回结构 `{"ok": False, "error": "..."}`，并 `logger.warning`；选题确认不受影响。
- 抓取是同步的，超时默认 15s，避免阻塞过久。

正文放在现有 `snippet` 字段而非新增列：`ResearchOutput`/研究提示词本来就会带上 `source.snippet`，可直接复用；避免迁移。缺点是 UI 里摘要会较长，前端列表截断展示即可。

`select()` 返回新增字段：

```python
{"topic": ..., "article": ..., "source_fetch": {"ok": bool, "source_id": str | None, "title": str, "error": str | None}}
```

**Alternatives considered:** 后台任务异步抓取（确认响应更快，但状态同步与测试复杂）；新增 `Source.content` 列（语义更干净，但需要迁移，且本次提案已声明不改表结构）。

### 7. 研究阶段：保留 `topic` 来源，跨来源按 URL 复用

`ResearchService.run()` 的清理条件从 `added_by != "user"` 改为 `added_by not in ("user", "topic")`。

- 收集现有 `dedupe_key` 集合（含 `topic` 来源）。
- `_persist_deep_sources()`：先按输出内部去重，再与现有集合比对；命中的复用现有 `Source`，不新建；返回的 `created` 列表按输出顺序包含「新建 + 复用」的来源，`index_map` 仍为 1-based 映射，保证事实引用可落到复用来源。
- 普通搜索路径同样跳过已存在 URL，并把复用的来源加入 `created_sources` 供事实提取。
- `topic` 来源的 `snippet`（正文）会随 `source.__dict__` 进入研究提示词，从而减少重复抓取。

**Alternatives considered:** 研究阶段重新抓取所有链接（简单但浪费 token/流量，违背目标）。

### 8. 提示词维护：模板 + `docs/prompts.md`

- 模板：`backend/app/prompts/topic_selection.md`（已存在），只修改内容，不改加载方式。
- 文档：新增 `docs/prompts.md`，列出 `count`、`domain`、`platforms`、`hot_signals`（含 `index/title/source/published_at`）、`exclude_titles` 的含义，说明保存后下一次推荐即生效（`PromptLoader` 每次渲染都读盘），给出讨论度要求的修改示例与注意事项（保留槽位变量，否则渲染为空）。
- `README.md` 的配置表补充 `APP_HOT_TOPIC_SOURCES` 与 `APP_TOPIC_ARTICLE_MAX_CHARS`。

**Alternatives considered:** 把提示词放入数据库并做编辑界面（范围过大）。

### 9. 前端：展示讨论度与关联信号，提示抓取结果

- `types/index.ts`：话题类型增加 `discussion_score`、`discussion_reason`；`Topic` 的 `hot_signals` 复用现有结构。
- `TopicPanel.tsx`：候选卡片展示讨论度分数与理由、关联信号标题（可点击外链）；选定后根据 `source_fetch` 显示「已抓取正文」或「正文抓取失败：…」提示。
- `lib/api.ts`：选定接口返回类型加入 `source_fetch`，不改变调用方式。

## Risks / Trade-offs

- HTML 选择器随站点改版失效 → 单源失败被隔离，错误通过 `hot_errors` 返回；选择器可配置，无需改代码。
- 同步抓取拖慢选题确认 → 15s 超时、单次请求；失败不阻断，后续研究仍可搜索。
- 正文存入 `snippet` 导致来源列表变长 → 前端截断展示；研究提示词获得更多上下文是预期收益。
- 模型虚高讨论度评分 → 提示词给出评分锚点，服务端过滤 <60；仍无法完全避免，后续可在自进化中校准。
- 抓取受 robots.txt 限制 → 明确失败并在响应中说明，不绕过。
- 新增 `beautifulsoup4` 依赖 → 纯 Python + 内置解析器，安装成本低。
- MODIFIED 规格依赖 `add-article-autopilot` 先归档 → 归档本变更前必须先归档基础变更，否则 `openspec archive` 会拒绝；任务中标注顺序。

## Migration Plan

1. 安装依赖：`pip install beautifulsoup4`（同步更新 `backend/.requirements.txt`）。
2. 配置：默认无需改动（未配置时使用量子位 RSS）；如需 HTML 源，设置 `APP_HOT_TOPIC_SOURCES`。
3. 执行 `alembic upgrade head` 新增 `topics.discussion_score` 与 `topics.discussion_reason`；旧数据取默认值 0 与空串。已有来源数据不受影响。
4. 回滚：还原代码与依赖即可。已生成的 `added_by="topic"` 来源在旧版本研究阶段会被删除，无残留风险。
5. 验证：先跑后端 `pytest` 与前端 `lint/test/build`，再用真实 qbitai RSS 手动推荐一次、选定一个候选确认抓取结果。
