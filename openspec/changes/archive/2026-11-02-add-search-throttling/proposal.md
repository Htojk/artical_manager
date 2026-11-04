# Proposal

## Why

资料研究阶段现在默认直接请求百度、必应、360 和搜狗微信的免费 HTML 接口。deep agent 在一次调研中可能对同一引擎发起多次搜索，多个工作流或重试也会叠加请求；频率过高会触发验证码、限流甚至临时封禁，导致该阶段降级为模型知识。需要在代码层面主动控制调用节奏，而不是依赖外部接口的容忍度。

## What Changes

- 新增进程级搜索引擎调用防护：同一引擎两次请求之间保持最小间隔。
- 新增失败冷却：引擎返回限流/封禁/超时等错误后，在冷却期内跳过该引擎，避免连续重试。
- 新增查询结果缓存：相同引擎、查询与条数在 TTL 内直接复用结果，不重复请求。
- 新增单次搜索调用预算：一次 `search()` 调用最多访问的引擎/请求次数受上限约束，超出即停止并返回已有结果或明确失败。
- 新增对应配置项（最小间隔、缓存 TTL、失败冷却、单次请求上限），全部有安全默认值，无需额外配置即可生效。
- 防护逻辑对现有 `search()` 接口透明，研究阶段、deep agent 工具和自定义搜索端点保持兼容。

## Capabilities

### New Capabilities

- `article-generation/search-throttling`: 资料搜索阶段对免费搜索引擎调用的限流、失败冷却、结果缓存与单次调用预算。

### Modified Capabilities

<!-- 无：现有 research 能力的行为契约不变，仅新增调用防护。 -->

## Impact

- 代码：`backend/app/article_generation/research/`（搜索工具与新增防护模块）、`backend/app/core/config.py`。
- 配置：新增 `APP_SEARCH_*` 配置项；未配置时使用默认值。
- 接口：`HttpSearchTool.search()` 签名与返回类型不变；deep agent 的 `web_search` 工具无需改动。
- 测试：新增限流、冷却、缓存与预算相关单元测试；现有搜索与工作流测试保持通过。
- 文档：`.env.example`、`README.md` 补充配置说明。
