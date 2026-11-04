# Design

## Context

技能以 `skills/<slug>/` 目录为事实来源，`SkillLoader` 负责解析 `SKILL.md`、校验 frontmatter 与扫描 `references/scripts/assets`；`SkillManager` 负责数据库同步、版本与删除（移动到 `data/skill-trash/`）。当前没有从归档文件创建技能的入口。前端技能页已有新建/删除对话框与详情资源列表，可复用其交互模式。详见 `proposal.md` 与 `specs/skill-system/spec.md`。

## Goals / Non-Goals

**Goals:**

- 在页面与 API 一步导入包含资源目录的标准技能包。
- 对不可信 ZIP 做路径、符号链接、加密条目、体积与文件数防护。
- 复用 loader 的标准校验，导入失败不留下半成品。
- 保持 slug 为稳定标识，冲突时不覆盖既有技能。

**Non-Goals:**

- 不做在线编辑/读取 ZIP 内单个资源文件的内容。
- 不做 `.tar.gz`、远程 URL 或技能市场导入。
- 不自动合并同名技能，不覆盖已存在目录。
- 不自动绑定导入技能到阶段（沿用用户显式绑定）。

## Decisions

### 1. 上传协议采用 multipart，新增 `python-multipart`

- `POST /api/skills/import` 接收 `file`（必填）与 `slug`（可选）表单字段，返回 `201`。
- 使用 `UploadFile.file.read(limit + 1)` 读取并执行大小上限检查，避免一次性读取超大请求体。
- 备选方案：JSON 内传 base64。请求体膨胀 33%，前端还需手工编码，放弃。
- 备选方案：原始 `application/zip` 请求体。与浏览器 `<input type=file>` 的常规 FormData 不一致，放弃。

### 2. 解压过程完全手工控制

- 用 `zipfile.ZipFile(io.BytesIO(data))` 打开；拒绝加密条目（`flag_bits & 0x1`）。
- 成员名规范化：`\` → `/`；拒绝绝对路径、盘符、NUL 与任一 `..` 段。
- 拒绝符号链接条目（`external_attr` 文件类型为 `0o120000`）。
- 跳过 `__MACOSX/`、`.DS_Store` 与任一段以 `.` 开头的隐藏路径，避免把编辑器/系统垃圾写入技能目录。
- 逐个成员 `zf.open()` 分块写入目标临时目录，累计解压字节超过上限立即中止；不使用 `extractall()`，从根源规避 Zip Slip。
- 非 UTF-8 标记的成员名按 `cp437 → utf-8 → gbk` 回退解码，兼容中文文件名压缩包。
- 上限：上传 20 MB、解压 50 MB、成员 500 个；超限返回 `413`，其余格式问题返回 `422`。

### 3. 以 `SKILL.md` 定位技能根目录

- 在过滤后的成员中查找 basename 大小写不敏感的 `SKILL.md`。
- 恰好一个：以其父目录为根前缀，只提取该前缀下的文件并剥离前缀；父目录为空时提取全部。
- 零个或多个：返回 `422`，要求压缩包包含唯一的 `SKILL.md`。
- 根前缀下的 `skill.md` 统一写为 `SKILL.md`，满足 loader 入口约定；其他文件名保持原样。

### 4. slug 解析顺序与冲突策略

- 显式 `slug`：严格校验 `^[a-z0-9]+(?:-[a-z0-9]+)*$` 且 ≤64，非法返回 `422`。
- 未提供时：取 `SKILL.md` 根目录名 → ZIP 文件名（去扩展名），再规范为小写连字符；规范后为空（如纯中文名）则返回 `422` 并提示提供 slug。
- 数据库已存在同 slug 或 `skills/<slug>` 目录已存在：返回 `409`，绝不覆盖；用户可先删除或指定新 slug。

### 5. 原子安装与版本记录

- 解压目标为 `skills/.import-<uuid>`（隐藏目录，`SkillLoader.scan()` 会跳过）。
- 解压完成后调用 `loader.load_directory(tmp)` 复用现有校验；无效则删除临时目录并返回 `422`。
- 校验通过后 `tmp.rename(skills/<slug>)`，再 `sync()` 入库，追加 `SkillVersion(version=info.version, note="导入 zip：<原文件名>")`。
- 任一步失败：回滚会话、移除已移动目录、再次 `registry.reload()`，与 `create_skill()` 的清理策略一致。

### 6. 前端复用现有对话框模式

- 头部动作区新增「导入 ZIP」按钮，打开对话框：文件选择（`accept=".zip,application/zip"`）、可选 slug 输入、目录结构与限制说明。
- 提交使用 `FormData`；`request()` 不设置 `Content-Type`，由浏览器生成 boundary。
- 成功后关闭对话框、刷新技能与绑定、选中新技能，并展示“已导入 N 个文件”的提示；失败在对话框内显示后端错误信息。

## Risks / Trade-offs

- [ZIP 炸弹或超大资源耗尽磁盘] → 上传/解压/文件数三重限制，分块写入并在超限时中止。
- [路径穿越写入技能根目录之外] → 成员名逐段校验 + 目标 `resolve()` 后再验证位于临时目录内，不使用 `extractall()`。
- [中文文件名乱码] → 依据 UTF-8 标记与 `cp437/utf-8/gbk` 回退解码。
- [多层目录包裹导致文件遗漏] → 仅当 `SKILL.md` 唯一时以其父目录为根；其余散落文件明确忽略并在文档说明。
- [导入中断留下半成品] → 隐藏临时目录 + 失败清理；隐藏目录不会被扫描或注册。
- [与既有技能同名] → 返回 `409` 而不覆盖；如需替换由用户显式删除（进入回收目录）后重试。

## Migration Plan

1. 安装新增依赖 `python-multipart==0.0.20`（`pip install -r backend/requirements.txt`）。
2. 无需数据库迁移；导入技能与手工创建技能在数据层完全一致。
3. 回滚：移除接口与前端入口即可；已导入目录仍可被旧代码按标准技能加载，删除仍走 `data/skill-trash/`。
