"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useApp, BotStatus } from "./Provider";

const NAV = [
  { href: "/", label: "Overview", icon: "◈" },
  { href: "/signals", label: "Signals", icon: "▲" },
  { href: "/trades", label: "Trades", icon: "◧" },
  { href: "/accounts", label: "Accounts", icon: "◉" },
  { href: "/backtest", label: "Backtest", icon: "↺" },
  { href: "/ai", label: "AI Engine", icon: "✦" },
  { href: "/risk", label: "Risk Center", icon: "⚠" },
  { href: "/sessions", label: "Sessions", icon: "◯" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

const STATUS_COLORS: Record<BotStatus, { bg: string; dot: string; text: string; label: string }> = {
  RUNNING: { bg: "bg-emerald-500/10 border-emerald-500/30", dot: "bg-emerald-400", text: "text-emerald-400", label: "RUNNING" },
  PAUSED: { bg: "bg-amber-500/10 border-amber-500/30", dot: "bg-amber-400", text: "text-amber-400", label: "PAUSED" },
  STOPPED: { bg: "bg-slate-500/10 border-slate-500/30", dot: "bg-slate-400", text: "text-slate-400", label: "STOPPED" },
  EMERGENCY_STOP: { bg: "bg-rose-500/10 border-rose-500/30", dot: "bg-rose-400", text: "text-rose-400", label: "EMERGENCY" },
};

export default function Sidebar() {
  const path = usePathname();
  const { bot, botCommand, emergencyStop, user, logout } = useApp();
  const [emergencyExpand, setEmergencyExpand] = useState(false);
  const [mode, setMode] = useState<"paper" | "live">("paper");
  const s = STATUS_COLORS[bot.status];

  return (
    <aside className="w-60 shrink-0 border-r border-[#2a3454] bg-[#0a0e1a] flex flex-col">
      <div className="px-5 py-5 border-b border-[#2a3454]">
        <div className="flex items-center gap-2">
          <div className="size-8 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-pink-500 flex items-center justify-center font-bold text-white shadow-lg">
            A
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-100">AAQTS</div>
            <div className="text-[10px] text-slate-500 uppercase tracking-widest">v2.0.0</div>
          </div>
        </div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV.map((item) => {
          const active = path === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                active
                  ? "bg-gradient-to-r from-indigo-500/20 to-violet-500/10 text-white border border-indigo-500/30"
                  : "text-slate-400 hover:text-slate-100 hover:bg-[#1e2540]"
              }`}
            >
              <span className={`text-lg ${active ? "text-indigo-400" : "text-slate-500"}`}>{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Master Bot Control (Feature 1) */}
      <div className="border-t border-[#2a3454] p-3 space-y-2">
        <div className={`rounded-lg border p-2.5 ${s.bg}`}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] uppercase tracking-widest text-slate-500">Bot Status</span>
            <span className={`flex items-center gap-1.5 text-[10px] font-bold ${s.text}`}>
              <span className={`size-1.5 rounded-full ${s.dot} ${bot.status === "RUNNING" ? "pulse-dot" : ""}`}></span>
              {s.label}
            </span>
          </div>
          <div className="flex items-center justify-between gap-1 mb-2">
            <span className="text-[10px] text-slate-500">Mode</span>
            <div className="flex rounded overflow-hidden border border-[#2a3454]">
              {(["paper", "live"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`px-2 py-0.5 text-[10px] font-semibold uppercase ${
                    (mode ?? bot.mode) === m ? (m === "live" ? "bg-rose-500/20 text-rose-300" : "bg-cyan-500/20 text-cyan-300") : "text-slate-500"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1">
            {bot.status === "STOPPED" || bot.status === "EMERGENCY_STOP" ? (
              <button
                onClick={() => bot.status === "EMERGENCY_STOP" ? botCommand("reset").then((ok) => ok && botCommand("start", mode ?? bot.mode)) : botCommand("start", mode)}
                className="col-span-2 py-1.5 text-[10px] font-bold rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/25"
              >
                ▶ START BOT
              </button>
            ) : bot.status === "PAUSED" ? (
              <>
                <button
                  onClick={() => botCommand("resume")}
                  className="py-1.5 text-[10px] font-bold rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/25"
                >
                  ▶ RESUME
                </button>
                <button
                  onClick={() => botCommand("stop")}
                  className="py-1.5 text-[10px] font-bold rounded bg-slate-500/15 text-slate-300 border border-slate-500/40 hover:bg-slate-500/25"
                >
                  ■ STOP
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={() => botCommand("pause")}
                  className="py-1.5 text-[10px] font-bold rounded bg-amber-500/15 text-amber-300 border border-amber-500/40 hover:bg-amber-500/25"
                >
                  ❚❚ PAUSE
                </button>
                <button
                  onClick={() => botCommand("stop")}
                  className="py-1.5 text-[10px] font-bold rounded bg-slate-500/15 text-slate-300 border border-slate-500/40 hover:bg-slate-500/25"
                >
                  ■ STOP
                </button>
              </>
            )}
          </div>
        </div>

        <button
          onClick={() => setEmergencyExpand(!emergencyExpand)}
          className="w-full py-1.5 text-[10px] font-bold rounded bg-rose-500/15 text-rose-300 border border-rose-500/40 hover:bg-rose-500/25"
        >
          ⚠ EMERGENCY STOP
        </button>
        {emergencyExpand && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-2 space-y-1.5">
            <div className="text-[9px] text-rose-300/80 leading-tight">
              Halts all trading immediately. Choose whether to close open positions.
            </div>
            <button
              onClick={() => { setEmergencyExpand(false); emergencyStop(false); }}
              className="w-full py-1 text-[10px] font-semibold rounded bg-rose-500/20 text-rose-200 border border-rose-500/40 hover:bg-rose-500/30"
            >
              Halt only
            </button>
            <button
              onClick={() => { setEmergencyExpand(false); emergencyStop(true); }}
              className="w-full py-1 text-[10px] font-semibold rounded bg-rose-600/30 text-rose-100 border border-rose-500/50 hover:bg-rose-600/40"
            >
              Halt + close all positions
            </button>
          </div>
        )}

        <div className="flex items-center justify-between pt-1 px-1">
          <div className="text-[10px] text-slate-500 truncate">
            {user ? `☺ ${user.username}` : ""}
          </div>
          <button onClick={logout} className="text-[10px] text-slate-500 hover:text-rose-300 font-semibold">
            LOGOUT
          </button>
        </div>
      </div>
    </aside>
  );
}
