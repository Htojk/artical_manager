import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SettingsPage } from "./SettingsPage";
import {
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../test/utils";
import type { ModelProfile, PlatformInfo } from "../types";

const model: ModelProfile = {
  id: "model-1",
  name: "主力模型",
  provider: "openai-compatible",
  base_url: "https://api.example.com/v1",
  api_key_env: "APP_LLM_API_KEY",
  model: "gpt-4o-mini",
  input_price_per_1k: 0.002,
  output_price_per_1k: 0.004,
  currency: "CNY",
  context_window: 128000,
  enabled: true,
  updated_at: "2026-10-30T08:00:00.000Z",
};

const wechat: PlatformInfo = {
  key: "wechat",
  display_name: "微信公众号",
  capabilities: {
    format: true,
    publish: true,
    metrics: true,
    official_api: true,
  },
  available: true,
  mode: "api",
  reason: "凭据已配置",
  has_credentials: true,
};

const zhihu: PlatformInfo = {
  key: "zhihu",
  display_name: "知乎",
  capabilities: {
    format: true,
    publish: false,
    metrics: false,
    official_api: false,
  },
  available: true,
  mode: "manual",
  reason: "仅生成排版稿",
  has_credentials: false,
};

describe("SettingsPage", () => {
  it("renders model prices and shows only masked platform credentials", async () => {
    const user = userEvent.setup();
    installFetchMock((url) => {
      if (url === "/api/models") {
        return jsonResponse({ items: [model] });
      }
      if (url === "/api/model-bindings") {
        return jsonResponse({ items: [] });
      }
      if (url === "/api/platforms") {
        return jsonResponse({ items: [wechat, zhihu] });
      }
      if (url === "/api/settings") {
        return jsonResponse({ items: [] });
      }
      if (url === "/api/platforms/wechat/credentials") {
        return jsonResponse({
          platform: "wechat",
          masked: { app_id: "wx123***", app_secret: "****9d2f" },
        });
      }
      if (url === "/api/platforms/zhihu/credentials") {
        return jsonResponse({ platform: "zhihu", masked: {} });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SettingsPage />);

    await user.click(await screen.findByRole("tab", { name: "模型" }));

    expect(await screen.findByText("主力模型")).toBeInTheDocument();
    expect(screen.getAllByText(/0\.002/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/0\.004/).length).toBeGreaterThan(0);
    expect(screen.getByText("价格更新时间")).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "平台凭据" }));

    expect(await screen.findByText("wx123***")).toBeInTheDocument();
    expect(screen.getByText("****9d2f")).toBeInTheDocument();
    expect(screen.getByText("尚未设置凭据")).toBeInTheDocument();
    expect(screen.queryByText("wx1234567890")).not.toBeInTheDocument();
    expect(screen.queryByText("real-app-secret")).not.toBeInTheDocument();
  });

  it("toggles auto review advance in the workflow settings module", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock((url, init) => {
      const method = requestMethod(init);
      if (url === "/api/models") return jsonResponse({ items: [] });
      if (url === "/api/model-bindings") return jsonResponse({ items: [] });
      if (url === "/api/platforms") return jsonResponse({ items: [] });
      if (url === "/api/settings" && method === "GET") {
        return jsonResponse({
          items: [{ key: "auto_review_advance", value: false }],
        });
      }
      if (url === "/api/settings/auto_review_advance" && method === "PUT") {
        return jsonResponse({ key: "auto_review_advance", value: requestBody(init) });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SettingsPage />);

    await user.click(await screen.findByRole("tab", { name: "流程设置" }));
    const toggle = await screen.findByRole("switch");
    expect(toggle).toHaveAttribute("aria-checked", "false");

    await user.click(toggle);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/auto_review_advance",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ value: true }),
      }),
    );
  });

  it("saves the account profile used by content generation", async () => {
    const user = userEvent.setup();
    const fetchMock = installFetchMock((url, init) => {
      const method = requestMethod(init);
      if (url === "/api/models" || url === "/api/model-bindings" || url === "/api/platforms") {
        return jsonResponse({ items: [] });
      }
      if (url === "/api/settings" && method === "GET") return jsonResponse({ items: [] });
      if (url === "/api/settings/account_profile" && method === "PUT") {
        return jsonResponse({ key: "account_profile", value: requestBody(init) });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });
    renderWithProviders(<SettingsPage />);
    const name = await screen.findByLabelText("账号名称");
    await user.clear(name);
    await user.type(name, "AI 游戏室");
    await user.click(screen.getByRole("button", { name: /保存账号画像/ }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/account_profile",
      expect.objectContaining({
        method: "PUT",
        body: expect.stringContaining("AI 游戏室"),
      }),
    );
  });
});
