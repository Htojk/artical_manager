# Design

## Context

`SkillLoader` 目前要求 `name/description/version`，且 `entry` 逻辑重复；`SkillManager` 已支持同步、启停、绑定、编辑与版本，但 `bind()` 会拒绝不在 `applies_to` 中的阶段，`render_for_stage()` 只有 `WritingService` 调用。前端技能页只能查看、编辑、启停和绑定，没有创建/删除入口。六个生成阶段会调用 LLM（选题、资料搜索、大纲、写作、标题优化、审核）；排版与发布不调用 LLM。详见 `proposal.md` 与 `specs/skill-system/spec.md`。

## Goals / Non-Goals

**Goals:**

- 让标准 Agent Skills 目录可直接加载，同时保持旧技能可用。
- 在 UI/API 完成技能创建、读取、编辑、删除的闭环，删除可恢复。
- 把“用户按阶段绑定 → 只加载当前阶段技能正文”统一到六个 LLM 阶段，包括 deep research agent。
- 保持技能文件系统为事实来源，数据库只做索引、版本与绑定。

**Non-Goals:**

- 不做 ZIP/远程技能市场导入导出，不做技能目录内资源文件的在线编辑。
- 不新增数据库列或迁移；不引入多用户权限。
- 不为排版/发布阶段注入技能（这两个阶段不调用 LLM）。
- 不改变写作阶段现有的技能模板变量与默认风格回退行为。

## Decisions

### 1. 标准兼容采用“最小必填 + 扩展保留”

- `REQUIRED_FIELDS` 改为 `name`、`description`；`version` 默认 `1.0.0`。
- 解析 `metadata`（其中 `display_name` 用于列表展示）、`license`、`compatibility`、`allowed-tools`；原始 `SKILL.md` 始终完整保留在 `content`，未知字段不会丢失。
- 保留 `applies_to`、`entry`、`files` 作为兼容扩展：`applies_to` 仅作为 UI 推荐提示，不再限制绑定。
- 校验 `name <= 64`、`description <= 1024`；`SkillInfo.name` 存展示名，新增 `standard_name` 保存 frontmatter 原始 `name`。
- 备选方案：严格只接受标准字段并让旧技能失效。会破坏内置技能与已有用户目录，放弃。

### 2. slug 是稳定标识，创建由后端生成标准文件

- 目录名即 slug；创建接口接收 `slug`、`display_name`、`description`、`content`（正文）、`version`、`applies_to`。
- 后端校验 slug 匹配 `^[a-z0-9]+(?:-[a-z0-9]+)*$`（≤64），组合标准 frontmatter：`name: <slug>`、`description`、`version`、`applies_to`、`metadata.display_name`，写入 `skills/<slug>/SKILL.md`。
- 编辑接口接收完整 `SKILL.md`（frontmatter + 正文），校验后始终写回 `skills/<slug>/SKILL.md`；slug 与目录不可通过编辑改变。
- 备选方案：前端拼 frontmatter。校验分散在两端，放弃。

### 3. 删除采用可恢复的回收目录

- 删除时先校验目标目录解析后位于技能根目录内，再把目录移动到 `data/skill-trash/<slug>-<timestamp>-<rand>/`，然后删除数据库技能记录（级联版本与绑定）。
- 目录已不存在时只清理数据库记录。
- 备选方案：直接 `rmtree`。不可逆且误操作代价高，放弃。
- 不自动删除磁盘上“消失”的技能数据库记录，避免外部临时移动目录造成绑定丢失；由显式删除或下次同步处理。

### 4. 绑定由用户控制，阶段白名单集中定义

- 新增 `SKILL_STAGE_KEYS`（选题、资料搜索、大纲、写作、标题优化、审核），后端 `bind()` 校验该集合，移除 `applies_to` 判断。
- `applies_to` 继续在列表/详情展示为“建议阶段”，前端绑定下拉展示全部技能并标注建议，但不做禁用。
- 同一 `(stage, skill_id)` 仍唯一，重复绑定走 upsert，保留现有行为。

### 5. 渐进加载通过阶段系统提示组合实现

- `SkillManager` 增加 `system_prompt(stage, base) -> str`：查询该阶段绑定，按顺序加载已启用且有效的技能正文，追加到基础系统提示；无绑定则原样返回。
- 六个服务增加可选 `skills: SkillManager | None` 参数，调用 `self.skills.system_prompt(Stage.X, SYSTEM_PROMPT)`。`workflow/nodes.py` 在每个阶段回调里用当前 `session` 构造 `SkillManager(session, self.ctx.skill_registry)` 并传入。
- 选题推荐接口由 API 层传入同一个 manager，保证手动触发与工作流一致。
- `DeepResearchRunner` 增加可选 `system_prompt` 参数；节点在资料搜索阶段用 skill manager 组合后传入，普通 `ResearchService.run()` 的两条 LLM 路径也使用组合后的系统提示。
- 写作阶段沿用现有 `WritingService._injection()` 与 `writing.md` 的 `{{ skills }}`，不重复注入系统提示；它本身已经只读取写作阶段绑定。
- 备选方案：在 `LLMService.structured()` 统一注入。会让自进化等非生成调用也套用技能，且难以按 session 取绑定，放弃。

### 6. 详情返回资源清单但不自动注入

- `SkillInfo` 增加 `resources: list[dict]`（相对路径、字节数），由技能目录递归扫描得到；跳过 `SKILL.md` 与隐藏文件，路径限制在技能目录内。
- 详情接口返回 `resources`；正文注入仍只使用 `SkillInfo.content`（`SKILL.md` 正文），资源按标准渐进披露由模型在需要时读取。
- 资源只做列表展示，不提供任意文件读取接口，避免路径穿越与密钥泄露风险。

### 7. 前端交互

- 列表卡片保留启停；头部新增“新建技能”对话框（slug、展示名、描述、建议阶段、正文）。
- 详情卡片新增删除按钮与确认对话框；删除成功后清空选择并刷新列表/绑定。
- 绑定面板按阶段分组展示，阶段下拉仅使用 `SKILL_STAGE_KEYS`；添加绑定时展示技能的建议阶段提示。
- 详情展示标准格式说明与资源文件列表；`types`/`api` 增加创建、删除类型与调用。

## Risks / Trade-offs

- [标准技能缺少 `version` 导致数据库版本为空] → loader 默认 `1.0.0`；编辑后仍按 `<version>-<序号>` 生成新版本。
- [旧技能 `name` 为中文，与目录 slug 不一致] → 保留兼容，仅新建时强制 slug 标准；`standard_name` 与展示名分离。
- [删除接口误删用户目录] → 前端二次确认；后端移动到 `data/skill-trash/`；路径校验防止越界。
- [阶段注入遗漏或重复] → 集中常量与 `system_prompt()`；测试覆盖六阶段白名单、未绑定隔离与写作不重复注入。
- [技能正文过长导致 token 超限] → 本次不新增截断，用户可在编辑时控制；后续可按阶段设置字符上限。
- [registry 缓存导致创建/删除后不可见] → 创建、编辑、删除后调用 `registry.reload()`/失效对应缓存；详情以文件为准。

## Migration Plan

1. 更新内置 `skills/writing-style-tech-review/SKILL.md` 为标准 frontmatter（`name` 为 slug，`metadata.display_name` 保留中文展示名），启动时 `sync()` 自动刷新数据库名称与版本。
2. 无数据库迁移；旧技能无需改动即可继续加载。
3. 回滚：代码回退后，技能目录仍为 `SKILL.md` 标准格式，旧 loader 仍可读取（`version` 与 `applies_to` 已存在）；被删除技能可从 `data/skill-trash/` 手工移回 `skills/`。
