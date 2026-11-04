import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Braces, FileJson, ListTree, Plus, Save, Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { invalidateArticleData, useStageDetail } from "../../../hooks/useArticleQueries";
import type { OutlineContent, OutlineSection } from "../../../types";
import { formatDate, toErrorMessage } from "../../../lib/utils";
import { Alert } from "../../ui/alert";
import { Badge } from "../../ui/badge";
import { Button } from "../../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../ui/card";
import { Input } from "../../ui/input";
import { Label } from "../../ui/label";
import { Select } from "../../ui/select";
import { Skeleton } from "../../ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../ui/tabs";
import { Textarea } from "../../ui/textarea";
import { EmptyState, ErrorState } from "../../common/States";
import { PanelShell, SectionTitle, StageRunSummary } from "./shared";

interface OutlinePanelProps {
  articleId: string;
}

const EMPTY_OUTLINE: OutlineContent = {
  title: "",
  hook: "",
  sections: [],
  target_words: 1800,
  summary: "",
  tags: [],
};

function isOutlineContent(value: unknown): value is OutlineContent {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.title === "string" &&
    Array.isArray(record.sections) &&
    record.sections.every(
      (section) =>
        typeof section === "object" &&
        section !== null &&
        typeof (section as Record<string, unknown>).heading === "string",
    )
  );
}

function normalizeOutline(content: OutlineContent): OutlineContent {
  return {
    title: content.title ?? "",
    hook: content.hook ?? "",
    summary: content.summary ?? "",
    target_words: content.target_words ?? 1800,
    tags: content.tags ?? [],
    sections: (content.sections ?? []).map((section) => ({
      heading: section.heading ?? "",
      key_points: section.key_points ?? [],
      source_refs: section.source_refs ?? [],
      image_hint: section.image_hint ?? "",
    })),
  };
}

function SectionEditor({
  section,
  index,
  onChange,
  onRemove,
}: {
  section: OutlineSection;
  index: number;
  onChange: (section: OutlineSection) => void;
  onRemove: () => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          第 {index + 1} 节
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onRemove}
          aria-label={`删除第 ${index + 1} 节`}
          className="text-red-600 hover:bg-red-50 hover:text-red-700"
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          删除
        </Button>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-1.5 md:col-span-2">
          <Label>章节标题</Label>
          <Input
            value={section.heading}
            onChange={(event) => onChange({ ...section, heading: event.target.value })}
          />
        </div>
        <div className="space-y-1.5 md:col-span-2">
          <Label>要点（每行一个）</Label>
          <Textarea
            rows={4}
            value={section.key_points.join("\n")}
            onChange={(event) =>
              onChange({
                ...section,
                key_points: event.target.value.split("\n").filter((line) => line.trim()),
              })
            }
          />
        </div>
        <div className="space-y-1.5">
          <Label>引用来源编号（逗号分隔）</Label>
          <Input
            value={section.source_refs.join(", ")}
            onChange={(event) =>
              onChange({
                ...section,
                source_refs: event.target.value
                  .split(",")
                  .map((value) => Number.parseInt(value.trim(), 10))
                  .filter((value) => Number.isFinite(value)),
              })
            }
          />
        </div>
        <div className="space-y-1.5">
          <Label>配图提示</Label>
          <Input
            value={section.image_hint}
            onChange={(event) => onChange({ ...section, image_hint: event.target.value })}
            placeholder="可选"
          />
        </div>
      </div>
    </div>
  );
}

export function OutlinePanel({ articleId }: OutlinePanelProps) {
  const queryClient = useQueryClient();
  const stageQuery = useStageDetail(articleId, "outline");
  const [tab, setTab] = useState("structured");
  const [form, setForm] = useState<OutlineContent>(EMPTY_OUTLINE);
  const [jsonText, setJsonText] = useState(JSON.stringify(EMPTY_OUTLINE, null, 2));
  const [note, setNote] = useState("用户编辑");
  const [selectedVersion, setSelectedVersion] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const loadedVersion = useRef<string | null>(null);

  const latest = stageQuery.data?.content.latest ?? null;
  const history = stageQuery.data?.content.history ?? [];

  useEffect(() => {
    if (!latest || loadedVersion.current === latest.id) return;
    loadedVersion.current = latest.id;
    setForm(normalizeOutline(latest.content));
    setJsonText(JSON.stringify(latest.content, null, 2));
    setSelectedVersion(latest.id);
  }, [latest]);

  const saveMutation = useMutation({
    mutationFn: (content: OutlineContent) => api.saveOutline(articleId, content, note),
    onSuccess: () => {
      setValidationError(null);
      invalidateArticleData(queryClient, articleId);
    },
  });

  if (stageQuery.isLoading) {
    return (
      <PanelShell title="大纲生成" description="文章结构与章节要点">
        <Skeleton className="h-64 w-full" />
      </PanelShell>
    );
  }

  if (stageQuery.isError) {
    return <ErrorState message={toErrorMessage(stageQuery.error)} onRetry={() => void stageQuery.refetch()} />;
  }

  const updateSection = (index: number, section: OutlineSection) => {
    setForm((previous) => ({
      ...previous,
      sections: previous.sections.map((item, itemIndex) => (itemIndex === index ? section : item)),
    }));
  };

  const removeSection = (index: number) => {
    setForm((previous) => ({
      ...previous,
      sections: previous.sections.filter((_, itemIndex) => itemIndex !== index),
    }));
  };

  const addSection = () => {
    setForm((previous) => ({
      ...previous,
      sections: [
        ...previous.sections,
        { heading: "新章节", key_points: [], source_refs: [], image_hint: "" },
      ],
    }));
    setTab("structured");
  };

  const loadVersion = (versionId: string) => {
    const version = history.find((item) => item.id === versionId);
    if (!version) return;
    setSelectedVersion(versionId);
    setForm(normalizeOutline(version.content));
    setJsonText(JSON.stringify(version.content, null, 2));
    setValidationError(null);
  };

  const handleSave = () => {
    setValidationError(null);
    let content: OutlineContent;
    if (tab === "json") {
      try {
        const parsed: unknown = JSON.parse(jsonText);
        if (!isOutlineContent(parsed)) {
          setValidationError("JSON 结构无效：至少需要 title 与 sections 数组。");
          return;
        }
        content = parsed;
      } catch (error) {
        setValidationError(`JSON 解析失败：${toErrorMessage(error)}`);
        return;
      }
    } else {
      content = form;
    }
    if (!content.title.trim()) {
      setValidationError("大纲标题不能为空。");
      return;
    }
    if (content.sections.length === 0) {
      setValidationError("大纲至少需要包含一个章节。");
      return;
    }
    saveMutation.mutate(content);
  };

  return (
    <PanelShell
      title="大纲生成"
      description="查看最新大纲与历史版本，支持结构化编辑或直接修改 JSON。保存会生成新版本。"
      actions={
        <Button onClick={handleSave} loading={saveMutation.isPending}>
          <Save className="h-4 w-4" aria-hidden="true" />
          保存新版本
        </Button>
      }
    >
      <StageRunSummary stageRun={stageQuery.data?.stage_run ?? null} />

      {!latest ? (
        <EmptyState
          title="尚无大纲"
          description="启动工作流后，大纲生成阶段会产出第一版大纲；也可以等待运行到该阶段。"
        />
      ) : (
        <>
          {saveMutation.isSuccess ? (
            <Alert variant="success">已保存新的大纲版本，后续阶段将读取最新版本。</Alert>
          ) : null}
          {saveMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(saveMutation.error)}</Alert>
          ) : null}
          {validationError ? <Alert variant="destructive">{validationError}</Alert> : null}

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
            <Card>
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>编辑器</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant="info">最新 v{latest.version}</Badge>
                    <Badge variant="outline">{latest.created_by}</Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <Tabs value={tab} onValueChange={setTab}>
                  <TabsList>
                    <TabsTrigger value="structured">
                      <span className="inline-flex items-center gap-1.5">
                        <ListTree className="h-3.5 w-3.5" aria-hidden="true" />
                        结构化编辑
                      </span>
                    </TabsTrigger>
                    <TabsTrigger value="json">
                      <span className="inline-flex items-center gap-1.5">
                        <FileJson className="h-3.5 w-3.5" aria-hidden="true" />
                        JSON
                      </span>
                    </TabsTrigger>
                  </TabsList>

                  <TabsContent value="structured" className="space-y-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5 sm:col-span-2">
                        <Label htmlFor="outline-title">文章标题</Label>
                        <Input
                          id="outline-title"
                          value={form.title}
                          onChange={(event) => setForm({ ...form, title: event.target.value })}
                        />
                      </div>
                      <div className="space-y-1.5 sm:col-span-2">
                        <Label htmlFor="outline-hook">开篇钩子</Label>
                        <Textarea
                          id="outline-hook"
                          rows={2}
                          value={form.hook}
                          onChange={(event) => setForm({ ...form, hook: event.target.value })}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="outline-words">目标字数</Label>
                        <Input
                          id="outline-words"
                          type="number"
                          min={100}
                          value={form.target_words}
                          onChange={(event) =>
                            setForm({ ...form, target_words: Number(event.target.value) })
                          }
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="outline-tags">标签（逗号分隔）</Label>
                        <Input
                          id="outline-tags"
                          value={form.tags.join(", ")}
                          onChange={(event) =>
                            setForm({
                              ...form,
                              tags: event.target.value
                                .split(",")
                                .map((tag) => tag.trim())
                                .filter(Boolean),
                            })
                          }
                        />
                      </div>
                      <div className="space-y-1.5 sm:col-span-2">
                        <Label htmlFor="outline-summary">摘要</Label>
                        <Textarea
                          id="outline-summary"
                          rows={2}
                          value={form.summary}
                          onChange={(event) => setForm({ ...form, summary: event.target.value })}
                        />
                      </div>
                    </div>

                    <SectionTitle
                      action={
                        <Button type="button" variant="outline" size="sm" onClick={addSection}>
                          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                          添加章节
                        </Button>
                      }
                    >
                      章节结构
                    </SectionTitle>
                    <div className="space-y-3">
                      {form.sections.map((section, index) => (
                        <SectionEditor
                          key={index}
                          section={section}
                          index={index}
                          onChange={(next) => updateSection(index, next)}
                          onRemove={() => removeSection(index)}
                        />
                      ))}
                      {form.sections.length === 0 ? (
                        <EmptyState title="还没有章节" description="添加至少一个章节后才能保存。" compact />
                      ) : null}
                    </div>
                  </TabsContent>

                  <TabsContent value="json">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-xs text-slate-500">
                        <Braces className="h-3.5 w-3.5" aria-hidden="true" />
                        可直接编辑结构化 JSON，保存前会校验基本字段。
                      </div>
                      <Textarea
                        value={jsonText}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                          setJsonText(event.target.value)
                        }
                        rows={26}
                        className="min-h-[480px] font-mono text-xs leading-5"
                        aria-label="大纲 JSON"
                      />
                    </div>
                  </TabsContent>
                </Tabs>

                <div className="flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-end">
                  <div className="flex-1 space-y-1.5">
                    <Label htmlFor="outline-note">版本说明</Label>
                    <Input
                      id="outline-note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                    />
                  </div>
                  <Button onClick={handleSave} loading={saveMutation.isPending}>
                    <Save className="h-4 w-4" aria-hidden="true" />
                    保存
                  </Button>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-3">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">版本历史</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Select
                    value={selectedVersion}
                    onChange={(event) => loadVersion(event.target.value)}
                    aria-label="选择大纲版本"
                  >
                    {[...history]
                      .sort((a, b) => b.version - a.version)
                      .map((version) => (
                        <option key={version.id} value={version.id}>
                          v{version.version} · {version.created_by}
                        </option>
                      ))}
                  </Select>
                  <div className="space-y-2">
                    {history.slice(0, 8).map((version) => (
                      <div
                        key={version.id}
                        className="rounded-lg border border-slate-100 px-3 py-2 text-xs"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-slate-700">v{version.version}</span>
                          <span className="text-slate-400">{formatDate(version.created_at)}</span>
                        </div>
                        <p className="mt-1 text-slate-500">{version.note || "无说明"}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
              <Card className="bg-indigo-50/50">
                <CardContent className="p-4 text-xs leading-5 text-slate-500">
                  <p className="font-semibold text-slate-700">版本说明</p>
                  <p className="mt-1">用户编辑会生成新版本，不会覆盖旧版大纲。审核回退也保留历史。</p>
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </PanelShell>
  );
}
