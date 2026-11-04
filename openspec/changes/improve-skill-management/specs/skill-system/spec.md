# Spec Delta

## MODIFIED Requirements

### Requirement: 技能发现与清单
系统 SHALL 从配置的技能目录中发现技能，每个技能 MUST 以 `SKILL.md` 作为入口；frontmatter MUST 包含通用 Agent Skills 规范的 `name` 与 `description`，`version`、`license`、`compatibility`、`allowed-tools`、`metadata` 为可选字段。`applies_to` 作为兼容扩展保留，仅用于提示推荐阶段，不再作为绑定限制。技能目录名作为稳定标识（slug），展示名称优先取 `metadata.display_name`，缺失时取 `name`。

#### Scenario: 发现标准技能
- **WHEN** 技能目录中存在仅含 `name` 与 `description` 的 `SKILL.md`
- **THEN** 该技能出现在技能列表中，状态为可用，版本使用默认值

#### Scenario: 发现带扩展字段的旧技能
- **WHEN** 技能 frontmatter 同时包含 `version`、`applies_to` 或旧 `entry` 字段
- **THEN** 系统仍能识别该技能，并保留这些字段的现有展示与兼容行为

#### Scenario: 展示名称回退
- **WHEN** 标准技能的 `metadata.display_name` 缺失
- **THEN** 技能列表展示 frontmatter 中的 `name`，slug 仍为目录名

### Requirement: 技能校验与错误隔离
系统 SHALL 在加载时校验技能入口与标准 frontmatter。缺少 `name` 或 `description`、缺少 `SKILL.md`、YAML 无法解析时，该技能 MUST 标记为无效并给出原因，不得导致启动失败或影响其他技能。`name` 长度 MUST NOT 超过 64 个字符，`description` MUST NOT 超过 1024 个字符。

#### Scenario: 缺少标准必填字段
- **WHEN** 某技能有 `name` 但缺少 `description`
- **THEN** 该技能被标记为无效并显示缺失字段，其他技能正常工作

#### Scenario: 缺少入口文件
- **WHEN** 技能目录中不存在 `SKILL.md`
- **THEN** 系统标记该技能不可用，并记录原因

#### Scenario: 无效技能不参与注入
- **WHEN** 某个已绑定技能在磁盘上变为无效
- **THEN** 该阶段跳过该技能并记录降级原因，生成流程继续

### Requirement: 按阶段绑定技能
系统 SHALL 允许用户把任意可用技能绑定到实际调用 LLM 的阶段：选题、资料搜索、大纲、写作、标题优化、审核。绑定 MUST NOT 受 `applies_to` 限制；排版与发布阶段不提供技能绑定。同一阶段可绑定多个技能，并按用户指定顺序组合。重复绑定同一阶段与技能时 MUST 更新原绑定。

#### Scenario: 绑定到审核阶段
- **WHEN** 用户把原本只声明 `applies_to: [writing]` 的技能绑定到审核阶段
- **THEN** 绑定成功，审核阶段后续生成加载该技能

#### Scenario: 拒绝非 LLM 阶段
- **WHEN** 用户尝试把技能绑定到排版或发布阶段
- **THEN** 系统拒绝绑定并返回明确错误

#### Scenario: 多技能按序组合
- **WHEN** 写作阶段绑定了顺序为 1 与 2 的两个技能
- **THEN** 两个技能正文按顺序进入写作上下文

### Requirement: 技能内容注入
运行时系统 SHALL 只把当前阶段绑定且启用的技能正文注入该阶段 Agent，包括普通研究与 deep research agent；未绑定到当前阶段的技能 MUST NOT 进入该 Agent 的系统提示或用户上下文。绑定或技能停用、失效时 MUST 跳过并记录降级原因。`references/`、`scripts/`、`assets/` 中的资源默认不注入，只有正文中的明确引用才由模型按需读取。

#### Scenario: 阶段隔离
- **WHEN** 某技能只绑定到写作阶段
- **THEN** 选题、大纲、审核等阶段的提示词不包含该技能正文

#### Scenario: 停用技能不再生效
- **WHEN** 用户停用某个已绑定技能或停用其绑定
- **THEN** 后续生成不再包含该技能内容

#### Scenario: 资料搜索阶段注入
- **WHEN** 用户把调研规范技能绑定到资料搜索阶段
- **THEN** 普通研究与 deep research agent 均按该技能要求执行

### Requirement: 技能管理与预览
系统 SHALL 提供技能的查看、创建、编辑、删除、启用/停用、版本查看与效果预览能力。列表只返回元数据；详情 MUST 返回完整 `SKILL.md` 内容与资源文件列表。创建 MUST 生成标准 `SKILL.md`；编辑 MUST 校验 frontmatter 并生成新版本。删除 MUST 清理版本、阶段绑定，并把技能目录移动到 `data/skill-trash/` 以便恢复。修改后的技能在下次生成时生效。

#### Scenario: 创建技能
- **WHEN** 用户填写 slug、描述与正文并提交
- **THEN** 系统创建 `skills/<slug>/SKILL.md`，技能出现在列表中且可绑定

#### Scenario: 编辑技能内容
- **WHEN** 用户修改完整 `SKILL.md` 并保存
- **THEN** 下次生成使用修改后的内容，并记录新版本

#### Scenario: 删除技能
- **WHEN** 用户确认删除某技能
- **THEN** 该技能及其绑定从列表与运行时消失，目录被移动到 `data/skill-trash/`

#### Scenario: 重复 slug
- **WHEN** 用户创建的 slug 已存在
- **THEN** 系统拒绝创建并返回冲突错误

## ADDED Requirements

### Requirement: 标准技能资源清单
系统 SHALL 在技能详情中列出 `references/`、`scripts/`、`assets/` 等目录下的文件相对路径与大小，供用户预览和管理。资源路径 MUST 限制在技能目录内，不得通过路径穿越读取外部文件。

#### Scenario: 查看技能资源
- **WHEN** 标准技能包含 `references/checklist.md`
- **THEN** 技能详情返回该资源的相对路径，且默认不把内容加入任何阶段提示词

#### Scenario: 阻止路径穿越
- **WHEN** 请求的资源路径解析后位于技能目录之外
- **THEN** 系统拒绝访问
