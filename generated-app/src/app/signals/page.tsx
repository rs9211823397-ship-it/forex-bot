"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { useApp } from "@/components/Provider";
import { SYMBOLS, TIMEFRAMES } from "@/lib/engine/seed";

interface Signal {
  id: number;
  symbol: string;
  timeframe: string;
  action: string;
  quality: string;
  confidence: string;
  score: number;
  entryPrice: string | null;
  stopLoss: string | null;
  takeProfit: string | null;
  riskReward: string;
  regime: string;
  volatility: string;
  reasons: string[];
  indicators: Record<string, number>;
  executed: boolean;
  createdAt: string;
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [filter, setFilter] = useState<"all" | "buy" | "sell" | "hold">("all");
  const [qualityFilter, setQualityFilter] = useState<"all" | "A+" | "A" | "B" | "C" | "reject">("all");
  const { showToast } = useApp();

  const load = useCallback(async () => {
    const r = await fetch("/api/signals/all", { cache: "no-store" });
    const d = await r.json();
    setSignals(d.signals);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [load]);

  const execute = async (id: number) => {
    const r = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ signalId: id, mode: "paper" }),
    });
    const d = await r.json();
    if (d.executed) {
      showToast(`Executed on ${d.executed.length} account(s)`, "success");
    } else {
      showToast("No accounts accepted the trade", "error");
    }
  };

  const filtered = signals.filter((s) => {
    if (filter !== "all" && s.action !== filter) return false;
    if (qualityFilter !== "all" && s.quality !== qualityFilter) return false;
    return true;
  });

  return (
    <Shell>
      <div className="space-y-6">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Phase 1.4</div>
          <h1 className="text-3xl font-semibold gradient-text">Signal Engine</h1>
          <p className="text-sm text-slate-400 mt-1">All AI-generated trading signals with multi-indicator confluence</p>
        </div>

        <div className="card p-4 flex items-center gap-3 flex-wrap">
          <div className="text-xs text-slate-500 uppercase tracking-widest">Filters</div>
          <div className="flex gap-1.5">
            {(["all", "buy", "sell", "hold"] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1.5 text-xs rounded-lg font-semibold uppercase ${
                filter === f ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40" : "bg-[#0a0e1a] text-slate-400 border border-[#2a3454]"
              }`}>
                {f}
              </button>
            ))}
          </div>
          <div className="h-4 w-px bg-[#2a3454]"></div>
          <div className="flex gap-1.5">
            {(["all", "A+", "A", "B", "C", "reject"] as const).map((q) => (
              <button key={q} onClick={() => setQualityFilter(q)} className={`px-3 py-1.5 text-xs rounded-lg font-semibold ${
                qualityFilter === q ? "bg-amber-500/20 text-amber-300 border border-amber-500/40" : "bg-[#0a0e1a] text-slate-400 border border-[#2a3454]"
              }`}>
                {q}
              </button>
            ))}
          </div>
          <div className="ml-auto text-xs text-slate-500">
            Showing {filtered.length} of {signals.length} signals
          </div>
        </div>

        <div className="space-y-3">
          {filtered.map((s) => (
            <div key={s.id} className="card p-5">
              <div className="flex items-start gap-4">
                <div className="shrink-0">
                  <div className={`size-12 rounded-lg flex items-center justify-center text-lg font-bold ${
                    s.action === "buy" ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30" :
                    s.action === "sell" ? "bg-rose-500/15 text-rose-300 border border-rose-500/30" :
                    "bg-slate-500/15 text-slate-300 border border-slate-500/30"
                  }`}>
                    {s.action === "buy" ? "▲" : s.action === "sell" ? "▼" : "—"}
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <div className="text-lg font-semibold text-slate-100">{s.symbol}</div>
                    <Badge color="slate">{s.timeframe}</Badge>
                    <Badge color={s.action === "buy" ? "emerald" : s.action === "sell" ? "rose" : "slate"}>
                      {s.action.toUpperCase()}
                    </Badge>
                    <Badge color={s.quality === "A+" || s.quality === "A" ? "emerald" : s.quality === "B" ? "amber" : "slate"}>
                      {s.quality}
                    </Badge>
                    <Badge color={s.regime === "trending" ? "cyan" : s.regime === "ranging" ? "amber" : s.regime === "volatile" ? "rose" : "slate"}>
                      {s.regime.replace("_", " ")}
                    </Badge>
                    {s.executed && <Badge color="emerald">✓ Executed</Badge>}
                  </div>
                  <div className="text-xs text-slate-500">{new Date(s.createdAt).toLocaleString()}</div>

                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-3">
                    <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                      <div className="text-[10px] text-slate-500">Score</div>
                      <div className="text-sm font-mono text-slate-100">{s.score}/100</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                      <div className="text-[10px] text-slate-500">Confidence</div>
                      <div className="text-sm font-mono text-indigo-400">{Number(s.confidence).toFixed(1)}%</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                      <div className="text-[10px] text-slate-500">Entry</div>
                      <div className="text-sm font-mono text-slate-200">{s.entryPrice ? Number(s.entryPrice).toFixed(5) : "—"}</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                      <div className="text-[10px] text-slate-500">Stop</div>
                      <div className="text-sm font-mono text-rose-400">{s.stopLoss ? Number(s.stopLoss).toFixed(5) : "—"}</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                      <div className="text-[10px] text-slate-500">Target</div>
                      <div className="text-sm font-mono text-emerald-400">{s.takeProfit ? Number(s.takeProfit).toFixed(5) : "—"}</div>
                    </div>
                  </div>

                  {s.reasons && s.reasons.length > 0 && (
                    <details className="mt-3">
                      <summary className="text-[10px] text-slate-500 uppercase cursor-pointer hover:text-slate-300">Show reasons ({s.reasons.length})</summary>
                      <div className="mt-2 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3 space-y-0.5 max-h-40 overflow-y-auto">
                        {s.reasons.map((r, i) => (
                          <div key={i} className="text-xs font-mono text-slate-300">{r}</div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
                {!s.executed && s.action !== "hold" && s.quality !== "reject" && (
                  <button onClick={() => execute(s.id)} className="px-3 py-2 text-xs rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/20 font-semibold">
                    Execute →
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {filtered.length === 0 && (
          <div className="card p-12 text-center">
            <div className="text-slate-500 mb-2">No signals match filters</div>
            <div className="text-xs text-slate-600">Go to Overview to generate new signals</div>
          </div>
        )}
      </div>
    </Shell>
  );
}
