import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SkillsPage } from "./SkillsPage";
import {
  emptyResponse,
  installFetchMock,
  jsonResponse,
  renderWithProviders,
  requestBody,
  requestMethod,
} from "../test/utils";
import type {
  SkillBinding,
  SkillDetail,
  SkillImportResult,
  SkillSummary,
} from "../types";

const baseSkill: SkillSummary = {
  id: "skill-1",
  slug: "tech-writing-style",
  name: "技术写作风格",
  version: "1.0",
  description: "面向工程读者的写作风格",
  applies_to: ["writing"],
  enabled: true,
  source_path: "skills/tech-writing-style",
  status: "valid",
  error: null,
  updated_at: "2026-10-29T08:00:00.000Z",
};

function skillDetail(enabled: boolean): SkillDetail {
  return {
    ...baseSkill,
    enabled,
    standard_name: "tech-writing-style",
    resources: [],
    entry: "SKILL.md",
    license: "",
    compatibility: "",
    allowed_tools: [],
    content:
      "---\nname: tech-writing-style\ndescription: 面向工程读者的写作风格\n---\n\n# 技术写作\n\n先给结论，再展开论证。",
    versions: [
      {
        id: "version-1",
        version: "1.0",
        note: "初始版本",
        created_at: "2026-10-29T08:00:00.000Z",
      },
    ],
  };
}

describe("SkillsPage", () => {
  it("saves a stage binding and refreshes skill status after toggling", async () => {
    const user = userEvent.setup();
    let enabled = true;
    const bindings: SkillBinding[] = [
      {
        id: "binding-1",
        stage: "writing",
        skill_id: baseSkill.id,
        order: 0,
        enabled: true,
        skill: { ...baseSkill },
      },
    ];
    const toggleBodies: unknown[] = [];
    const bindingBodies: unknown[] = [];

    installFetchMock((url, init) => {
      const method = requestMethod(init);
      if (url === "/api/skills") {
        return jsonResponse({ items: [{ ...baseSkill, enabled }] });
      }
      if (url === "/api/skills/tech-writing-style") {
        return jsonResponse(skillDetail(enabled));
      }
      if (url === "/api/skills/tech-writing-style/toggle" && method === "POST") {
        toggleBodies.push(requestBody(init));
        enabled = Boolean((requestBody(init) as { enabled?: boolean }).enabled);
        return jsonResponse({ ...baseSkill, enabled });
      }
      if (url === "/api/skill-bindings" && method === "POST") {
        const body = requestBody(init) as {
          stage: string;
          slug: string;
          order: number;
          enabled: boolean;
        };
        bindingBodies.push(body);
        bindings.push({
          id: "binding-2",
          stage: body.stage,
          skill_id: baseSkill.id,
          order: body.order,
          enabled: body.enabled,
          skill: { ...baseSkill, enabled },
        });
        return jsonResponse(bindings[bindings.length - 1], 201);
      }
      if (url === "/api/skill-bindings") {
        return jsonResponse({ items: bindings.map((binding) => ({ ...binding })) });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SkillsPage />);

    expect((await screen.findAllByText("技术写作风格")).length).toBeGreaterThan(0);
    expect(await screen.findByText("写作 · 顺序 0")).toBeInTheDocument();
    expect(screen.getAllByText("已启用").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("switch", { name: "启用技能" }));

    await waitFor(() => {
      expect(toggleBodies).toEqual([{ enabled: false }]);
    });
    await waitFor(() => {
      expect(screen.getAllByText("已停用").length).toBeGreaterThan(0);
    });

    await user.click(screen.getByRole("button", { name: "添加绑定" }));

    await waitFor(() => {
      expect(bindingBodies).toEqual([
        { stage: "writing", slug: "tech-writing-style", order: 1, enabled: true },
      ]);
    });
    expect(await screen.findByText("写作 · 顺序 1")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("绑定阶段"), "review");
    await user.click(screen.getByRole("button", { name: "添加绑定" }));

    await waitFor(() => {
      expect(bindingBodies[1]).toEqual({
        stage: "review",
        slug: "tech-writing-style",
        order: 0,
        enabled: true,
      });
    });
    expect(await screen.findByText("审核 · 顺序 0")).toBeInTheDocument();
  });

  it("creates a standard skill, shows resources and deletes it to trash", async () => {
    const user = userEvent.setup();
    let skills = [{ ...baseSkill }];
    const createBodies: unknown[] = [];
    let deleted = "";
    const created = {
      ...baseSkill,
      id: "skill-2",
      slug: "data-story",
      name: "数据故事",
      version: "1.0.0",
      description: "用数据讲故事的写作规范",
      applies_to: ["review"],
    };

    installFetchMock((url, init) => {
      const method = requestMethod(init);
      if (url === "/api/skills" && method === "POST") {
        createBodies.push(requestBody(init));
        skills = [...skills, created];
        return jsonResponse(created, 201);
      }
      if (url === "/api/skills") {
        return jsonResponse({ items: skills });
      }
      if (url === "/api/skills/data-story" && method === "DELETE") {
        deleted = "data-story";
        skills = skills.filter((skill) => skill.slug !== "data-story");
        return emptyResponse();
      }
      if (url === "/api/skills/data-story") {
        return jsonResponse({
          ...created,
          standard_name: "data-story",
          resources: [{ path: "references/checklist.md", size: 2048 }],
          entry: "SKILL.md",
          license: "",
          compatibility: "",
          allowed_tools: [],
          content: "# 数据故事\n\n每个结论配一个数字。",
          versions: [],
        });
      }
      if (url === "/api/skills/tech-writing-style") {
        return jsonResponse(skillDetail(true));
      }
      if (url === "/api/skill-bindings") {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SkillsPage />);
    expect((await screen.findAllByText("技术写作风格")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "新建技能" }));
    await user.type(screen.getByLabelText("技能 slug（目录名）"), "data-story");
    await user.type(screen.getByLabelText("展示名称"), "数据故事");
    await user.type(
      screen.getByLabelText("技能描述"),
      "用数据讲故事的写作规范",
    );
    await user.click(screen.getByRole("checkbox", { name: "审核" }));
    await user.type(
      screen.getByLabelText("技能正文"),
      "## 要求\n每个结论配一个数字。",
    );
    await user.click(screen.getByRole("button", { name: "创建技能" }));

    await waitFor(() => {
      expect(createBodies).toEqual([
        {
          slug: "data-story",
          display_name: "数据故事",
          description: "用数据讲故事的写作规范",
          content: "## 要求\n每个结论配一个数字。",
          applies_to: ["review"],
        },
      ]);
    });
    expect(await screen.findByText("references/checklist.md")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "删除技能" }));
    await user.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => {
      expect(deleted).toBe("data-story");
    });
  });

  it("downloads a skill ZIP package", async () => {
    const user = userEvent.setup();
    let exported = "";
    const createObjectURL = vi.fn(() => "blob:skill");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    installFetchMock((url) => {
      if (url === "/api/skills/tech-writing-style/export") {
        exported = url;
        return new Response(new Uint8Array([1, 2, 3]), {
          status: 200,
          headers: { "Content-Type": "application/zip" },
        });
      }
      if (url === "/api/skills") {
        return jsonResponse({ items: [{ ...baseSkill }] });
      }
      if (url === "/api/skills/tech-writing-style") {
        return jsonResponse(skillDetail(true));
      }
      if (url === "/api/skill-bindings") {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SkillsPage />);
    await user.click(await screen.findByRole("button", { name: "导出 ZIP" }));

    await waitFor(() => {
      expect(exported).toBe("/api/skills/tech-writing-style/export");
    });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    click.mockRestore();
  });

  it("imports a ZIP skill package and selects it", async () => {
    const user = userEvent.setup();
    const imported: SkillImportResult = {
      ...skillDetail(true),
      id: "skill-3",
      slug: "zip-skill",
      name: "压缩包技能",
      standard_name: "zip-skill",
      description: "从 ZIP 导入的技能",
      resources: [{ path: "references/check.md", size: 5 }],
      content:
        "---\nname: zip-skill\ndescription: 从 ZIP 导入的技能\n---\n\n# 压缩包技能",
      imported_files: 3,
      source_filename: "zip-skill.zip",
    };
    let uploaded: FormData | null = null;

    installFetchMock((url, init) => {
      if (url === "/api/skills/import" && requestMethod(init) === "POST") {
        uploaded = init.body as FormData;
        return jsonResponse(imported, 201);
      }
      if (url === "/api/skills") {
        return jsonResponse({ items: [{ ...baseSkill }] });
      }
      if (url === "/api/skills/zip-skill") {
        return jsonResponse(imported);
      }
      if (url === "/api/skills/tech-writing-style") {
        return jsonResponse(skillDetail(true));
      }
      if (url === "/api/skill-bindings") {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SkillsPage />);
    expect((await screen.findAllByText("技术写作风格")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "导入 ZIP" }));
    const file = new File(["zip"], "zip-skill.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText(/技能包文件/), file);
    await user.type(screen.getByLabelText(/slug（可选）/), "zip-skill");
    await user.click(screen.getByRole("button", { name: "开始导入" }));

    await waitFor(() => {
      expect(uploaded).not.toBeNull();
    });
    expect(uploaded!.get("slug")).toBe("zip-skill");
    expect(uploaded!.get("file")).toBe(file);
    expect(
      await screen.findByText(/已导入技能“压缩包技能”，共 3 个文件。/),
    ).toBeInTheDocument();
    expect(await screen.findByText("references/check.md")).toBeInTheDocument();
  });

  it("shows the backend error when a ZIP import is rejected", async () => {
    const user = userEvent.setup();

    installFetchMock((url, init) => {
      if (url === "/api/skills/import" && requestMethod(init) === "POST") {
        return jsonResponse(
          { code: "validation_error", message: "压缩包中未找到 SKILL.md" },
          422,
        );
      }
      if (url === "/api/skills") {
        return jsonResponse({ items: [{ ...baseSkill }] });
      }
      if (url === "/api/skills/tech-writing-style") {
        return jsonResponse(skillDetail(true));
      }
      if (url === "/api/skill-bindings") {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({ code: "not_found", message: `unexpected ${url}` }, 404);
    });

    renderWithProviders(<SkillsPage />);
    expect((await screen.findAllByText("技术写作风格")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "导入 ZIP" }));
    await user.upload(
      screen.getByLabelText(/技能包文件/),
      new File(["bad"], "bad.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "开始导入" }));

    expect(await screen.findByText("压缩包中未找到 SKILL.md")).toBeInTheDocument();
  });
});
