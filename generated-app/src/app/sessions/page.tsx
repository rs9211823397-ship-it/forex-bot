"use client";

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";

const SESSIONS = [
  { name: "Sydney", open: 0, close: 7, color: "indigo" },
  { name: "Tokyo (Asian)", open: 0, close: 9, color: "pink" },
  { name: "Frankfurt", open: 6, close: 16, color: "amber" },
  { name: "London", open: 7, close: 16, color: "cyan" },
  { name: "New York", open: 12, close: 21, color: "emerald" },
  { name: "London+NY Overlap", open: 12, close: 16, color: "violet" },
];

const SYMBOL_SESSIONS: Record<string, string[]> = {
  EURUSD: ["London", "New York", "Frankfurt"],
  GBPUSD: ["London", "New York"],
  USDJPY: ["Tokyo (Asian)", "New York", "London+NY Overlap"],
  AUDUSD: ["Sydney", "Tokyo (Asian)", "London"],
  USDCAD: ["London", "New York"],
  USDCHF: ["London", "Frankfurt"],
  NZDUSD: ["Sydney", "Tokyo (Asian)", "London"],
  XAUUSD: ["London", "New York", "London+NY Overlap"],
  XAGUSD: ["London", "New York"],
  BTCUSD: ["New York", "London", "London+NY Overlap"],
  ETHUSD: ["New York", "London", "London+NY Overlap"],
  SOLUSD: ["New York", "London"],
};

const HIGH_IMPACT_EVENTS = [
  { time: "08:30", date: "Today", title: "USD CPI (m/m)", impact: "high" },
  { time: "10:00", date: "Today", title: "USD Consumer Sentiment", impact: "medium" },
  { time: "14:00", date: "Tomorrow", title: "FOMC Member Powell Speaks", impact: "high" },
  { time: "08:30", date: "Friday", title: "USD NFP", impact: "high" },
  { time: "12:30", date: "Next Week", title: "GBP BOE Rate Decision", impact: "high" },
];

export default function SessionsPage() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const hour = now ? now.getUTCHours() : 0;
  const minute = now ? now.getUTCMinutes() : 0;
  const currentHour = hour + minute / 60;

  return (
    <Shell>
      <div className="space-y-6">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Phase 9</div>
          <h1 className="text-3xl font-semibold gradient-text">Sessions & News</h1>
          <p className="text-sm text-slate-400 mt-1">Trading session map and economic calendar intelligence</p>
        </div>

        <div className="card p-5">
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-4">24-Hour Session Map (UTC)</div>
          <div className="relative h-32">
            {/* Hour markers */}
            <div className="absolute inset-x-0 top-0 flex justify-between text-[9px] text-slate-600">
              {Array.from({ length: 25 }).map((_, i) => (
                <span key={i}>{i % 24}</span>
              ))}
            </div>
            {/* Sessions */}
            <div className="absolute inset-x-0 top-6 bottom-0 space-y-1.5">
              {SESSIONS.map((s) => {
                const left = (s.open / 24) * 100;
                const width = ((s.close - s.open) / 24) * 100;
                const colors: Record<string, string> = {
                  indigo: "bg-indigo-500/30 border-indigo-500/50 text-indigo-200",
                  pink: "bg-pink-500/30 border-pink-500/50 text-pink-200",
                  amber: "bg-amber-500/30 border-amber-500/50 text-amber-200",
                  cyan: "bg-cyan-500/30 border-cyan-500/50 text-cyan-200",
                  emerald: "bg-emerald-500/30 border-emerald-500/50 text-emerald-200",
                  violet: "bg-violet-500/30 border-violet-500/50 text-violet-200",
                };
                const isActive = currentHour >= s.open && currentHour < s.close;
                return (
                  <div key={s.name} className="relative h-5">
                    <div
                      className={`absolute h-full rounded border ${colors[s.color]} ${isActive ? "ring-1 ring-white/30" : ""} flex items-center justify-center text-[10px] font-medium`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                    >
                      {s.name}
                    </div>
                  </div>
                );
              })}
            </div>
            {/* Current time indicator */}
            <div
              className="absolute top-4 bottom-0 w-0.5 bg-white z-10"
              style={{ left: `${(currentHour / 24) * 100}%` }}
            >
              <div className="absolute -top-3 -translate-x-1/2 px-1.5 py-0.5 bg-white text-black text-[9px] font-bold rounded">
                NOW
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Economic Calendar (Next Events)</div>
            <div className="space-y-2">
              {HIGH_IMPACT_EVENTS.map((e, i) => (
                <div key={i} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                  <div className="text-center shrink-0 w-16">
                    <div className="text-sm font-mono font-semibold text-slate-200">{e.time}</div>
                    <div className="text-[9px] text-slate-500">UTC</div>
                  </div>
                  <div className="flex-1">
                    <div className="text-sm text-slate-200">{e.title}</div>
                    <div className="text-[10px] text-slate-500">{e.date}</div>
                  </div>
                  <Badge color={e.impact === "high" ? "rose" : "amber"}>
                    {e.impact === "high" ? "HIGH" : "MED"}
                  </Badge>
                </div>
              ))}
            </div>
            <div className="mt-3 rounded-lg bg-amber-500/5 border border-amber-500/20 p-3 text-xs text-amber-300/80">
              ⚠ Avoid opening new positions 15 min before high-impact events.
            </div>
          </div>

          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Symbol Best Sessions</div>
            <div className="space-y-1.5">
              {Object.entries(SYMBOL_SESSIONS).map(([sym, sessions]) => (
                <div key={sym} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2.5">
                  <div className="font-mono font-medium text-slate-200 w-20">{sym}</div>
                  <div className="flex-1 flex flex-wrap gap-1">
                    {sessions.map((s) => (
                      <Badge key={s} color={
                        s === "London" || s === "London+NY Overlap" ? "cyan" :
                        s === "New York" ? "emerald" :
                        s === "Tokyo (Asian)" || s === "Sydney" ? "pink" : "amber"
                      }>{s}</Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
