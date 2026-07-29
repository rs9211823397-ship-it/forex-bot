"use client";
import { ReactNode } from "react";

export function StatCard({ label, value, change, icon, color = "indigo", trend }: { label: string; value: ReactNode; change?: string; icon?: string; color?: "indigo" | "emerald" | "rose" | "amber" | "cyan" | "violet"; trend?: "up" | "down" | "neutral" }) {
  const colors: Record<string, string> = {
    indigo: "from-indigo-500/20 to-violet-500/5 border-indigo-500/30 text-indigo-300",
    emerald: "from-emerald-500/20 to-emerald-500/5 border-emerald-500/30 text-emerald-300",
    rose: "from-rose-500/20 to-rose-500/5 border-rose-500/30 text-rose-300",
    amber: "from-amber-500/20 to-amber-500/5 border-amber-500/30 text-amber-300",
    cyan: "from-cyan-500/20 to-cyan-500/5 border-cyan-500/30 text-cyan-300",
  };
  return (
    <div className={`rounded-xl bg-gradient-to-br ${colors[color]} border p-4 relative overflow-hidden`}>
      <div className="flex items-start justify-between mb-2">
        <div className="text-[10px] uppercase tracking-widest text-slate-400">{label}</div>
        {icon && <div className="text-lg opacity-60">{icon}</div>}
      </div>
      <div className="text-2xl font-semibold text-slate-100">{value}</div>
      {change && (
        <div className={`mt-1 text-xs flex items-center gap-1 ${
          trend === "up" ? "text-emerald-400" : trend === "down" ? "text-rose-400" : "text-slate-400"
        }`}>
          {trend === "up" ? "▲" : trend === "down" ? "▼" : "—"} {change}
        </div>
      )}
    </div>
  );
}
