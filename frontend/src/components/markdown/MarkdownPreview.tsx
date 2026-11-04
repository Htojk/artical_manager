import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "../../lib/utils";

interface MarkdownPreviewProps {
  content: string;
  className?: string;
  emptyText?: string;
}

export function MarkdownPreview({
  content,
  className,
  emptyText = "暂无内容",
}: MarkdownPreviewProps) {
  if (!content.trim()) {
    return <p className="text-sm text-slate-400">{emptyText}</p>;
  }
  return (
    <div className={cn("markdown-body", className)} data-testid="markdown-preview">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {content}
      </ReactMarkdown>
    </div>
  );
}
