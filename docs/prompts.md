# 提示词维护：AI 智能选题

选题提示词放在 `backend/app/prompts/topic_selection.md`，按 Markdown + Jinja2 语法维护。改完保存即可在**下一次推荐请求**生效，不需要重启后端。

## 文件与加载机制

| 项目 | 说明 |
| --- | --- |
| 模板文件 | `backend/app/prompts/topic_selection.md` |
| 加载器 | `backend/app/core/prompts.py` 的 `PromptLoader`（Jinja2 `FileSystemLoader`） |
| 目录配置 | `APP_PROMPTS_DIR`，默认 `backend/app/prompts` |
| 渲染上下文 | `TopicService._generate_candidates()` 每次请求渲染 |
| 未定义变量 | `StrictUndefined`：模板引用了上下文没有的变量会直接报 `prompt_render_failed`，不会静默渲染为空 |

系统提示词不在模板里，而是 `backend/app/article_generation/topic_selection/service.py` 顶部的 `SYSTEM_PROMPT` 常量。修改选题语气或角色定位时，两处都可能需要同步调整。

## 模板变量

| 变量 | 类型 | 说明 |
| --- | --- | --- |
| `count` | `int` | 候选数量，当前固定为 5；推荐接口不接受其他数量 |
| `domain` | `str` | 选题领域/方向。请求未传时依次回退到文章标题、`科技与人工智能` |
| `platforms` | `str` | 目标平台的逗号拼接文本；为空时渲染为 `通用` |
| `hot_signals` | `list[dict]` | 热点信号，仅标题级字段，不含 URL 和正文 |
| `exclude_titles` | `list[str]` | 需要避免重复的标题：用户传入的排除项 + 本轮已生成候选 |

`hot_signals` 每项只有四个字段：

| 字段 | 说明 |
| --- | --- |
| `index` | 1-based 序号，供模型在 `hot_signal_index` 中引用 |
| `title` | 文章标题 |
| `source` | 信源名称（来自 `APP_HOT_TOPIC_SOURCES` 的 `name`） |
| `published_at` | 发布时间字符串，可能为空 |

模板不应要求或展示信号 URL、正文摘要。选题阶段只把标题交给模型，用户选定候选后才抓取正文，这是节省 token 的核心约束。相关测试会断言提示词中不出现信号 URL 或正文标记，例如 `backend/tests/test_services.py` 中的标题级提示词用例。

## 讨论度设计

模板要求模型为每个候选输出：

- `discussion_score`：0–100，衡量「是否有人愿意争论、是否与读者利益相关」。
- `discussion_reason`：一句话说明谁和谁在争什么。
- `hot_signal_index`：关联的热点信号序号；没有关联时填 `0`。

服务端的硬性规则在 `TopicService` 中，模板措辞无法绕过：

- 低于 `MIN_DISCUSSION_SCORE`（60）的候选直接丢弃。
- 每轮最多生成 5 个，最多补生成 `MAX_CANDIDATE_ROUNDS`（3）轮。
- 去重后仍不足 5 个时，推荐接口返回 `ValidationError`，提示「模型未能生成足够讨论度的候选选题，请重试」。

因此调整阈值时，除了改模板里的评分说明，还要同步修改 `service.py` 的常量，二者保持一致，避免提示词建议与后端过滤规则相互矛盾。

## 修改步骤

1. 编辑 `backend/app/prompts/topic_selection.md`。
2. 保持输出契约字段名不变：`title`、`angle`、`rationale`、`target_platforms`、`hot_signal_index`、`discussion_score`、`discussion_reason`。这些字段对应 `backend/app/schemas/artifacts.py` 的 `TopicCandidate`，改名会导致结构化输出解析失败。
3. 若新增模板变量，同时修改 `service.py` 的 `self.prompts.render(...)` 调用并传入值，否则 `StrictUndefined` 会报错。
4. 在 `backend/` 下运行针对性测试：

   ```bash
   pytest tests/test_services.py -q
   ```

5. 打开文章工作台的选题面板，点击「推荐 5 个选题」，检查候选是否满足预期。

## 生效时机

- 推荐请求每次都会通过 `PromptLoader` 渲染模板，保存文件后下一次点击「推荐 5 个选题」即生效。
- 已生成的候选不会因提示词修改而重新生成；需要重新推荐才会应用新模板。
- 不需要重启 FastAPI，也不需要清缓存。

## 渲染示例

假设领域为 `AI 编程工具`、平台为 `wechat, zhihu`、两条热点信号、一个排除标题，渲染结果大致如下（节选）：

```text
你是资深内容策划，擅长把行业变化转化为有讨论度、有人愿意争论的选题。……

领域/方向：AI 编程工具
目标平台：wechat, zhihu

可用热点信号（只提供标题级信息，没有正文）：
- [1] 某公司发布新一代 AI 编程助手（来源：量子位，发布：2026-10-29T09:00:00+08:00）
- [2] 开发者调查：AI 生成代码的维护成本上升（来源：量子位）

请为每个候选填写最主要依据的 `hot_signal_index`（即上面的方括号序号）。……

以下选题已经推荐过，请勿重复：
- 旧候选标题

讨论度要求（重要）：
1. 优先选择有争议空间的话题……
```

模型随后返回结构化候选，服务端按 `discussion_score >= 60` 过滤、去重、补生成，最终落库 5 个候选，并只保留各自 `hot_signal_index` 指向的那一条信号。
