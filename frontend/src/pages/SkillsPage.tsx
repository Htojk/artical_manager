import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FileText,
  Link2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { api } from "../lib/api";
import { queryKeys } from "../hooks/useArticleQueries";
import { SKILL_STAGE_KEYS, STAGE_LABELS } from "../lib/labels";
import { formatDate, toErrorMessage } from "../lib/utils";
import type { StageKey } from "../types";
import { PageHeader } from "../components/common/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States";
import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { MarkdownEditor } from "../components/markdown/MarkdownEditor";

const EMPTY_FORM = { slug: "", display_name: "", description: "", content: "" };

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function SkillsPage() {
  const queryClient = useQueryClient();
  const [selectedSlug, setSelectedSlug] = useState("");
  const [content, setContent] = useState("");
  const [bindingStage, setBindingStage] = useState<StageKey>("writing");
  const [bindingSlug, setBindingSlug] = useState("");
  const [note, setNote] = useState("用户编辑");
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formStages, setFormStages] = useState<StageKey[]>([]);
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importSlug, setImportSlug] = useState("");
  const [importNotice, setImportNotice] = useState("");

  const skillsQuery = useQuery({
    queryKey: queryKeys.skills(),
    queryFn: () => api.listSkills(),
  });
  const bindingsQuery = useQuery({
    queryKey: queryKeys.skillBindings(),
    queryFn: () => api.listSkillBindings(),
  });

  const skills = skillsQuery.data?.items ?? [];
  const bindings = bindingsQuery.data?.items ?? [];
  const activeSlug = selectedSlug || skills[0]?.slug || "";

  const detailQuery = useQuery({
    queryKey: queryKeys.skill(activeSlug),
    queryFn: () => api.getSkill(activeSlug),
    enabled: Boolean(activeSlug),
  });

  const detailSlug = detailQuery.data?.slug;
  const detailContent = detailQuery.data?.content;

  useEffect(() => {
    if (!detailSlug) return;
    setContent(detailContent ?? "");
  }, [detailSlug, detailContent]);

  const toggleMutation = useMutation({
    mutationFn: ({ slug, enabled }: { slug: string; enabled: boolean }) =>
      api.toggleSkill(slug, enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(activeSlug) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillBindings() });
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => api.saveSkillContent(activeSlug, content, note),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(activeSlug) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills() });
    },
  });

  const bindMutation = useMutation({
    mutationFn: () => {
      const slug = bindingSlug || activeSlug;
      const order = bindings.filter((binding) => binding.stage === bindingStage).length;
      return api.createSkillBinding({ stage: bindingStage, slug, order, enabled: true });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillBindings() });
    },
  });

  const unbindMutation = useMutation({
    mutationFn: (bindingId: string) => api.deleteSkillBinding(bindingId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillBindings() });
    },
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.createSkill({
        slug: form.slug.trim(),
        display_name: form.display_name.trim(),
        description: form.description.trim(),
        content: form.content,
        applies_to: formStages,
      }),
    onSuccess: (skill) => {
      setCreateOpen(false);
      setForm(EMPTY_FORM);
      setFormStages([]);
      setSelectedSlug(skill.slug);
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills() });
    },
  });

  const importMutation = useMutation({
    mutationFn: () => {
      if (!importFile) throw new Error("请选择 ZIP 技能包");
      return api.importSkill(importFile, importSlug);
    },
    onSuccess: (result) => {
      setImportOpen(false);
      setImportFile(null);
      setImportSlug("");
      setSelectedSlug(result.slug);
      setContent(result.content ?? "");
      setImportNotice(
        `已导入技能“${result.name}”，共 ${result.imported_files} 个文件。`,
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skill(result.slug) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillBindings() });
    },
  });

  const exportMutation = useMutation({
    mutationFn: (slug: string) => api.exportSkill(slug),
  });

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => api.deleteSkill(slug),
    onSuccess: () => {
      setDeleteOpen(false);
      setSelectedSlug("");
      setBindingSlug("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.skills() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.skillBindings() });
    },
  });

  const detail = detailQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Skills"
        title="技能管理"
        description="创建、编辑、删除标准 Agent Skills，并将技能按阶段绑定；只有当前阶段的绑定会在生成时加载。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                void skillsQuery.refetch();
                void bindingsQuery.refetch();
              }}
            >
              刷新
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                importMutation.reset();
                setImportNotice("");
                setImportOpen(true);
              }}
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              导入 ZIP
            </Button>
            <Button
              onClick={() => {
                createMutation.reset();
                setCreateOpen(true);
              }}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              新建技能
            </Button>
          </div>
        }
      />

      {skillsQuery.isError ? (
        <ErrorState
          message={toErrorMessage(skillsQuery.error)}
          onRetry={() => void skillsQuery.refetch()}
        />
      ) : null}
      {bindMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(bindMutation.error)}</Alert>
      ) : null}
      {unbindMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(unbindMutation.error)}</Alert>
      ) : null}
      {deleteMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(deleteMutation.error)}</Alert>
      ) : null}
      {importNotice ? <Alert variant="success">{importNotice}</Alert> : null}
      {exportMutation.error ? (
        <Alert variant="destructive">{toErrorMessage(exportMutation.error)}</Alert>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">技能列表</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {skillsQuery.isLoading ? <LoadingState label="正在加载技能…" /> : null}
              {!skillsQuery.isLoading && skills.length === 0 ? (
                <EmptyState
                  title="未发现技能"
                  description="点击“新建技能”创建标准技能，或把技能目录放入 skills/ 后刷新。"
                  compact
                />
              ) : null}
              {skills.map((skill) => {
                const active = skill.slug === activeSlug;
                return (
                  <div
                    key={skill.id}
                    className={`rounded-xl border p-3 transition-colors ${
                      active ? "border-indigo-300 bg-indigo-50/60" : "border-slate-200 bg-white"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          if (skill.slug !== activeSlug) setContent("");
                          setSelectedSlug(skill.slug);
                          setBindingSlug(skill.slug);
                        }}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p className="truncate text-sm font-semibold text-slate-800">{skill.name}</p>
                        <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-slate-500">
                          {skill.description || "无描述"}
                        </p>
                      </button>
                      <Switch
                        checked={skill.enabled}
                        disabled={toggleMutation.isPending}
                        label="启用技能"
                        onCheckedChange={(enabled) =>
                          toggleMutation.mutate({ slug: skill.slug, enabled })
                        }
                      />
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Badge variant={skill.enabled ? "success" : "secondary"}>
                        {skill.enabled ? "已启用" : "已停用"}
                      </Badge>
                      <Badge variant="outline">v{skill.version}</Badge>
                      {skill.status !== "valid" ? <Badge variant="destructive">{skill.status}</Badge> : null}
                    </div>
                    <p className="mt-2 text-[11px] text-slate-400">
                      {skill.applies_to.map((stage) => STAGE_LABELS[stage as StageKey] ?? stage).join("、") || "通用"}
                    </p>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="inline-flex items-center gap-2 text-sm">
                <Link2 className="h-4 w-4 text-slate-400" aria-hidden="true" />
                阶段绑定
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {bindingsQuery.isLoading ? <LoadingState label="加载绑定…" /> : null}
              {bindings.length === 0 ? (
                <p className="text-xs text-slate-400">尚未绑定任何技能。</p>
              ) : (
                <div className="space-y-3">
                  {SKILL_STAGE_KEYS.map((stage) => {
                    const stageBindings = bindings.filter(
                      (binding) => binding.stage === stage,
                    );
                    if (stageBindings.length === 0) return null;
                    return (
                      <div key={stage} className="space-y-1.5">
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                          {STAGE_LABELS[stage]}
                        </p>
                        {stageBindings.map((binding) => (
                          <div
                            key={binding.id}
                            className="flex items-start justify-between gap-2 rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2"
                          >
                            <div className="min-w-0 text-xs">
                              <p className="font-medium text-slate-700">
                                {binding.skill?.name ?? binding.skill_id}
                              </p>
                              <p className="mt-0.5 text-slate-400">
                                {STAGE_LABELS[stage]} · 顺序 {binding.order}
                              </p>
                            </div>
                            <Button
                              size="icon"
                              variant="ghost"
                              aria-label={`解绑技能：${binding.skill?.name ?? binding.skill_id}`}
                              onClick={() => unbindMutation.mutate(binding.id)}
                              className="h-7 w-7 text-slate-400 hover:bg-red-50 hover:text-red-600"
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="space-y-2 border-t border-slate-100 pt-3">
                <p className="text-[11px] text-slate-400">
                  只有选题、资料、大纲、写作、标题、审核六个 LLM 阶段可绑定技能。
                </p>
                <div className="space-y-1">
                  <Label htmlFor="binding-stage">绑定阶段</Label>
                  <Select
                    id="binding-stage"
                    value={bindingStage}
                    onChange={(event) => setBindingStage(event.target.value as StageKey)}
                  >
                    {SKILL_STAGE_KEYS.map((stage) => (
                      <option key={stage} value={stage}>
                        {STAGE_LABELS[stage]}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="binding-skill">技能</Label>
                  <Select
                    id="binding-skill"
                    value={bindingSlug || activeSlug}
                    onChange={(event) => setBindingSlug(event.target.value)}
                  >
                    {skills.map((skill) => (
                      <option key={skill.slug} value={skill.slug}>
                        {skill.name}
                        {skill.applies_to.length > 0
                          ? `（建议：${skill.applies_to
                              .map((stage) => STAGE_LABELS[stage as StageKey] ?? stage)
                              .join("、")}）`
                          : ""}
                      </option>
                    ))}
                  </Select>
                </div>
                <Button
                  size="sm"
                  className="w-full"
                  onClick={() => bindMutation.mutate()}
                  loading={bindMutation.isPending}
                  disabled={skills.length === 0}
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  添加绑定
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="min-w-0">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="inline-flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-violet-500" aria-hidden="true" />
                  {detail?.name ?? "技能内容"}
                </CardTitle>
                <p className="mt-1 text-sm text-slate-500">
                  {detail?.description ?? "从左侧选择一个技能查看与编辑。"}
                </p>
              </div>
              {detail ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">v{detail.version}</Badge>
                  <Badge variant={detail.enabled ? "success" : "secondary"}>
                    {detail.enabled ? "已启用" : "已停用"}
                  </Badge>
                  <Badge variant="info">{detail.status}</Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => exportMutation.mutate(detail.slug)}
                    loading={exportMutation.isPending}
                  >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    导出 ZIP
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-red-600 hover:bg-red-50"
                    onClick={() => {
                      deleteMutation.reset();
                      setDeleteOpen(true);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    删除技能
                  </Button>
                </div>
              ) : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {detailQuery.isError ? (
              <ErrorState
                message={toErrorMessage(detailQuery.error)}
                onRetry={() => void detailQuery.refetch()}
              />
            ) : null}
            {!detail && detailQuery.isLoading ? <LoadingState label="加载技能内容…" /> : null}
            {!detail && !detailQuery.isLoading && !detailQuery.isError ? (
              <EmptyState title="请选择技能" description="从左侧列表选择要编辑的技能。" />
            ) : null}
            {detail ? (
              <>
                <Alert variant="info">
                  技能遵循 Agent Skills 标准：目录中的 SKILL.md 使用 YAML frontmatter，只有 name 与
                  description 必填。正文仅在绑定阶段执行时注入系统提示，references/scripts/assets
                  中的资源不会自动进入提示词。保存会生成新版本，并在下一次模型调用时生效。
                </Alert>

                <div className="grid gap-2 rounded-xl border border-slate-100 bg-slate-50/60 p-3 text-xs text-slate-500 sm:grid-cols-2">
                  <p>
                    标准名称：<span className="font-mono text-slate-700">{detail.standard_name}</span>
                  </p>
                  <p>
                    入口文件：<span className="font-mono text-slate-700">{detail.entry}</span>
                  </p>
                  {detail.license ? <p>许可证：{detail.license}</p> : null}
                  {detail.compatibility ? <p>兼容性：{detail.compatibility}</p> : null}
                  {detail.allowed_tools.length > 0 ? (
                    <p className="sm:col-span-2">
                      允许工具：{detail.allowed_tools.join("、")}
                    </p>
                  ) : null}
                </div>

                <div>
                  <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                    <FileText className="h-4 w-4 text-slate-400" aria-hidden="true" />
                    捆绑资源
                  </h3>
                  {detail.resources.length === 0 ? (
                    <p className="text-xs text-slate-400">
                      暂无资源文件。可在技能目录下添加 references/、scripts/、assets/。
                    </p>
                  ) : (
                    <ul className="space-y-1 rounded-lg border border-slate-100 bg-slate-50/60 p-3 text-xs">
                      {detail.resources.map((resource) => (
                        <li
                          key={resource.path}
                          className="flex items-center justify-between gap-2"
                        >
                          <span className="truncate font-mono text-slate-600">{resource.path}</span>
                          <span className="shrink-0 text-slate-400">
                            {formatBytes(resource.size)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <MarkdownEditor
                  value={content}
                  onChange={setContent}
                  label="SKILL.md 内容（frontmatter + 正文）"
                  minRows={24}
                />
                <div className="flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-end sm:justify-between">
                  <div className="w-full space-y-1.5 sm:max-w-md">
                    <Label htmlFor="skill-note">版本说明</Label>
                    <Input
                      id="skill-note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                    />
                  </div>
                  <Button
                    onClick={() => saveMutation.mutate()}
                    loading={saveMutation.isPending}
                    disabled={!content.trim()}
                  >
                    <Save className="h-4 w-4" aria-hidden="true" />
                    保存技能内容
                  </Button>
                </div>
                {saveMutation.isSuccess ? (
                  <Alert variant="success">技能内容已保存，并生成新版本。</Alert>
                ) : null}
                {saveMutation.error ? (
                  <Alert variant="destructive">{toErrorMessage(saveMutation.error)}</Alert>
                ) : null}

                <div className="border-t border-slate-100 pt-4">
                  <h3 className="mb-2 text-sm font-semibold text-slate-800">历史版本</h3>
                  {detail.versions.length === 0 ? (
                    <p className="text-xs text-slate-400">暂无版本记录。</p>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {detail.versions.map((version) => (
                        <div
                          key={version.id}
                          className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-slate-700">v{version.version}</span>
                            <span className="text-slate-400">{formatDate(version.created_at)}</span>
                          </div>
                          <p className="mt-1 text-slate-500">{version.note || "无说明"}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Dialog open={importOpen} onOpenChange={setImportOpen} labelledBy="import-skill-title">
        <DialogHeader>
          <DialogTitle id="import-skill-title">导入 ZIP 技能包</DialogTitle>
          <DialogDescription>
            上传包含 SKILL.md 的 ZIP 技能包；references/、scripts/、assets/
            会一并导入到 skills/&lt;slug&gt;/。
          </DialogDescription>
        </DialogHeader>
        <DialogContent>
          <div className="space-y-1.5">
            <Label htmlFor="import-skill-file">技能包文件（.zip）</Label>
            <Input
              id="import-skill-file"
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="import-skill-slug">slug（可选）</Label>
            <Input
              id="import-skill-slug"
              value={importSlug}
              placeholder="留空则使用技能目录名或 ZIP 文件名"
              onChange={(event) => setImportSlug(event.target.value)}
            />
          </div>
          <Alert variant="info">
            支持 SKILL.md 位于压缩包根目录或单一顶层目录；缺少或包含多个 SKILL.md
            会被拒绝。同名技能不会被覆盖，请先删除或指定新的 slug。上传上限 20 MB。
          </Alert>
          {importMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(importMutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setImportOpen(false)}>
            取消
          </Button>
          <Button
            onClick={() => importMutation.mutate()}
            loading={importMutation.isPending}
            disabled={!importFile}
          >
            开始导入
          </Button>
        </DialogFooter>
      </Dialog>

      <Dialog open={createOpen} onOpenChange={setCreateOpen} labelledBy="create-skill-title">
        <DialogHeader>
          <DialogTitle id="create-skill-title">新建技能</DialogTitle>
          <DialogDescription>
            创建标准 Agent Skills 目录：skills/&lt;slug&gt;/SKILL.md。slug 只能包含小写字母、数字与连字符。
          </DialogDescription>
        </DialogHeader>
        <DialogContent>
          <div className="space-y-1.5">
            <Label htmlFor="create-skill-slug">技能 slug（目录名）</Label>
            <Input
              id="create-skill-slug"
              value={form.slug}
              placeholder="data-story"
              onChange={(event) => setForm({ ...form, slug: event.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="create-skill-name">展示名称</Label>
            <Input
              id="create-skill-name"
              value={form.display_name}
              placeholder="数据故事写法"
              onChange={(event) => setForm({ ...form, display_name: event.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="create-skill-description">技能描述</Label>
            <Input
              id="create-skill-description"
              value={form.description}
              placeholder="一句话说明技能解决什么问题"
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>建议阶段（仅作提示，可绑定到任意 LLM 阶段）</Label>
            <div className="flex flex-wrap gap-2">
              {SKILL_STAGE_KEYS.map((stage) => (
                <label
                  key={stage}
                  className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600"
                >
                  <input
                    type="checkbox"
                    checked={formStages.includes(stage)}
                    onChange={(event) =>
                      setFormStages(
                        event.target.checked
                          ? [...formStages, stage]
                          : formStages.filter((item) => item !== stage),
                      )
                    }
                  />
                  {STAGE_LABELS[stage]}
                </label>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="create-skill-content">技能正文</Label>
            <Textarea
              id="create-skill-content"
              rows={6}
              value={form.content}
              placeholder="## 写作要求&#10;先给结论，再给证据。"
              onChange={(event) => setForm({ ...form, content: event.target.value })}
            />
          </div>
          {createMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(createMutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setCreateOpen(false)}>
            取消
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            loading={createMutation.isPending}
            disabled={!form.slug.trim() || !form.description.trim()}
          >
            创建技能
          </Button>
        </DialogFooter>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen} labelledBy="delete-skill-title">
        <DialogHeader>
          <DialogTitle id="delete-skill-title">删除技能</DialogTitle>
          <DialogDescription>
            将删除技能“{detail?.name ?? ""}”及其阶段绑定。目录会移动到 data/skill-trash/，可手动恢复。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteOpen(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={() => activeSlug && deleteMutation.mutate(activeSlug)}
            loading={deleteMutation.isPending}
          >
            确认删除
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
