# Proposal

## Why

当前 AI 智能选题只接受逗号分隔的 RSS 地址，无法接入 HTML 列表页；推荐时虽然只传标题，但没有把「标题优先、正文按需」固化为可验证的行为，也没有在用户选定后抓取对应文章，导致选题缺乏讨论度依据、后续研究重复抓取。选题提示词也缺少面向讨论度的设计与编辑说明，不便于持续调优。

## What Changes

- 新增可配置热点信源：支持 RSS/Atom 与 HTML 列表页两种类型，HTML 来源可配置标题/链接选择器；单个来源失败不影响其他来源，按标题去重并按配置限制数量。
- 默认仅启用 `https://www.qbitai.com/feed`（量子位 RSS），保留 `APP_HOT_TOPICS_FEEDS` 兼容写法。
- 选题推荐阶段只向模型提供文章标题、来源、发布时间与信号序号，不传正文；模型必须为每个候选关联一个热点信号序号。
- 选题提示词改为讨论度导向：优先有争议、有真实利益相关方、能引发读者讨论的角度，并在候选中输出讨论度评分与理由。
- 用户选定候选后，若该候选关联了文章链接，立即抓取并解析正文，保存为可复用的资料来源；抓取失败不阻断选题确认。
- 资料研究阶段保留并复用选题阶段预抓取的来源，按 URL 去重，避免重复抓取与重复计费。
- 选题提示词存放在 `backend/app/prompts/topic_selection.md`，新增 `docs/prompts.md` 说明可编辑变量、修改方式与生效时机。

## Capabilities

### New Capabilities

- `article-generation/topic-sources`: 获取并解析 RSS/Atom 与 HTML 热点信源，提供标题级信号，并在需要时抓取单篇文章正文。

### Modified Capabilities

- `article-generation/topic-selection`: 推荐输入限制为标题级信号、候选需关联热点信号、讨论度导向、选定后按需抓取正文，以及提示词可维护性。
- `article-generation/research`: 保留并复用选题阶段已抓取的来源，与检索结果统一去重。

## Impact

- 后端：`topic_selection/hot_topics.py`、`topic_selection/service.py`、新增 HTML/正文解析模块、`prompts/topic_selection.md`、`schemas/artifacts.py`、`api/topics.py`、`api/serializers.py`、`research/service.py`、`core/config.py`。
- 数据：`Source.added_by` 增加 `topic` 取值；`TopicCandidate` 增加信号序号与讨论度字段；`topics` 表新增 `discussion_score`、`discussion_reason` 两列（Alembic 迁移），以便前端刷新后仍能展示讨论度。
- 依赖：新增 HTML 解析依赖（BeautifulSoup/soupsieve）。
- 前端：选题候选展示讨论度与关联热点，选定时提示正文抓取结果；无破坏性接口变更，仅新增响应字段。
- 配置：`.env.example` 默认写入量子位 RSS；新增 HTML 来源配置说明。
- 测试：RSS/HTML 解析、标题-only 提示词、讨论度排序、选定抓取、研究阶段复用与去重。
