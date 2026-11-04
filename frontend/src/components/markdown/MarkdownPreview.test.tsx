import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownPreview } from "./MarkdownPreview";
import { SandboxedHtmlPreview } from "./SandboxedHtmlPreview";

describe("safe article previews", () => {
  it("renders GFM markdown while skipping raw HTML", () => {
    const { container } = render(
      <MarkdownPreview
        content={[
          "# 标题",
          "",
          "<script>alert('xss')</script>",
          "",
          "| 维度 | 得分 |",
          "| --- | --- |",
          "| 事实 | 90 |",
        ].join("\n")}
      />,
    );

    expect(screen.getByRole("heading", { name: "标题" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("事实")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.queryByText(/alert\('xss'\)/)).not.toBeInTheDocument();
  });

  it("renders generated WeChat HTML only inside a fully sandboxed iframe", () => {
    render(
      <SandboxedHtmlPreview
        title="公众号文章预览"
        html={"<script>alert('xss')</script><p>公众号正文</p>"}
      />,
    );

    const frame = screen.getByTitle("公众号文章预览");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame.getAttribute("srcdoc")).toContain("<p>公众号正文</p>");
    expect(document.querySelector("script")).toBeNull();
  });
});
