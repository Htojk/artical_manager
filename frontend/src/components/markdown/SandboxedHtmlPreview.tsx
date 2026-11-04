import { cn } from "../../lib/utils";

interface SandboxedHtmlPreviewProps {
  html: string;
  title?: string;
  className?: string;
  heightClass?: string;
}

/**
 * WeChat HTML is rendered exclusively inside a fully sandboxed iframe. Never
 * feed generated HTML through dangerouslySetInnerHTML in the parent document.
 */
export function SandboxedHtmlPreview({
  html,
  title = "公众号文章预览",
  className,
  heightClass = "h-[520px]",
}: SandboxedHtmlPreviewProps) {
  return (
    <iframe
      title={title}
      sandbox=""
      srcDoc={html}
      className={cn("w-full rounded-xl border border-slate-200 bg-white", heightClass, className)}
      data-testid="wechat-preview-iframe"
    />
  );
}
