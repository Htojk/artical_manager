# Tasks

## 1. 防护配置与核心模块

- [x] 1.1 在 `backend/app/core/config.py` 增加 `APP_SEARCH_THROTTLE_ENABLED`、`APP_SEARCH_MIN_INTERVAL_SECONDS`、`APP_SEARCH_CACHE_TTL_SECONDS`、`APP_SEARCH_COOLDOWN_SECONDS`、`APP_SEARCH_MAX_REQUESTS_PER_CALL`，并同步 `.env.example`；验证方式：新增配置测试用环境变量覆盖默认值，断言字段类型与数值生效。
- [x] 1.2 新建 `backend/app/article_generation/research/search_guard.py`，实现按引擎最小间隔、失败冷却、TTL 缓存与清除方法，支持注入 `clock`/`sleep`；验证方式：单测使用假时钟覆盖等待、冷却跳过与到期恢复、缓存命中/过期。
- [x] 1.3 为缓存结果返回防御性副本，避免调用方修改污染缓存；验证方式：单测修改首次返回结果后再次命中缓存，断言内容未被改变。

## 2. 搜索工具接入

- [x] 2.1 在 `HttpSearchTool` 中注入默认单例 `SearchGuard`，并在 `_dispatch` 调用每个引擎前检查冷却、执行最小间隔等待；验证方式：单测断言冷却中的引擎不发请求且切换到下一引擎。
- [x] 2.2 在 `_dispatch` 中接入缓存读取/写入与单次请求预算（缓存命中不计入预算）；验证方式：单测断言重复查询只发一次请求、缓存过期后重发、预算耗尽时返回已有结果或抛出现有 `SearchUnavailable`。
- [x] 2.3 保持自定义 `APP_SEARCH_ENDPOINT` 与 `search()` 签名/返回结构不变，并在 `APP_SEARCH_THROTTLE_ENABLED=false` 时跳过全部防护；验证方式：现有 `tests/test_research_tools.py` 全通过，新增开关关闭用例断言无等待/无缓存。
- [x] 2.4 更新 `README.md` 配置表，说明五个防护参数与默认值；验证方式：文档中的变量名与 `Settings` 字段逐项核对一致。

## 3. 集成验证

- [x] 3.1 运行后端全量测试，确认搜索、deep agent、工作流与追踪测试无回归；验证方式：`backend` 下 `python -m pytest -q` 全部通过。
- [x] 3.2 进行一次真实搜索冒烟，记录同引擎连续调用的耗时与日志，确认缓存命中、限流等待与冷却跳过按预期生效；验证方式：冒烟输出显示第二次相同查询不产生新网络请求。

## Workflow follow-up

- 代码评审通过后归档本变更（`/opsx:archive`）。
- 归档后确认主规格 `openspec/specs/article-generation/search-throttling/spec.md` 已生成。
