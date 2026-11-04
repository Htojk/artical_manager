# Tasks

## 1. 标准技能加载

- [x] 1.1 修改 `backend/app/skills/loader.py`：必填字段改为 `name`/`description`，`version` 缺省为 `1.0.0`，解析 `metadata.display_name`、`license`、`compatibility`、`allowed-tools`，新增 `standard_name`；更新 `backend/tests/test_skills.py` 覆盖最小标准技能、展示名回退与旧字段兼容并运行 `pytest tests/test_skills.py -q`
- [x] 1.2 在 loader 中校验 `name <= 64`、`description <= 1024`，缺少 `SKILL.md`/YAML 错误仍标记无效；补充长度与入口缺失测试并运行通过
- [x] 1.3 让 `SkillInfo` 收集 `references/`、`scripts/`、`assets/` 资源清单（相对路径、字节数，禁止越界路径）；补充资源扫描与隐藏文件测试并运行通过
- [x] 1.4 把 `skills/writing-style-tech-review/SKILL.md` 改为标准 frontmatter（`name` 使用目录 slug，`metadata.display_name` 保留中文名）；测试断言内置技能加载为 valid 且展示名不变

## 2. 技能管理服务

- [x] 2.1 在 `backend/app/core/constants.py` 定义 `SKILL_STAGE_KEYS`（六个 LLM 阶段）；修改 `SkillManager.bind()` 仅校验该集合、移除 `applies_to` 限制；测试覆盖跨建议阶段绑定与拒绝排版/发布
- [x] 2.2 在 `SkillManager` 实现 `create_skill()`：校验 slug 格式与唯一性，组合标准 frontmatter 写入 `skills/<slug>/SKILL.md`，记录初始版本并刷新 registry；测试覆盖创建成功、非法 slug、重复 slug
- [x] 2.3 在 `SkillManager` 实现 `delete_skill()`：路径校验后移动目录到 `data/skill-trash/`，删除数据库记录与级联绑定；测试覆盖移动、目录缺失时清理记录、越界路径拒绝
- [x] 2.4 调整 `edit_content()`：校验完整 `SKILL.md`、始终写回 `SKILL.md`、同步展示名/版本/建议阶段并记录版本；更新回滚路径；测试编辑标准技能与版本回滚
- [x] 2.5 新增 `SkillManager.system_prompt(stage, base)` 组合当前阶段技能正文，无绑定时原样返回；测试覆盖只包含当前阶段、按顺序拼接、停用与失效技能被跳过

## 3. 技能 API

- [x] 3.1 在 `backend/app/api/schemas.py` 增加 `SkillCreate`，在 `serializers.py` 的详情载荷输出 `standard_name`、`resources` 与展示名；运行 `pytest tests/test_api.py -q` 确认现有技能接口响应兼容
- [x] 3.2 在 `backend/app/api/skills.py` 增加 `POST /api/skills`（201）与 `DELETE /api/skills/{slug}`（204），重复 slug 返回 409、非法 slug 返回 422；补充 API 测试并运行通过
- [x] 3.3 更新 `GET /api/skills/{slug}` 返回资源清单与标准字段；补充资源列表断言，确认列表接口不返回正文与资源内容

## 4. 分阶段注入

- [x] 4.1 修改 `TopicService` 支持可选 `SkillManager` 并把技能追加到系统提示，`app/api/topics.py` 推荐接口传入 manager；测试断言绑定选题技能进入 system、未绑定技能不出现
- [x] 4.2 修改 `OutlineService`、`TitleOptimizationService`、`ReviewService` 支持可选 `SkillManager` 并组合系统提示；测试分别断言绑定技能进入对应阶段提示
- [x] 4.3 修改 `ResearchService` 两条 LLM 路径与 `DeepResearchRunner` 使用阶段技能提示；测试覆盖普通研究注入与 deep agent 系统提示包含技能正文
- [x] 4.4 在 `workflow/nodes.py` 为选题、资料搜索、大纲、标题、审核阶段构造 `SkillManager(session, self.ctx.skill_registry)` 并传入服务；运行相关 workflow 测试确认无回归

## 5. 前端技能管理

- [x] 5.1 更新 `frontend/src/types/index.ts`、`lib/api.ts`、`lib/labels.ts`：增加创建/删除类型与调用、`SkillResource`、`standard_name` 与 `SKILL_STAGE_KEYS`；运行 `npm run build` 确认类型通过
- [x] 5.2 在 `SkillsPage.tsx` 增加“新建技能”对话框（slug、展示名、描述、建议阶段、正文）与删除确认对话框，详情展示标准格式说明和资源列表；扩展 `SkillsPage.test.tsx` 覆盖创建与删除并运行 `npm test -- SkillsPage`
- [x] 5.3 将绑定面板按阶段分组，阶段下拉只展示 `SKILL_STAGE_KEYS`，技能选项标注建议阶段；扩展测试覆盖绑定到审核阶段与请求体，运行 `npm run lint && npm test -- SkillsPage`

## 6. 文档

- [x] 6.1 重写 `docs/skills.md`：标准 `SKILL.md` 字段、目录结构、创建/编辑/删除流程、六阶段绑定、渐进加载边界、旧格式兼容与回收目录说明；核对示例字段与实现一致
- [x] 6.2 更新 `README.md` 技能能力说明与文档入口，核对“技能管理”相关命令/步骤可执行

## 7. 集成验证

- [x] 7.1 运行后端全量 `pytest -q` 与前端 `npm run lint && npm test && npm run build`，全部通过
- [x] 7.2 手动冒烟：页面创建标准技能并绑定到审核阶段，确认列表/详情/资源展示、绑定顺序；删除后确认列表消失且 `data/skill-trash/` 存在目录

## Workflow follow-up

- 归档前先归档基础变更 `add-article-autopilot`（本变更的 `skill-system` 是 MODIFIED 增量，主规格不存在时归档会被拒绝）。
- 完成评审后归档本变更并确认主规格已合并。
