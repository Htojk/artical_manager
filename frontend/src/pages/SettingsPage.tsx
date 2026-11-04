import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  KeyRound,
  LockKeyhole,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { api } from "../lib/api";
import { queryKeys } from "../hooks/useArticleQueries";
import { STAGE_KEYS, STAGE_LABELS } from "../lib/labels";
import { formatDate, formatMoney, parseNumber, toErrorMessage } from "../lib/utils";
import type {
  ConnectivityReport,
  JsonValue,
  ModelBinding,
  ModelCreatePayload,
  ModelProfile,
  PlatformInfo,
  SettingItem,
  StageKey,
} from "../types";
import { PageHeader } from "../components/common/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States";
import { Alert } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Select } from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Textarea } from "../components/ui/textarea";

interface ModelFormState {
  name: string;
  provider: string;
  base_url: string;
  api_key_env: string;
  model: string;
  input_price_per_1k: string;
  output_price_per_1k: string;
  currency: string;
  context_window: string;
  enabled: boolean;
}

const EMPTY_MODEL: ModelFormState = {
  name: "",
  provider: "openai-compatible",
  base_url: "",
  api_key_env: "APP_LLM_API_KEY",
  model: "",
  input_price_per_1k: "",
  output_price_per_1k: "",
  currency: "CNY",
  context_window: "65536",
  enabled: true,
};

function toModelForm(model: ModelProfile): ModelFormState {
  return {
    name: model.name,
    provider: model.provider,
    base_url: model.base_url,
    api_key_env: model.api_key_env,
    model: model.model,
    input_price_per_1k:
      model.input_price_per_1k === null ? "" : String(model.input_price_per_1k),
    output_price_per_1k:
      model.output_price_per_1k === null ? "" : String(model.output_price_per_1k),
    currency: model.currency,
    context_window: String(model.context_window),
    enabled: model.enabled,
  };
}

function toModelPayload(form: ModelFormState): ModelCreatePayload {
  return {
    name: form.name.trim(),
    provider: form.provider.trim(),
    base_url: form.base_url.trim(),
    api_key_env: form.api_key_env.trim(),
    model: form.model.trim(),
    input_price_per_1k:
      form.input_price_per_1k.trim() === "" ? null : parseNumber(form.input_price_per_1k),
    output_price_per_1k:
      form.output_price_per_1k.trim() === "" ? null : parseNumber(form.output_price_per_1k),
    currency: form.currency.trim() || "CNY",
    context_window: Math.round(parseNumber(form.context_window, 65536)),
    enabled: form.enabled,
  };
}

function ModelDialog({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: ModelProfile | null;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ModelFormState>(EMPTY_MODEL);

  useEffect(() => {
    if (open) setForm(editing ? toModelForm(editing) : EMPTY_MODEL);
  }, [open, editing]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = toModelPayload(form);
      return editing ? api.updateModel(editing.id, payload) : api.createModel(payload);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.models() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelBindings() });
      onOpenChange(false);
    },
  });

  const update = (patch: Partial<ModelFormState>) => setForm((prev) => ({ ...prev, ...patch }));
  const canSave = Boolean(form.name.trim() && form.model.trim());

  return (
    <Dialog open={open} onOpenChange={onOpenChange} labelledBy="model-dialog-title">
      <DialogHeader>
        <DialogTitle id="model-dialog-title">{editing ? "编辑模型档案" : "新建模型档案"}</DialogTitle>
        <DialogDescription>
          使用 OpenAI 兼容接口。价格用于把 Token 用量换算为成本。
        </DialogDescription>
      </DialogHeader>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (canSave) saveMutation.mutate();
        }}
      >
        <DialogContent className="max-h-[70vh] space-y-4 overflow-y-auto">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="model-name">名称</Label>
              <Input
                id="model-name"
                value={form.name}
                onChange={(event) => update({ name: event.target.value })}
                placeholder="default-chat"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-provider">Provider</Label>
              <Input
                id="model-provider"
                value={form.provider}
                onChange={(event) => update({ provider: event.target.value })}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="model-base-url">Base URL</Label>
              <Input
                id="model-base-url"
                value={form.base_url}
                onChange={(event) => update({ base_url: event.target.value })}
                placeholder="https://api.openai.com/v1"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-id">模型名</Label>
              <Input
                id="model-id"
                value={form.model}
                onChange={(event) => update({ model: event.target.value })}
                placeholder="gpt-4o-mini"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-key-env">API Key 环境变量</Label>
              <Input
                id="model-key-env"
                value={form.api_key_env}
                onChange={(event) => update({ api_key_env: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-input-price">输入价格 / 1K Token</Label>
              <Input
                id="model-input-price"
                type="number"
                step="0.000001"
                min="0"
                value={form.input_price_per_1k}
                onChange={(event) => update({ input_price_per_1k: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-output-price">输出价格 / 1K Token</Label>
              <Input
                id="model-output-price"
                type="number"
                step="0.000001"
                min="0"
                value={form.output_price_per_1k}
                onChange={(event) => update({ output_price_per_1k: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-currency">币种</Label>
              <Input
                id="model-currency"
                value={form.currency}
                onChange={(event) => update({ currency: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model-context">上下文窗口</Label>
              <Input
                id="model-context"
                type="number"
                min="1"
                value={form.context_window}
                onChange={(event) => update({ context_window: event.target.value })}
              />
            </div>
          </div>
          <div className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 p-3">
            <span className="text-sm font-medium text-slate-700">启用该模型</span>
            <Switch
              checked={form.enabled}
              onCheckedChange={(enabled) => update({ enabled })}
              label="启用"
            />
          </div>
          {saveMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(saveMutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button type="submit" loading={saveMutation.isPending} disabled={!canSave}>
            保存模型
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

function ModelBindingsTab({
  bindings,
  models,
  loading,
  error,
  onRetry,
}: {
  bindings: ModelBinding[];
  models: ModelProfile[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  if (loading) return <LoadingState label="加载阶段绑定…" />;
  if (error) return <ErrorState message={toErrorMessage(error)} onRetry={onRetry} />;
  if (models.length === 0) {
    return <EmptyState title="请先创建模型" description="阶段绑定需要至少一个模型档案。" />;
  }
  return (
    <div className="space-y-3">
      {STAGE_KEYS.map((stage) => (
        <StageBindingRow
          key={stage}
          stage={stage}
          binding={bindings.find((item) => item.stage === stage) ?? null}
          models={models}
        />
      ))}
    </div>
  );
}

function StageBindingRow({
  stage,
  binding,
  models,
}: {
  stage: StageKey;
  binding: ModelBinding | null;
  models: ModelProfile[];
}) {
  const queryClient = useQueryClient();
  const [profileId, setProfileId] = useState(
    binding?.model_profile_id ?? models[0]?.id ?? "",
  );
  const [temperature, setTemperature] = useState(String(binding?.temperature ?? 0.7));
  const [maxTokens, setMaxTokens] = useState(String(binding?.max_tokens ?? 4096));

  useEffect(() => {
    setProfileId(binding?.model_profile_id ?? models[0]?.id ?? "");
    setTemperature(String(binding?.temperature ?? 0.7));
    setMaxTokens(String(binding?.max_tokens ?? 4096));
  }, [binding, models]);

  const mutation = useMutation({
    mutationFn: () =>
      api.saveModelBinding(stage, {
        model_profile_id: profileId,
        temperature: parseNumber(temperature, 0.7),
        max_tokens: Math.round(parseNumber(maxTokens, 4096)),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelBindings() });
    },
  });

  const profile = models.find((model) => model.id === profileId) ?? binding?.profile ?? null;

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Badge variant="info">{STAGE_LABELS[stage]}</Badge>
            <span className="font-mono text-[11px] text-slate-400">{stage}</span>
          </div>
          <span className="text-[11px] text-slate-400">
            {binding?.updated_at ? `更新于 ${formatDate(binding.updated_at)}` : "尚未绑定"}
          </span>
        </div>
        <form
          className="grid gap-3 sm:grid-cols-[minmax(0,2fr)_120px_140px_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor={`model-${stage}`}>模型</Label>
            <Select
              id={`model-${stage}`}
              value={profileId}
              onChange={(event) => setProfileId(event.target.value)}
            >
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} · {model.model}
                  {model.enabled ? "" : "（停用）"}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`temperature-${stage}`}>温度</Label>
            <Input
              id={`temperature-${stage}`}
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`max-tokens-${stage}`}>Max tokens</Label>
            <Input
              id={`max-tokens-${stage}`}
              type="number"
              min="1"
              value={maxTokens}
              onChange={(event) => setMaxTokens(event.target.value)}
            />
          </div>
          <Button type="submit" loading={mutation.isPending} disabled={!profileId}>
            <Save className="h-4 w-4" aria-hidden="true" />
            保存
          </Button>
        </form>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
          <span>
            价格：输入 {formatMoney(profile?.input_price_per_1k)} / 1K · 输出{" "}
            {formatMoney(profile?.output_price_per_1k)} / 1K
          </span>
          {profile && !profile.enabled ? <Badge variant="warning">模型已停用</Badge> : null}
          {mutation.error ? (
            <span className="text-red-600">{toErrorMessage(mutation.error)}</span>
          ) : null}
          {mutation.isSuccess ? <span className="text-emerald-600">已保存</span> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function PlatformCredentialCard({ platform }: { platform: PlatformInfo }) {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [payloadText, setPayloadText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);

  const credentialsQuery = useQuery({
    queryKey: queryKeys.platformCredentials(platform.key),
    queryFn: () => api.getMaskedCredentials(platform.key),
    staleTime: 30_000,
  });

  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, string>) =>
      api.setPlatformCredentials(platform.key, payload),
    onSuccess: () => {
      setDialogOpen(false);
      setPayloadText("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.platformCredentials(platform.key),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.platforms() });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deletePlatformCredentials(platform.key),
    onSuccess: () => {
      setDeleteOpen(false);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.platformCredentials(platform.key),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.platforms() });
    },
  });

  const masked = credentialsQuery.data?.masked ?? {};
  const handlesSave = () => {
    setParseError(null);
    try {
      const parsed: unknown = JSON.parse(payloadText);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed) ||
        Object.values(parsed).some((value) => typeof value !== "string")
      ) {
        setParseError("凭据 JSON 必须是字符串键值对象。");
        return;
      }
      const payload = Object.fromEntries(
        Object.entries(parsed as Record<string, string>).map(([key, value]) => [key, value]),
      );
      saveMutation.mutate(payload);
    } catch (error) {
      setParseError(`JSON 解析失败：${toErrorMessage(error)}`);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">{platform.display_name}</CardTitle>
            <Badge variant={platform.available ? "success" : "warning"}>
              {platform.available ? "可用" : "不可用"}
            </Badge>
            <Badge variant="outline">{platform.mode}</Badge>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setPayloadText(platform.key === "wechat"
                  ? '{\n  "app_id": "",\n  "app_secret": "",\n  "thumb_media_id": "",\n  "publish_mode": "draft"\n}'
                  : "{\n  \n}");
                setDialogOpen(true);
              }}
            >
              <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
              设置凭据
            </Button>
            {platform.has_credentials ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDeleteOpen(true)}
                className="text-red-600 hover:bg-red-50 hover:text-red-700"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                删除
              </Button>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          <Badge variant={platform.capabilities.format ? "info" : "secondary"}>排版</Badge>
          <Badge variant={platform.capabilities.publish ? "info" : "secondary"}>发布</Badge>
          <Badge variant={platform.capabilities.metrics ? "info" : "secondary"}>指标</Badge>
          <Badge variant={platform.capabilities.official_api ? "purple" : "secondary"}>
            官方 API
          </Badge>
        </div>
        <p className="text-xs text-slate-500">{platform.reason || "未提供状态说明"}</p>
        <div className="rounded-lg border border-slate-100 bg-slate-50/70 p-3">
          {credentialsQuery.isLoading ? (
            <p className="text-xs text-slate-400">读取掩码…</p>
          ) : Object.keys(masked).length === 0 ? (
            <p className="inline-flex items-center gap-1.5 text-xs text-amber-600">
              <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />
              尚未设置凭据
            </p>
          ) : (
            <div className="grid gap-1.5 text-xs">
              {Object.entries(masked).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between gap-3">
                  <span className="font-mono text-[11px] text-slate-400">{key}</span>
                  <span className="inline-flex items-center gap-1 font-mono text-slate-600">
                    <LockKeyhole className="h-3 w-3 text-slate-400" aria-hidden="true" />
                    {key === "cover_media_ids" && value && typeof value === "object"
                      ? `${Object.keys(value).length} 种封面已上传`
                      : String(value)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen} labelledBy={`credential-${platform.key}-title`}>
        <DialogHeader>
          <DialogTitle id={`credential-${platform.key}-title`}>
            设置凭据 · {platform.display_name}
          </DialogTitle>
          <DialogDescription>
            输入 JSON 键值对。保存后页面只展示掩码，不显示明文。
            {platform.key === "wechat" ? " 四张通用封面已上传后会按文章基调自动选择；thumb_media_id 作为备用封面，draft 仅同步草稿箱。" : ""}
          </DialogDescription>
        </DialogHeader>
        <DialogContent className="space-y-3">
          <Textarea
            value={payloadText}
            onChange={(event) => setPayloadText(event.target.value)}
            rows={8}
            className="font-mono text-xs"
            aria-label="平台凭据 JSON"
            autoComplete="off"
            spellCheck={false}
          />
          {parseError ? <Alert variant="destructive">{parseError}</Alert> : null}
          {saveMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(saveMutation.error)}</Alert>
          ) : null}
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDialogOpen(false)}>
            取消
          </Button>
          <Button
            onClick={handlesSave}
            loading={saveMutation.isPending}
            disabled={!payloadText.trim()}
          >
            保存凭据
          </Button>
        </DialogFooter>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen} labelledBy={`delete-credential-${platform.key}`}>
        <DialogHeader>
          <DialogTitle id={`delete-credential-${platform.key}`}>
            删除凭据 · {platform.display_name}
          </DialogTitle>
          <DialogDescription>
            删除后该平台的自动发布与指标抓取将不可用，直到重新设置凭据。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteOpen(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            loading={deleteMutation.isPending}
            onClick={() => deleteMutation.mutate()}
          >
            删除凭据
          </Button>
        </DialogFooter>
      </Dialog>
    </Card>
  );
}

function parseSettingValue(value: string): JsonValue {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (
      parsed === null ||
      typeof parsed === "string" ||
      typeof parsed === "number" ||
      typeof parsed === "boolean" ||
      Array.isArray(parsed) ||
      typeof parsed === "object"
    ) {
      return parsed as JsonValue;
    }
  } catch {
    return trimmed;
  }
  return trimmed;
}

function SettingRow({ setting }: { setting: SettingItem }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(
    typeof setting.value === "string" ? setting.value : JSON.stringify(setting.value),
  );

  useEffect(() => {
    setValue(typeof setting.value === "string" ? setting.value : JSON.stringify(setting.value));
  }, [setting]);

  const mutation = useMutation({
    mutationFn: () => api.updateSetting(setting.key, parseSettingValue(value)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings() });
    },
  });

  return (
    <div className="grid gap-2 rounded-xl border border-slate-100 p-3 sm:grid-cols-[minmax(0,180px)_minmax(0,1fr)_auto] sm:items-center">
      <div>
        <p className="font-mono text-xs font-semibold text-slate-700">{setting.key}</p>
        <p className="mt-0.5 text-[10px] text-slate-400">
          {typeof setting.value} · {setting.updated_at ? formatDate(setting.updated_at) : "默认值"}
        </p>
      </div>
      <Input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        aria-label={`配置值：${setting.key}`}
      />
      <Button size="sm" variant="outline" onClick={() => mutation.mutate()} loading={mutation.isPending}>
        保存
      </Button>
      {mutation.error ? (
        <p className="text-xs text-red-600 sm:col-span-3">{toErrorMessage(mutation.error)}</p>
      ) : null}
    </div>
  );
}

interface AccountProfileForm {
  name: string;
  audience: string;
  promise: string;
  tone: string;
  humor_boundaries: string;
  content_pillars: string;
  excluded_topics: string;
  preferred_formats: string[];
  default_domain: string;
}

const DEFAULT_ACCOUNT_PROFILE: AccountProfileForm = {
  name: "AI 娱乐观察",
  audience: "对 AI 好奇、但不想读技术报告的普通读者",
  promise: "用真实、有趣的场景讲清 AI 新鲜事与使用体验",
  tone: "轻松、具体、有自嘲感；先讲人和场景，再解释技术",
  humor_boundaries: "不编造真实人物言论；不把未实测写成亲测；虚构场景明确标注",
  content_pillars: "AI 新鲜事轻解读\nAI 工具真实体验\nAI × 游戏、乒乓与文学脑洞",
  excluded_topics: "",
  preferred_formats: ["hot_take", "tool_test", "creative_experiment"],
  default_domain: "有趣的 AI 产品、事件与使用场景",
};

const ACCOUNT_FORMATS = [
  { key: "hot_take", label: "热点轻解读" },
  { key: "tool_test", label: "AI 工具实测" },
  { key: "creative_experiment", label: "AI 脑洞实验" },
];

function profileForm(setting: SettingItem | undefined): AccountProfileForm {
  const value = setting?.value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return DEFAULT_ACCOUNT_PROFILE;
  const data = value as Record<string, JsonValue>;
  const text = (key: keyof AccountProfileForm) =>
    typeof data[key] === "string" ? String(data[key]) : DEFAULT_ACCOUNT_PROFILE[key] as string;
  const lines = (key: "content_pillars" | "excluded_topics") =>
    Array.isArray(data[key]) ? (data[key] as JsonValue[]).filter((item): item is string => typeof item === "string").join("\n") : DEFAULT_ACCOUNT_PROFILE[key];
  return {
    name: text("name"),
    audience: text("audience"),
    promise: text("promise"),
    tone: text("tone"),
    humor_boundaries: text("humor_boundaries"),
    content_pillars: lines("content_pillars"),
    excluded_topics: lines("excluded_topics"),
    default_domain: text("default_domain"),
    preferred_formats: Array.isArray(data.preferred_formats)
      ? data.preferred_formats.filter((item): item is string => typeof item === "string")
      : DEFAULT_ACCOUNT_PROFILE.preferred_formats,
  };
}

function AccountProfileTab({ setting }: { setting: SettingItem | undefined }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<AccountProfileForm>(() => profileForm(setting));
  useEffect(() => setForm(profileForm(setting)), [setting]);
  const update = (patch: Partial<AccountProfileForm>) => setForm((current) => ({ ...current, ...patch }));
  const mutation = useMutation({
    mutationFn: () => api.updateSetting("account_profile", {
      name: form.name.trim(),
      audience: form.audience.trim(),
      promise: form.promise.trim(),
      tone: form.tone.trim(),
      humor_boundaries: form.humor_boundaries.trim(),
      content_pillars: form.content_pillars.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      excluded_topics: form.excluded_topics.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      preferred_formats: form.preferred_formats,
      default_domain: form.default_domain.trim(),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.settings() }),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>账号画像</CardTitle>
        <p className="mt-1 text-sm text-slate-500">选题、大纲和写作会共用这里的定位；保存后对新生成内容生效。</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          {([
            ["name", "账号名称"], ["audience", "目标读者"], ["promise", "内容承诺"],
            ["tone", "表达语气"], ["default_domain", "默认选题方向"],
          ] as const).map(([key, label]) => (
            <div className="space-y-1.5" key={key}>
              <Label htmlFor={`profile-${key}`}>{label}</Label>
              <Input id={`profile-${key}`} value={form[key]} onChange={(event) => update({ [key]: event.target.value })} />
            </div>
          ))}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="profile-boundaries">幽默与事实边界</Label>
          <Textarea id="profile-boundaries" value={form.humor_boundaries} onChange={(event) => update({ humor_boundaries: event.target.value })} />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="profile-pillars">常写栏目（每行一项）</Label>
            <Textarea id="profile-pillars" rows={4} value={form.content_pillars} onChange={(event) => update({ content_pillars: event.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="profile-excluded">排除话题（每行一项）</Label>
            <Textarea id="profile-excluded" rows={4} value={form.excluded_topics} onChange={(event) => update({ excluded_topics: event.target.value })} />
          </div>
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium text-slate-800">AI 推荐可用的内容形式</p>
          <div className="flex flex-wrap gap-4">
            {ACCOUNT_FORMATS.map((item) => (
              <label key={item.key} className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={form.preferred_formats.includes(item.key)} onChange={(event) => update({ preferred_formats: event.target.checked ? [...form.preferred_formats, item.key] : form.preferred_formats.filter((key) => key !== item.key) })} />
                {item.label}
              </label>
            ))}
          </div>
        </div>
        {mutation.error ? <Alert variant="destructive">{toErrorMessage(mutation.error)}</Alert> : null}
        {mutation.isSuccess ? <Alert variant="success">账号画像已保存。</Alert> : null}
        <Button onClick={() => mutation.mutate()} loading={mutation.isPending} disabled={!form.name.trim() || !form.audience.trim() || !form.preferred_formats.length}>
          <Save className="h-4 w-4" aria-hidden="true" />保存账号画像
        </Button>
      </CardContent>
    </Card>
  );
}

const CONNECTIVITY_GROUPS = [
  { key: "feed", label: "热点信源" },
  { key: "search", label: "搜索工具" },
  { key: "media", label: "图片接口" },
  { key: "model", label: "模型接口" },
  { key: "platform", label: "发布平台" },
] as const;

function ConnectivityTab() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["connectivity-report"],
    queryFn: () => api.getConnectivityReport(),
  });
  const check = useMutation({
    mutationFn: () => api.runConnectivityCheck(),
    onSuccess: (report: ConnectivityReport) => {
      queryClient.setQueryData(["connectivity-report"], report);
    },
  });
  const report = query.data;
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <div>
          <CardTitle>外部服务检测</CardTitle>
          <p className="mt-1 text-sm text-slate-500">检测已配置的信源、搜索、图片、默认模型和公众号草稿接口。模型检测会产生一次极短的调用。</p>
        </div>
        <Button onClick={() => check.mutate()} loading={check.isPending} disabled={check.isPending}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />立即检测
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {query.isLoading ? <LoadingState label="加载最近检测结果…" /> : null}
        {query.isError ? <ErrorState message={toErrorMessage(query.error)} onRetry={() => void query.refetch()} /> : null}
        {check.isPending ? <Alert variant="info">正在逐项检测，通常需要几秒到半分钟。</Alert> : null}
        {check.isError ? <Alert variant="destructive">{toErrorMessage(check.error)}</Alert> : null}
        {report?.checked_at ? (
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span>最近检测：{formatDate(report.checked_at)}</span>
            <Badge variant="success">正常 {report.summary.ok}</Badge>
            <Badge variant="destructive">异常 {report.summary.failed}</Badge>
            <Badge variant="secondary">未检测 {report.summary.skipped}</Badge>
          </div>
        ) : !query.isLoading && !query.isError ? (
          <EmptyState title="尚未检测" description="点击“立即检测”获取各外部服务的当前状态。" />
        ) : null}
        {CONNECTIVITY_GROUPS.map((group) => {
          const items = report?.items.filter((item) => item.group === group.key) ?? [];
          if (!items.length) return null;
          return (
            <div key={group.key} className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-800">{group.label}</h3>
              <div className="divide-y rounded-xl border border-slate-200">
                {items.map((item) => (
                  <div key={item.key} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
                    <div className="min-w-0">
                      <div className="font-medium text-slate-800">{item.name}</div>
                      <div className="text-xs text-slate-500">{item.target}</div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-slate-600">{item.message}</span>
                      {item.status !== "skipped" ? <span className="text-xs text-slate-400">{item.latency_ms} ms</span> : null}
                      <Badge variant={item.status === "ok" ? "success" : item.status === "failed" ? "destructive" : "secondary"}>
                        {item.status === "ok" ? "正常" : item.status === "failed" ? "异常" : "未检测"}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("account");
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<ModelProfile | null>(null);
  const [deleteModel, setDeleteModel] = useState<ModelProfile | null>(null);

  const modelsQuery = useQuery({ queryKey: queryKeys.models(), queryFn: () => api.listModels() });
  const bindingsQuery = useQuery({
    queryKey: queryKeys.modelBindings(),
    queryFn: () => api.listModelBindings(),
  });
  const platformsQuery = useQuery({
    queryKey: queryKeys.platforms(),
    queryFn: () => api.listPlatforms(),
  });
  const settingsQuery = useQuery({
    queryKey: queryKeys.settings(),
    queryFn: () => api.listSettings(),
  });

  const toggleModelMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.updateModel(id, { enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.models() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelBindings() });
    },
  });

  const deleteModelMutation = useMutation({
    mutationFn: (id: string) => api.deleteModel(id),
    onSuccess: () => {
      setDeleteModel(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.models() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.modelBindings() });
    },
  });

  const autoReviewMutation = useMutation({
    mutationFn: (enabled: boolean) => api.updateSetting("auto_review_advance", enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings() });
    },
  });

  const models = modelsQuery.data?.items ?? [];
  const bindings = bindingsQuery.data?.items ?? [];
  const platforms = platformsQuery.data?.items ?? [];
  const settings = settingsQuery.data?.items ?? [];
  const autoReviewSetting = settings.find((item) => item.key === "auto_review_advance");
  const accountProfileSetting = settings.find((item) => item.key === "account_profile");
  const autoReviewEnabled = autoReviewSetting?.value === true;
  const refreshAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.models() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.modelBindings() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.platforms() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.settings() });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="设置"
        description="管理账号定位、模型、流程自动化、平台凭据与外部服务状态。凭据始终以掩码展示。"
        actions={
          <Button variant="outline" onClick={refreshAll}>
            <Settings2 className="h-4 w-4" aria-hidden="true" />
            刷新配置
          </Button>
        }
      />

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="account">账号画像</TabsTrigger>
          <TabsTrigger value="models">模型</TabsTrigger>
          <TabsTrigger value="workflow">流程设置</TabsTrigger>
          <TabsTrigger value="credentials">平台凭据</TabsTrigger>
          <TabsTrigger value="connectivity">服务检测</TabsTrigger>
        </TabsList>

        <TabsContent value="account">
          {settingsQuery.isLoading ? <LoadingState label="加载账号画像…" /> : null}
          {settingsQuery.isError ? <ErrorState message={toErrorMessage(settingsQuery.error)} onRetry={() => void settingsQuery.refetch()} /> : null}
          {!settingsQuery.isLoading && !settingsQuery.isError ? <AccountProfileTab setting={accountProfileSetting} /> : null}
        </TabsContent>

        <TabsContent value="models">
          <Card>
            <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
              <div>
                <CardTitle>模型档案</CardTitle>
                <p className="mt-1 text-sm text-slate-500">价格按每 1000 Token 记录，用于成本核算。</p>
              </div>
              <Button
                onClick={() => {
                  setEditingModel(null);
                  setModelDialogOpen(true);
                }}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                新建模型
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {modelsQuery.isLoading ? <LoadingState label="加载模型…" /> : null}
              {modelsQuery.isError ? (
                <ErrorState
                  message={toErrorMessage(modelsQuery.error)}
                  onRetry={() => void modelsQuery.refetch()}
                />
              ) : null}
              {toggleModelMutation.error ? (
                <Alert variant="destructive">{toErrorMessage(toggleModelMutation.error)}</Alert>
              ) : null}
              {!modelsQuery.isLoading && models.length === 0 ? (
                <EmptyState title="没有模型档案" description="创建一个 OpenAI 兼容模型开始使用。" />
              ) : null}
              {models.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>模型</TableHead>
                      <TableHead>接口</TableHead>
                      <TableHead className="text-right">输入价格</TableHead>
                      <TableHead className="text-right">输出价格</TableHead>
                      <TableHead>价格更新时间</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {models.map((model) => (
                      <TableRow key={model.id}>
                        <TableCell>
                          <p className="font-medium text-slate-800">{model.name}</p>
                          <p className="text-[11px] text-slate-400">{model.model}</p>
                        </TableCell>
                        <TableCell className="max-w-60 truncate text-xs text-slate-500">
                          {model.base_url || model.provider}
                          <p className="text-[10px] text-slate-400">Key: {model.api_key_env}</p>
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-xs">
                          {formatMoney(model.input_price_per_1k)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-xs">
                          {formatMoney(model.output_price_per_1k)}
                        </TableCell>
                        <TableCell className="text-xs text-slate-500">
                          {formatDate(model.updated_at)}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Switch
                              checked={model.enabled}
                              disabled={toggleModelMutation.isPending}
                              label={model.enabled ? "已启用" : "已停用"}
                              onCheckedChange={(enabled) =>
                                toggleModelMutation.mutate({ id: model.id, enabled })
                              }
                            />
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`编辑模型：${model.name}`}
                              onClick={() => {
                                setEditingModel(model);
                                setModelDialogOpen(true);
                              }}
                            >
                              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`删除模型：${model.name}`}
                              className="text-slate-400 hover:bg-red-50 hover:text-red-600"
                              onClick={() => setDeleteModel(model)}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden="true" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : null}
            </CardContent>
          </Card>
          <div className="mb-3 mt-6 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-800">阶段绑定</p>
              <p className="mt-1 text-sm text-slate-500">
                每个阶段可以指定独立的模型、温度与最大 Token。保存后立即对后续调用生效。
              </p>
            </div>
          </div>
          <ModelBindingsTab
            bindings={bindings}
            models={models}
            loading={bindingsQuery.isLoading || modelsQuery.isLoading}
            error={bindingsQuery.error ?? modelsQuery.error}
            onRetry={() => {
              void bindingsQuery.refetch();
              void modelsQuery.refetch();
            }}
          />
        </TabsContent>

        <TabsContent value="credentials">
          <div className="grid gap-4 xl:grid-cols-2">
            {platformsQuery.isLoading ? <LoadingState label="加载平台…" /> : null}
            {platformsQuery.isError ? (
              <ErrorState
                message={toErrorMessage(platformsQuery.error)}
                onRetry={() => void platformsQuery.refetch()}
              />
            ) : null}
            {!platformsQuery.isLoading && platforms.length === 0 ? (
              <EmptyState title="未发现平台适配器" description="刷新或检查后端平台注册。" />
            ) : null}
            {platforms.map((platform) => (
              <PlatformCredentialCard key={platform.key} platform={platform} />
            ))}
          </div>
          <Alert variant="info" className="mt-4" title="凭据安全">
            前端只展示后端返回的掩码。明文仅在你输入时短暂存在于表单内存，保存后立即清空。
          </Alert>
        </TabsContent>

        <TabsContent value="connectivity">
          <ConnectivityTab />
        </TabsContent>

        <TabsContent value="workflow">
          <Card>
            <CardHeader>
              <CardTitle>审稿与自动化</CardTitle>
              <p className="mt-1 text-sm text-slate-500">
                控制自动审稿通过后是否直接进入下一环节。
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-100 p-4">
                <div className="max-w-2xl">
                  <p className="text-sm font-medium text-slate-800">开启自动审稿</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {autoReviewEnabled
                      ? "审稿通过后自动进入排版与发布环节。"
                      : "审稿通过后只给出通过建议并暂停，等待人工确认后继续。"}
                  </p>
                </div>
                <Switch
                  checked={autoReviewEnabled}
                  disabled={settingsQuery.isLoading || autoReviewMutation.isPending}
                  label={autoReviewEnabled ? "已开启" : "已关闭"}
                  onCheckedChange={(enabled) => autoReviewMutation.mutate(enabled)}
                />
              </div>
              {autoReviewMutation.error ? (
                <Alert variant="destructive">{toErrorMessage(autoReviewMutation.error)}</Alert>
              ) : null}
              <div className="flex items-center gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />
                该开关对之后执行审稿的运行生效，默认关闭。
              </div>
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle>运行时配置</CardTitle>
              <p className="mt-1 text-sm text-slate-500">
                可直接编辑 JSON 值；布尔、数字与对象会被解析为对应类型。保存立即写入数据库。
              </p>
            </CardHeader>
            <CardContent className="space-y-2">
              {settingsQuery.isLoading ? <LoadingState label="加载配置…" /> : null}
              {settingsQuery.isError ? (
                <ErrorState
                  message={toErrorMessage(settingsQuery.error)}
                  onRetry={() => void settingsQuery.refetch()}
                />
              ) : null}
              {!settingsQuery.isLoading && settings.length === 0 ? (
                <EmptyState title="暂无配置项" description="后端初始化后会写入默认配置。" />
              ) : null}
              {settings
                .filter((setting) => !["auto_review_advance", "account_profile", "external_connectivity_latest"].includes(setting.key))
                .map((setting) => (
                  <SettingRow key={setting.key} setting={setting} />
                ))}
              <div className="flex items-center gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />
                修改发布确认、返工上限等设置会影响新启动的工作流。
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <ModelDialog
        open={modelDialogOpen}
        onOpenChange={setModelDialogOpen}
        editing={editingModel}
      />

      <Dialog
        open={deleteModel !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteModel(null);
            deleteModelMutation.reset();
          }
        }}
        labelledBy="delete-model-title"
      >
        <DialogHeader>
          <DialogTitle id="delete-model-title">删除模型档案</DialogTitle>
          <DialogDescription>
            确定删除「{deleteModel?.name}」吗？仍被阶段绑定的模型无法删除。
          </DialogDescription>
        </DialogHeader>
        <DialogContent>
          {deleteModelMutation.error ? (
            <Alert variant="destructive">{toErrorMessage(deleteModelMutation.error)}</Alert>
          ) : (
            <Alert variant="warning">删除前请先将阶段绑定切换到其他模型。</Alert>
          )}
        </DialogContent>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDeleteModel(null)}>
            取消
          </Button>
          <Button
            variant="destructive"
            loading={deleteModelMutation.isPending}
            onClick={() => {
              if (deleteModel) deleteModelMutation.mutate(deleteModel.id);
            }}
          >
            确认删除
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
