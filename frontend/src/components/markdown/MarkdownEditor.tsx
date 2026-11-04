import { FileText, Eye } from "lucide-react";
import { Textarea } from "../ui/textarea";
import { MarkdownPreview } from "./MarkdownPreview";
import { cn } from "../../lib/utils";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  placeholder?: string;
  minRows?: number;
  className?: string;
  disabled?: boolean;
}

export function MarkdownEditor({
  value,
  onChange,
  label = "Markdown 正文",
  placeholder = "在这里编辑 Markdown…",
  minRows = 22,
  className,
  disabled,
}: MarkdownEditorProps) {
  const wordCount = value.replace(/\s+/g, "").length;
  return (
    <div className={cn("grid gap-4 lg:grid-cols-2", className)}>
      <div className="min-w-0">
        <div className="mb-2 flex items-center justify-between gap-2">
          <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700">
            <FileText className="h-4 w-4 text-slate-400" aria-hidden="true" />
            {label}
          </label>
          <span className="text-xs tabular-nums text-slate-400">{wordCount} 字</span>
        </div>
        <Textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          rows={minRows}
          disabled={disabled}
          className="min-h-[420px] resize-y font-mono text-[13px] leading-6"
          aria-label={label}
        />
      </div>
      <div className="min-w-0">
        <div className="mb-2 flex items-center gap-1.5 text-sm font-medium text-slate-700">
          <Eye className="h-4 w-4 text-slate-400" aria-hidden="true" />
          实时预览
        </div>
        <div className="min-h-[420px] overflow-auto rounded-lg border border-slate-200 bg-white p-5">
          <MarkdownPreview content={value} emptyText="开始输入后，这里会显示预览。" />
        </div>
      </div>
    </div>
  );
}
