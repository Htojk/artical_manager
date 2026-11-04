import { describe, expect, it } from "vitest";
import { api, ApiError, request } from "./api";
import { installFetchMock, jsonResponse } from "../test/utils";

describe("API request wrapper", () => {
  it("sends JSON with the /api base and parses the response", async () => {
    const fetchMock = installFetchMock((url) => {
      expect(url).toBe("/api/articles?limit=200&status=running");
      return jsonResponse({ items: [], total: 0 });
    });

    const result = await api.listArticles({ limit: 200, status: "running" });

    expect(result).toEqual({ items: [], total: 0 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/articles?limit=200&status=running");
  });

  it("serializes a JSON body and sets request headers", async () => {
    const fetchMock = installFetchMock(() => jsonResponse({ id: "a1" }, 201));

    await request<{ id: string }>("/articles", {
      method: "POST",
      json: { title: "测试文章", target_platforms: ["wechat"] },
    });

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init).toBeDefined();
    const headers = new Headers(init?.headers);
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe(
      JSON.stringify({ title: "测试文章", target_platforms: ["wechat"] }),
    );
  });

  it("throws a typed ApiError for structured backend errors", async () => {
    installFetchMock(() =>
      jsonResponse(
        {
          code: "validation_error",
          message: "文章标题至少 5 个字符",
          details: { field: "title" },
        },
        422,
      ),
    );

    const error = await request("/articles", {
      method: "POST",
      json: { title: "x" },
    }).catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      name: "ApiError",
      status: 422,
      code: "validation_error",
      message: "文章标题至少 5 个字符",
      details: { field: "title" },
    });
  });

  it("returns undefined for 204 responses", async () => {
    installFetchMock(() => new Response(null, { status: 204 }));
    const result = await api.deleteArticle("a1");
    expect(result).toBeUndefined();
  });
});
