# 技能（Skill）管理与阶段绑定

技能是遵循 Agent Skills 通用格式的 Markdown 规则包。目录名（slug）是技能唯一标识；`SKILL.md` 的 YAML frontmatter 提供元数据，正文是该技能的完整指令。

技能按需加载：只有**绑定到当前阶段且启用**的技能，才会在该阶段调用大模型时注入系统提示；排版、发布等不调用大模型的阶段不参与绑定。`references/`、`scripts/`、`assets/` 中的资源只做清单展示，不会自动进入提示词。

## 目录结构

```text
skills/
  writing-style-tech-review/
    SKILL.md            # 必需
    references/         # 可选：参考文档
    scripts/            # 可选：辅助脚本
    assets/             # 可选：模板、图片等
```

## SKILL.md 格式

最小合法技能只需要 `name` 与 `description`：

```markdown
---
name: data-story
description: 用数据讲故事的写作规范：每个结论配一个数字。
---

# 数据故事

## 要求

- 每个核心结论至少配一个可核验的数字。
- 先描述数据，再给出解释。
```

完整字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 标准技能名，最多 64 字符；建议与目录 slug 一致 |
| `description` | 是 | 一句话说明技能用途，最多 1024 字符 |
| `version` | 否 | 版本号，缺省 `1.0.0`；保存/回滚时写入版本记录 |
| `license` | 否 | 许可证标识，如 `MIT` |
| `compatibility` | 否 | 兼容性说明 |
| `allowed-tools` | 否 | 允许使用的工具列表（仅元数据） |
| `metadata` | 否 | 自定义元数据对象 |

本平台扩展字段：

| 字段 | 说明 |
| --- | --- |
| `metadata.display_name` | 页面展示名称；缺省回退到 `name` |
| `applies_to` | 建议阶段列表，仅用于界面提示，不限制实际绑定 |
| `entry` | 旧格式入口文件，缺省 `SKILL.md`（兼容保留） |

`name`/`description` 缺失、字段超长、`SKILL.md` 缺失或 YAML 无法解析时，技能标记为 `invalid`：页面可见但不会注入，也不会中断服务启动。旧的 `name` 为中文、`version`/`applies_to` 必填的技能仍可正常加载；把中文名迁移到 `metadata.display_name` 即可完全符合标准。

## 创建、导入、编辑、删除

### 页面操作

1. 「技能管理」→「新建技能」。
2. 填写 slug（小写字母、数字、连字符，最多 64 字符）、展示名称、描述、建议阶段与正文。
3. 提交后后端生成标准 frontmatter（`name: <slug>`、`description`、`version`、可选 `metadata.display_name` 与 `applies_to`），写入 `skills/<slug>/SKILL.md`，并记录初始版本。
4. 右侧编辑器展示完整 `SKILL.md`（frontmatter + 正文）；修改后「保存技能内容」会校验 frontmatter、写回文件并追加版本记录。slug/目录名不可通过编辑修改。
5. 「删除技能」会把目录移动到 `data/skill-trash/<slug>-<时间戳>-<随机串>/`，同时删除数据库记录、版本与绑定。需要恢复时把目录移回 `skills/` 并刷新。

### API

```text
GET    /api/skills                         技能列表（不含正文与资源）
POST   /api/skills                         创建技能（201）
POST   /api/skills/import                  导入 ZIP 技能包（201）
GET    /api/skills/{slug}                  详情：完整 SKILL.md、版本、资源清单
PUT    /api/skills/{slug}/content          编辑完整 SKILL.md 并生成版本
POST   /api/skills/{slug}/toggle           启用/停用
POST   /api/skills/{slug}/rollback/{id}    回滚到指定版本
DELETE /api/skills/{slug}                  删除并移入回收目录（204）
GET    /api/skill-bindings?stage=writing   绑定列表
POST   /api/skill-bindings                 新增/更新绑定（201）
DELETE /api/skill-bindings/{id}            解除绑定（204）
```

创建请求示例：

```json
{
  "slug": "data-story",
  "display_name": "数据故事",
  "description": "用数据讲故事的写作规范",
  "content": "## 要求\n每个结论配一个数字。",
  "applies_to": ["writing", "review"]
}
```

重复 slug 返回 `409`；非法 slug、空描述或非法阶段返回 `422`。

## 导入 ZIP 技能包

「技能管理」→「导入 ZIP」，或在 API 上传 `multipart/form-data`：

```bash
curl -X POST http://127.0.0.1:8000/api/skills/import \
  -F "file=@data-story.zip" \
  -F "slug=data-story"        # 可选；留空则自动推断
```

支持的压缩包结构（`SKILL.md` 必须唯一，大小写不敏感）：

```text
data-story.zip
└── data-story/               # 单一顶层目录（推荐）
    ├── SKILL.md
    ├── references/
    ├── scripts/
    └── assets/
```

或直接以技能根目录为压缩包根：

```text
data-story.zip
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

行为说明：

- 以 `SKILL.md` 的父目录为技能根，提取该前缀下的全部文件并剥离外层目录；`SKILL.md` 之外的散落文件（如压缩包根部的 `README.md`）会被忽略。
- `__MACOSX/`、`.DS_Store` 与任何隐藏路径会被跳过；带 GBK 文件名的旧压缩包会按 UTF-8 → GBK 回退解码。
- 导入成功后立即出现在技能列表，并记录初始版本（说明为“导入 zip：<文件名>”）；不会自动绑定到任何阶段。
- slug 解析顺序：显式 `slug` → `SKILL.md` 所在目录名 → ZIP 文件名；结果规范为小写字母、数字与连字符，最长 64 字符。无法推断时（如纯中文文件名）需显式提供 `slug`。
- 同名技能或已有目录不会被覆盖，返回 `409`；如需替换，先删除旧技能（移入 `data/skill-trash/`）再导入。
- 安全限制：上传 ≤ 20 MB、解压后 ≤ 50 MB、成员 ≤ 500 个；拒绝绝对路径、`..`、盘符、符号链接与加密条目，超限返回 `413`，格式或技能内容无效返回 `422`。导入先落到技能根目录内的隐藏临时目录，校验通过后才原子移动到 `skills/<slug>/`，失败不会留下半成品。

响应包含完整的技能详情，并额外返回 `imported_files`（落盘文件数）与 `source_filename`。

## 阶段绑定

可绑定技能的六个 LLM 阶段：

| 阶段 key | 名称 |
| --- | --- |
| `topic_selection` | 选题 |
| `research` | 资料搜索 |
| `outline` | 大纲生成 |
| `writing` | 写作 |
| `title_optimization` | 标题优化 |
| `review` | 审核 |

- 绑定记录包含 `stage`、`skill_id`、`order`、`enabled`；同一阶段可绑定多个技能，按 `order` 升序拼接。
- `applies_to` 只是建议，不限制绑定：例如可以显式把「科技评论文风」绑定到审核阶段。
- 排版（`formatting`）与发布（`publishing`）不调用大模型，拒绝绑定并返回 `422`。
- 只有当前阶段的启用绑定会进入系统提示；其他阶段绑定的技能不会出现在本次调用中。

## 加载与热更新

- 启动时扫描 `APP_SKILLS_DIR`（默认 `skills/`），同步到 SQLite。
- 注册表按技能目录内所有文件的 `mtime` 缓存；修改 `SKILL.md` 或新增资源后，下一次读取自动重载，无需重启。
- 内置 `writing-style-tech-review` 使用标准 frontmatter（`name` 为 slug，`metadata.display_name` 保留中文名），首次启动会注册并默认绑定写作阶段，可作为模板复制。
- 目录缺失但数据库仍有记录时，同步会标记为 `invalid`；删除接口也可直接清理这类记录。

## 版本与回滚

- 创建记录初始版本；每次保存/回滚追加 `skill_versions` 快照（版本号形如 `1.0.0-2`）。
- 回滚会恢复旧 `SKILL.md` 内容、展示名、版本与建议阶段，并生成新的版本记录，历史不丢失。
- 草稿的 `skill_snapshot` 记录生成时实际使用的技能 slug/name/version。

## 降级行为

- 绑定的技能被停用、文件删除或解析失败：跳过该技能，继续使用同阶段其他有效技能。
- 写作阶段没有任何有效技能：注入默认风格（结论先行、短句、证据优先、结尾可执行建议），并在草稿 `note` 写入“技能降级: <slug>: <原因>”。
- 技能问题不会导致写作失败；降级原因可从 API 返回的 `degraded_skills` 查看。
