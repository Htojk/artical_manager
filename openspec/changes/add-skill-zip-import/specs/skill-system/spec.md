# Spec Delta

## ADDED Requirements

### Requirement: 技能包 ZIP 导入
系统 SHALL 支持通过页面或 API 上传 ZIP 技能包并创建技能。技能包 MUST 包含且仅包含一个 `SKILL.md`（大小写不敏感），其同级或子目录中的 `references/`、`scripts/`、`assets/` 等文件 MUST 原样落盘到 `skills/<slug>/`。系统 MUST 在不覆盖既有技能的前提下完成导入，并在导入后立即出现在技能列表中。

#### Scenario: 导入单顶层目录技能包
- **WHEN** 用户上传 `data-story.zip`，其中包含 `data-story/SKILL.md` 与 `data-story/references/check.md`
- **THEN** 系统创建 `skills/data-story/`，`SKILL.md` 位于根目录，资源清单包含 `references/check.md`，且不保留多余的顶层目录

#### Scenario: 导入根目录技能包
- **WHEN** 用户上传的 ZIP 根目录直接包含 `SKILL.md` 与 `scripts/run.py`
- **THEN** 系统把两者写入 `skills/<slug>/`，并记录初始版本说明为“导入 zip”

#### Scenario: 缺少或重复入口
- **WHEN** 压缩包中没有 `SKILL.md` 或包含多个 `SKILL.md`
- **THEN** 系统拒绝导入并返回 `422`，磁盘与数据库均不新增技能

#### Scenario: slug 冲突
- **WHEN** 解析出的 slug 与已有技能或已有目录相同
- **THEN** 系统返回 `409`，不覆盖、不合并既有技能

### Requirement: 导入安全与限制
系统 SHALL 把上传的 ZIP 视为不可信输入。解压 MUST 拒绝绝对路径、包含 `..` 的路径、盘符、符号链接与加密条目；MUST 限制上传大小、解压总大小与成员数量，超限时拒绝且不产生残留文件。导入 MUST 先解压到技能根目录内的隐藏临时目录，通过标准技能校验后再原子移动到目标 slug 目录；任一步失败 MUST 清理临时目录与数据库记录。

#### Scenario: 阻止路径穿越
- **WHEN** ZIP 中存在名为 `../evil.md`、`/etc/passwd` 或符号链接的成员
- **THEN** 系统拒绝整个导入并返回 `422`，技能根目录之外不写入任何文件

#### Scenario: 超出大小限制
- **WHEN** 上传文件超过 20 MB、解压后超过 50 MB 或成员数超过 500
- **THEN** 系统返回 `413`，不创建技能目录或数据库记录

#### Scenario: 无效技能内容
- **WHEN** `SKILL.md` 的 frontmatter 缺少 `name`/`description` 或 YAML 无法解析
- **THEN** 系统返回 `422` 并清理临时目录，其他技能不受影响
