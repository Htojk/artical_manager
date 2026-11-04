# Proposal

## Why

当前技能管理只能新建单文件正文或手工把目录放入 `skills/`。标准 Agent Skills 往往以完整技能包分发（`SKILL.md` + `references/` + `scripts/` + `assets/`），逐个文件复制容易漏文件、破坏目录结构，也无法在页面完成导入。需要支持直接上传 ZIP 技能包并安全落盘。

## What Changes

- 新增 `POST /api/skills/import`：接收 `multipart/form-data` 的 ZIP 文件与可选 `slug`，返回导入后的技能详情与导入文件数。
- 安全解压：手工写入成员而非 `extractall`；拒绝绝对路径、`..`、盘符、符号链接与加密条目；限制压缩包大小、解压总大小与文件数。
- 结构识别：支持 `SKILL.md` 位于压缩包根目录或单一顶层目录；存在多个 `SKILL.md` 时报错；`skill.md` 大小写不敏感并规范为 `SKILL.md`；顶层目录外的散落文件忽略。
- slug 解析：显式 `slug` 优先，其次技能根目录名，最后 ZIP 文件名；统一规范为小写连字符；与已有 slug/目录冲突时返回 `409`，不覆盖。
- 原子安装：先解压到技能根目录下的隐藏临时目录并复用现有 loader 校验，通过后重命名到 `skills/<slug>/`；失败时清理临时目录、数据库记录与已移动目录。
- 前端「技能管理」页新增「导入 ZIP」对话框：选择 `.zip`、可选 slug 覆盖、展示接受的目录结构；成功后选中新技能并刷新列表。
- 更新 `docs/skills.md`、`README.md` 与依赖清单（新增 `python-multipart`）。
- 补充后端服务/API 测试与前端组件测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `skill-system`: 新增技能包 ZIP 导入能力（安全解压、结构识别、slug 解析、冲突处理与原子安装）。

## Impact

- 后端：新增 `app/skills/importer.py`；修改 `app/skills/manager.py`、`app/api/skills.py`、`app/core/errors.py`（`413`）；依赖增加 `python-multipart`。
- 前端：`SkillsPage.tsx`、`types/index.ts`、`lib/api.ts` 与 `SkillsPage.test.tsx`。
- 数据：不新增数据库列或迁移；导入成功后按现有 `skills` / `skill_versions` 记录，初始版本说明为“导入 zip”。
- 兼容性：不影响现有创建、编辑、删除与绑定流程；未使用 `python-multipart` 前启动不受影响，安装依赖后生效。
- 归档顺序：主规格 `skill-system` 仍在未归档的 `add-article-autopilot` 变更中，需在其归档后归档本变更；与 `improve-skill-management` 的 delta 可并存。
