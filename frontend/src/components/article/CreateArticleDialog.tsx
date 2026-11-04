import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Bot, Check, PenLine, Sparkles } from "lucide-react";
import { api } from "../../lib/api";
import { DEFAULT_PLATFORMS, PLATFORM_LABELS } from "../../lib/labels";
import type { Article } from "../../types";
import { cn, toErrorMessage } from "../../lib/utils";
import { Alert } from "../ui/alert";
import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { Textarea } from "../ui/textarea";

interface CreateArticleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (article: Article, options: { aiMode: boolean; domain: string }) => void;
}

export function CreateArticleDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateArticleDialogProps) {
  const [mode, setMode] = useState<"manual" | "ai">("manual");
  const [title, setTitle] = useState("");
  const [angle, setAngle] = useState("");
  const [domain, setDomain] = useState("");
  const [platforms, setPlatforms] = useState<string[]>([...DEFAULT_PLATFORMS]);
  const [publishConfirmation, setPublishConfirmation] = useState(true);

  const mutation = useMutation({
    mutationFn: () =>
      api.createArticle({
        title: mode === "manual" ? title.trim() : "",
        topic_mode: mode,
        target_platforms: platforms,
        publish_confirmation: publishConfirmation,
        angle: mode === "manual" ? angle.trim() : "",
      }),
    onSuccess: (result) => {
      onCreated(result.article, { aiMode: mode === "ai", domain: domain.trim() });
      onOpenChange(false);
      setTitle("");
      setAngle("");
      setDomain("");
    },
  });

  const togglePlatform = (platform: string) => {
    setPlatforms((previous) =>
      previous.includes(platform)
        ? previous.filter((item) => item !== platform)
        : [...previous, platform],
    );
  };

  const canSubmit =
    platforms.length > 0 && (mode === "ai" || title.trim().length >= 5);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} labelledBy="create-article-title">
      <DialogHeader>
        <DialogTitle id="create-article-title">新建文章</DialogTitle>
        <DialogDescription>
          手动输入主题，或创建 AI 选题草稿后生成 5 个候选主题。
        </DialogDescription>
      </DialogHeader>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) mutation.mutate();
        }}
      >
        <DialogContent className="max-h-[70vh] space-y-5 overflow-y-auto">
          <div className="grid grid-cols-2 gap-2" role="tablist" aria-label="选题模式">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "manual"}
              onClick={() => setMode("manual")}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-3 text-left transition-colors",
                mode === "manual"
                  ? "border-indigo-300 bg-indigo-50"
                  : "border-slate-200 bg-white hover:bg-slate-50",
              )}
            >
              <PenLine className="mt-0.5 h-4 w-4 text-indigo-600" aria-hidden="true" />
              <span>
                <span className="block text-sm font-semibold text-slate-800">手动主题</span>
                <span className="mt-0.5 block text-xs text-slate-500">自己输入标题与角度</span>
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "ai"}
              onClick={() => setMode("ai")}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-3 text-left transition-colors",
                mode === "ai"
                  ? "border-indigo-300 bg-indigo-50"
                  : "border-slate-200 bg-white hover:bg-slate-50",
              )}
            >
              <Sparkles className="mt-0.5 h-4 w-4 text-violet-600" aria-hidden="true" />
              <span>
                <span className="block text-sm font-semibold text-slate-800">AI 推荐选题</span>
                <span className="mt-0.5 block text-xs text-slate-500">生成 5 个候选供选择</span>
              </span>
            </button>
          </div>

          {mode === "manual" ? (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="create-title">文章主题</Label>
                <Input
                  id="create-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="例如：为什么 AI Agent 需要工作流编排"
                  minLength={5}
                  required
                  autoFocus
                />
                <p className="text-xs text-slate-400">主题至少 5 个字符。</p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="create-angle">切入角度（可选）</Label>
                <Textarea
                  id="create-angle"
                  rows={2}
                  value={angle}
                  onChange={(event) => setAngle(event.target.value)}
                  placeholder="面向工程团队，结合真实系统设计…"
                />
              </div>
            </div>
          ) : (
            <div className="space-y-3 rounded-xl border border-violet-100 bg-violet-50/50 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-violet-800">
                <Bot className="h-4 w-4" aria-hidden="true" />
                AI 选题模式
              </div>
              <p className="text-xs leading-5 text-slate-500">
                创建草稿后会进入选题节点，AI 将结合热点生成恰好 5 个候选主题。你可以刷新推荐或改用手动输入。
              </p>
              <div className="space-y-1.5">
                <Label htmlFor="create-domain">关注领域（可选）</Label>
                <Input
                  id="create-domain"
                  value={domain}
                  onChange={(event) => setDomain(event.target.value)}
                  placeholder="例如：大模型应用、开发者工具"
                />
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label>目标平台</Label>
            <div className="grid grid-cols-2 gap-2">
              {DEFAULT_PLATFORMS.map((platform) => {
                const selected = platforms.includes(platform);
                return (
                  <button
                    type="button"
                    key={platform}
                    aria-pressed={selected}
                    onClick={() => togglePlatform(platform)}
                    className={cn(
                      "flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors",
                      selected
                        ? "border-indigo-300 bg-indigo-50 text-indigo-800"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                    )}
                  >
                    {PLATFORM_LABELS[platform] ?? platform}
                    <span
                      className={cn(
                        "flex h-4 w-4 items-center justify-center rounded border",
                        selected ? "border-indigo-500 bg-indigo-500 text-white" : "border-slate-300",
                      )}
                    >
                      {selected ? <Check className="h-3 w-3" aria-hidden="true" /> : null}
                    </span>
                  </button>
                );
              })}
            </div>
            {platforms.length === 0 ? (
              <p className="text-xs text-red-500">请至少选择一个目标平台。</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between gap-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
            <div>
              <p className="text-sm font-medium text-slate-800">发布前人工确认</p>
              <p className="mt-0.5 text-xs text-slate-500">工作流在真正发布前暂停等待你的批准。</p>
            </div>
            <Switch
              checked={publishConfirmation}
              onCheckedChange={setPublishConfirmation}
              label="发布前人工确认"
            />
          </div>

          {mutation.error ? (
            <Alert variant="destructive">{toErrorMessage(mutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button type="submit" loading={mutation.isPending} disabled={!canSubmit}>
            {mode === "ai" ? "创建并推荐选题" : "创建文章"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
