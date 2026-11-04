# 平台适配器开发指南

每个平台一个独立目录，互不引用：`backend/app/platforms/<platform>/`。启动时 `PlatformRegistry.discover()` 扫描所有 `<platform>/adapter.py` 并自动注册。

```text
backend/app/platforms/
  base.py            # 唯一契约：PlatformAdapter / FormatResult / PublishResult ...
  registry.py        # 发现、注册、按 key 查询、能力过滤
  mock/              # 演示平台
  wechat/            # 微信公众号（独立目录，可含 client.py/templates）
  zhihu/
  juejin/
  csdn/
```

## 契约

实现 `app.platforms.base.PlatformAdapter`：

```python
from app.platforms.base import (
    AdapterAvailability,
    AdapterCapabilities,
    ArticleForFormat,
    FormatResult,
    MetricsSnapshot,
    PlatformAdapter,
    PublishResult,
)


class DemoAdapter(PlatformAdapter):
    key = "demo"                    # 唯一，写入 article.target_platforms
    display_name = "Demo 平台"
    capabilities = AdapterCapabilities(
        format=True, publish=True, metrics=False, official_api=True, manual_fallback=True
    )

    def validate(self, credentials: dict) -> AdapterAvailability:
        if not credentials.get("token"):
            return AdapterAvailability(
                available=False, mode="export_manual", reason="未配置 token"
            )
        return AdapterAvailability(available=True, mode="api")

    def format(self, article: ArticleForFormat) -> FormatResult:
        return FormatResult(
            platform=self.key,
            title=article.title,
            summary=article.summary or article.title,
            tags=list(article.tags),
            content=article.content_md,     # 或转换为平台 HTML
            format="markdown",              # markdown | html
            metadata={"preview": article.content_md},
        )

    def publish(self, artifact: FormatResult, credentials: dict) -> PublishResult:
        # 有 API 时上传/提交；没有 API 时返回 manual_required 并提供导出内容
        return PublishResult(
            success=True,
            remote_id="demo-1",
            url="https://demo.local/a/1",
            status="published",
            mode="api",
            raw={},
        )

    def fetch_metrics(self, record, credentials: dict) -> MetricsSnapshot | None:
        # 没有指标 API 时返回 None，采集器会记为 skipped
        return None
```

约定：

- `key` 与目录名一致；`format` 返回的 `platform` 必须等于 `key`，`format` 只能是 `markdown` 或 `html`。
- 凭据由 `CredentialService` 解密后以普通 dict 传入；适配器不得自行落盘或打印凭据。
- 单个平台抛异常必须被上层隔离：排版服务会保存 `failed` 行并允许单独重试，不影响其他平台。
- 发布需幂等：同一文章同一平台的重复发布请求不应重复创建远端内容。
- 指标能力通过 `capabilities.metrics` 声明；不支持时 `fetch_metrics` 返回 `None`，用户可手动回填。
- 公众号等 HTML 平台应声明 `format="html"`，前端只在沙箱 iframe 预览。

## 注册与调用

```python
registry = PlatformRegistry()
registry.discover()                 # 自动扫描 app.platforms.*.adapter
registry.get("wechat")              # 不存在返回 None
registry.require("wechat")          # 不存在抛 KeyError
registry.with_capability("metrics") # 只返回声明了指标能力的适配器
```

也支持从外部目录发现：`registry.discover(paths=[Path("my_adapters")])`，每个子目录包含 `adapter.py`。

## 新增平台清单

1. 创建 `backend/app/platforms/<key>/__init__.py` 与 `adapter.py`。
2. 实现上述契约；需要 HTTP 客户端时放在同目录（参考 `wechat/client.py`）。
3. 运行 `pytest -k adapter_contract`，确认新适配器通过跨平台契约测试。
4. 在设置页录入凭据（如需），前端平台列表会通过 `/api/platforms` 自动显示。
5. 无需修改 `registry.py` 或文章生成代码。

## 测试建议

- 用 `httpx.MockTransport` 模拟平台 API，覆盖成功、鉴权失败、限流/5xx 与幂等。
- 断言缺凭据时 `validate` 返回不可用且不影响其他平台排版。
- 断言 `format` 输出可被发布复用，`fetch_metrics` 不可用时返回 `None`。
