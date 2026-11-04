# Proposal

## Why

当前技能管理只能浏览、编辑内容、启停和绑定写作阶段：无法在页面创建或删除技能；技能清单强制要求 `version` 与 `applies_to`，与市面通用的 Agent Skills（`SKILL.md` + YAML frontmatter）规范不一致；除写作外，绑定到其他阶段的技能不会进入对应 Agent，用户以为生效但实际无效。需要把技能管理补成完整的增删改查，并让“按阶段绑定 + 只加载当前阶段技能”成为统一机制。

## What Changes

- 技能格式对齐 Agent Skills 通用规范：仅要求 `name`、`description`；`version` 可选；支持 `license`、`compatibility`、`allowed-tools`、`metadata` 与 `references/scripts/assets` 资源目录；保留 `applies_to` 作为兼容扩展。
- 新增技能创建与删除接口及前端操作：创建时按标准生成 `skills/<slug>/SKILL.md`；删除时移除数据库记录与绑定，并把技能目录移动到 `data/skill-trash/` 以便恢复。
- 编辑改为维护完整 `SKILL.md`（frontmatter + 正文），保存时校验标准字段并记录版本；技能详情返回资源文件列表。
- 绑定不再受 `applies_to` 限制，由用户决定技能关联到哪些阶段；仅允许绑定到实际调用 LLM 的六个阶段（选题、资料搜索、大纲、写作、标题优化、审核）。
- 运行时按阶段渐进加载技能：只把当前阶段绑定且启用的技能正文注入该阶段 Agent（含 deep research agent），未绑定技能不进入任何 Agent 上下文；写作阶段行为保持不变。
- 前端技能页补齐新建、删除、标准格式提示、资源列表与按阶段分组的绑定操作；绑定阶段选择只展示可注入的六个阶段。
- 更新 `docs/skills.md` 与内置示例技能，使其符合标准格式并演示按阶段绑定。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `skill-system`: 技能发现/校验改为 Agent Skills 标准；新增创建、删除与资源读取；阶段绑定由用户控制且覆盖全部 LLM 阶段；明确渐进加载与注入边界。

## Impact

- 后端：`app/skills/loader.py`、`registry.py`、`manager.py`、`app/api/skills.py`、`app/api/schemas.py`、`app/api/serializers.py`、`app/seed.py`；`topic_selection`、`research`、`outline`、`title_optimization`、`review` 服务与 `workflow/nodes.py` 的注入接线；research deep agent 系统提示。
- 前端：`SkillsPage.tsx`、`types/index.ts`、`lib/api.ts`、`lib/labels.ts` 与技能页测试。
- 数据：不新增数据库列或迁移；沿用 `skills` / `skill_versions` / `skill_bindings`，删除通过级联清理。
- 文档与内置技能：`docs/skills.md`、`skills/writing-style-tech-review/SKILL.md`、`README.md` 的相关说明。
- 兼容性：缺少 `version`/`applies_to` 的标准技能可直接加载；旧技能继续可用，`entry` 等旧字段仍兼容。
- 归档顺序：主规格 `skill-system` 尚在未归档的 `add-article-autopilot` 变更中，本变更的 MODIFIED delta 需在该基础变更归档后才能归档。
