import type { ReactNode } from "react";
import { Clock3, Cpu, Coins, Hash } from "lucide-react";
import type { StageRun } from "../../../types";
import { formatDuration, formatNumber, formatMoney } from "../../../lib/utils";
import { StatusBadge } from "../../common/StatusBadge";

interface PanelShellProps {
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function PanelShell({ title, description, actions, children }: PanelShellProps) {
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
          <p className="mt-0.5 text-sm text-slate-500">{description}</p>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function StageRunSummary({ stageRun }: { stageRun: StageRun | null }) {
  if (!stageRun) {
    return (
      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-4 py-3 text-xs text-slate-500">
        该阶段尚无运行记录。启动工作流后，这里会显示模型、Token 与耗时。
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs sm:grid-cols-4">
      <div className="flex items-center gap-2 text-slate-500">
        <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{formatDuration(stageRun.started_at, stageRun.finished_at)}</span>
      </div>
      <div className="flex items-center gap-2 text-slate-500">
        <Cpu className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="truncate">{stageRun.model ?? "未记录模型"}</span>
      </div>
      <div className="flex items-center gap-2 text-slate-500">
        <Hash className="h-3.5 w-3.5" aria-hidden="true" />
        <span>
          {formatNumber(stageRun.prompt_tokens)} / {formatNumber(stageRun.completion_tokens)}
        </span>
      </div>
      <div className="flex items-center gap-2 text-slate-500">
        <Coins className="h-3.5 w-3.5" aria-hidden="true" />
        <span>{formatMoney(stageRun.cost)}</span>
      </div>
      <div className="col-span-2 sm:col-span-4">
        <StatusBadge kind="stage" status={stageRun.status} />
      </div>
      {stageRun.error ? (
        <p className="col-span-2 rounded-md bg-red-50 px-2 py-1.5 text-red-700 sm:col-span-4">
          {stageRun.error}
        </p>
      ) : null}
    </div>
  );
}

export function MetaLine({ children }: { children: ReactNode }) {
  return <p className="text-xs text-slate-400">{children}</p>;
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold text-slate-800">{children}</h3>
      {action}
    </div>
  );
}
