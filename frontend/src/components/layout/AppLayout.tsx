import { NavLink, Outlet } from "react-router-dom";
import { BarChart3, Bot, Layers3, Settings2, Sparkles, Workflow } from "lucide-react";
import { cn } from "../../lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "文章工作台", icon: Workflow, end: true },
  { to: "/analytics", label: "运维分析", icon: BarChart3 },
  { to: "/skills", label: "技能管理", icon: Sparkles },
  { to: "/evolution", label: "自进化", icon: Bot },
  { to: "/settings", label: "设置", icon: Settings2 },
];

export function AppLayout() {
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-40 border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-3 px-4 py-3 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center justify-between gap-4">
            <NavLink to="/" className="flex items-center gap-3" aria-label="返回文章工作台">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-600 to-violet-500 text-white shadow-md shadow-indigo-200">
                <Layers3 className="h-5 w-5" aria-hidden="true" />
              </span>
              <span>
                <span className="block text-sm font-bold tracking-tight text-slate-900">
                  Article Autopilot
                </span>
                <span className="block text-[11px] font-medium tracking-wide text-slate-400">
                  文章自动驾驶控制台
                </span>
              </span>
            </NavLink>
            <span className="hidden rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 sm:inline-flex">
              本地模式
            </span>
          </div>

          <nav aria-label="主导航" className="scrollbar-thin -mx-1 overflow-x-auto">
            <div className="flex min-w-max items-center gap-1 px-1">
              {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900",
                      isActive && "bg-indigo-50 text-indigo-700 hover:bg-indigo-50 hover:text-indigo-700",
                    )
                  }
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  {label}
                </NavLink>
              ))}
            </div>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:py-8">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-[1600px] px-4 pb-8 pt-4 text-xs text-slate-400 sm:px-6">
        Article Autopilot · 单机本地工作流 · 所有发布与模型调用均由你掌控
      </footer>
    </div>
  );
}
