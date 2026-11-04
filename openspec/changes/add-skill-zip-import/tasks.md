# Tasks

## 1. 后端导入服务

- [x] 1.1 新建 `backend/app/skills/importer.py`：实现 ZIP 成员名解码、路径校验、符号链接/加密条目拒绝、隐藏与元数据过滤、单 `SKILL.md` 根目录识别、分块解压与 20 MB / 50 MB / 500 文件限制；补充单元测试覆盖根目录包、单顶层目录包、中文文件名、`skill.md` 大小写与 `__MACOSX` 过滤
- [x] 1.2 为路径穿越、绝对路径、盘符、符号链接、加密条目、缺失/重复 `SKILL.md`、超限场景补充测试，断言抛出 `ValidationError` 或 `PayloadTooLargeError` 且临时目录无残留
- [x] 1.3 在 `backend/app/core/errors.py` 增加 `PayloadTooLargeError`（`413`），并确认现有错误中间件输出 `{code,message,details}`
- [x] 1.4 在 `SkillManager` 实现 `import_skill(data, filename, slug)`：slug 解析与校验、数据库/目录冲突 `409`、隐藏临时目录解压与 loader 校验、原子重命名、`sync()`、初始版本“导入 zip”、失败清理；补充成功、显式 slug、文件名回退、非法 slug、重复 slug、无效 frontmatter 测试
- [x] 1.5 更新 `backend/requirements.txt` 增加 `python-multipart==0.0.20` 并安装；运行 `pytest tests/test_skills.py -q`

## 2. 技能 API

- [x] 2.1 在 `backend/app/api/skills.py` 增加 `POST /api/skills/import`（`201`）：接收 `file` 与可选 `slug`，限制读取大小，返回技能详情、`imported_files` 与 `source_filename`
- [x] 2.2 在 `backend/tests/test_api.py` 增加导入成功（资源落盘、列表可见、版本说明）、重复 slug `409`、非 ZIP/缺入口 `422`、缺文件字段 `422` 的用例并运行 `pytest tests/test_api.py -q`

## 3. 前端导入

- [x] 3.1 更新 `frontend/src/types/index.ts` 与 `frontend/src/lib/api.ts`：新增 `SkillImportResult` 与 `importSkill(file, slug)`（`FormData`，不设置 `Content-Type`）
- [x] 3.2 在 `SkillsPage.tsx` 增加「导入 ZIP」按钮与对话框（文件选择、可选 slug、结构与限制说明、错误提示、成功文件数提示），成功后刷新列表/绑定并选中新技能
- [x] 3.3 扩展 `frontend/src/pages/SkillsPage.test.tsx` 覆盖导入对话框提交（`FormData` 含 file/slug）、成功后选中技能与错误展示；运行 `npm test -- SkillsPage`

## 4. 文档

- [x] 4.1 在 `docs/skills.md` 增加“导入 ZIP 技能包”章节：支持的目录结构、slug 解析顺序与冲突、安全限制、错误码、API/curl 示例；核对字段与实现一致
- [x] 4.2 更新 `README.md` 技能能力说明与依赖说明，补充 ZIP 导入入口

## 5. 集成验证

- [x] 5.1 运行后端全量 `pytest -q` 与前端 `npm run lint && npm test && npm run build`，全部通过
- [ ] 5.2 手动冒烟：在技能页导入含 `references/scripts/assets` 的 ZIP，确认列表/详情/资源显示；再次导入同名返回 409；导入非法 ZIP 不产生目录（需重启后端后由用户在浏览器确认）

## Workflow follow-up

- 归档前先归档基础变更 `add-article-autopilot`（`skill-system` 主规格来源），再按顺序归档 `improve-skill-management` 与本变更。
