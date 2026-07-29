"use client";
import { ReactNode } from "react";

export function Badge({ children, color = "slate" }: { children: ReactNode; color?: "slate" | "emerald" | "rose" | "amber" | "indigo" | "cyan" | "pink" | "violet" }) {
  const colors: Record<string, string> = {
    slate: "bg-slate-500/10 text-slate-300 border-slate-500/30",
    emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    rose: "bg-rose-500/10 text-rose-300 border-rose-500/30",
    amber: "bg-amber-500/10 text-amber-300 border-amber-500/30",
    indigo: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30",
    cyan: "bg-cyan-500/10 text-cyan-300 border-cyan-500/30",
    pink: "bg-pink-500/10 text-pink-300 border-pink-500/30",
    violet: "bg-violet-500/10 text-violet-300 border-violet-500/30",
  };
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wide border ${colors[color]}`}>{children}</span>;
}
