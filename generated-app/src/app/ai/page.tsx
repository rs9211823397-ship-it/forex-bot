"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { StatCard } from "@/components/StatCard";

interface AIData {
  decisions: Array<{ id: number; symbol: string; action: string; quality: string; confidence: string; regime: string | null; outcome: string | null; reward: string | null; createdAt: string }>;
  summary: {
    totalTrades: number;
    wins: number;
    losses: number;
    winRate: number;
    totalProfit: number;
    bySymbol: Record<string, { wins: number; losses: number; profit: number; trades: number }>;
    byQuality: Record<string, { wins: number; losses: number; total: number }>;
  };
}

export default function AIPage() {
  const [data, setData] = useState<AIData | null>(null);

  const load = useCallback(async () => {
    const r = await fetch("/api/ai", { cache: "no-store" });
    const d = await r.json();
    setData(d);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  if (!data) {
    return (
      <Shell>
        <div className="grid place-items-center h-96 text-slate-500 text-sm">Loading AI engine…</div>
      </Shell>
    );
  }

  const symbolEntries = Object.entries(data.summary.bySymbol).sort((a, b) => b[1].profit - a[1].profit);
  const qualityEntries = Object.entries(data.summary.byQuality);

  return (
    <Shell>
      <div className="space-y-6">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Phase 7 & 11</div>
          <h1 className="text-3xl font-semibold gradient-text">AI Trade Quality Engine</h1>
          <p className="text-sm text-slate-400 mt-1">Reinforcement learning from winning and losing trades</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <StatCard label="Total Trades" value={data.summary.totalTrades} color="indigo" icon="∑" />
          <StatCard label="Wins" value={data.summary.wins} color="emerald" icon="✓" />
          <StatCard label="Losses" value={data.summary.losses} color="rose" icon="✗" />
          <StatCard
            label="Win Rate"
            value={`${data.summary.winRate.toFixed(1)}%`}
            color={data.summary.winRate >= 50 ? "emerald" : "amber"}
            icon="%"
            trend={data.summary.winRate >= 50 ? "up" : "down"}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Performance by Symbol</div>
            <div className="space-y-2">
              {symbolEntries.length === 0 ? (
                <div className="text-slate-500 text-xs py-8 text-center">No data yet — close some trades</div>
              ) : (
                symbolEntries.map(([sym, s]) => {
                  const wr = s.trades > 0 ? (s.wins / s.trades) * 100 : 0;
                  return (
                    <div key={sym} className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                      <div className="flex items-center justify-between mb-1">
                        <div className="font-medium text-slate-100">{sym}</div>
                        <div className={`font-mono font-semibold ${s.profit >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {s.profit >= 0 ? "+" : ""}${s.profit.toFixed(2)}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-[#2a3454] rounded-full h-1.5">
                          <div className="h-1.5 rounded-full bg-emerald-500" style={{ width: `${wr}%` }}></div>
                        </div>
                        <div className="text-[10px] text-slate-500 w-20 text-right">
                          {wr.toFixed(0)}% • {s.trades}T
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Performance by Signal Quality</div>
            <div className="space-y-2">
              {qualityEntries.length === 0 ? (
                <div className="text-slate-500 text-xs py-8 text-center">No quality data yet</div>
              ) : (
                qualityEntries.map(([q, s]) => {
                  const wr = s.total > 0 ? (s.wins / s.total) * 100 : 0;
                  return (
                    <div key={q} className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <Badge color={q === "A+" || q === "A" ? "emerald" : q === "B" ? "amber" : "slate"}>{q}</Badge>
                          <span className="text-xs text-slate-400">{s.total} trades</span>
                        </div>
                        <div className="text-sm font-mono text-slate-200">{wr.toFixed(1)}%</div>
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {s.wins} wins / {s.losses} losses
                      </div>
                    </div>
                  );
                })
              )}
            </div>
            <div className="mt-4 rounded-lg bg-indigo-500/5 border border-indigo-500/20 p-3 text-xs text-slate-400">
              <div className="text-indigo-300 font-semibold mb-1">AI Insight</div>
              The engine tracks which signal grades and regimes yield the highest reward, then reinforces high-quality setups in future signals.
            </div>
          </div>
        </div>

        <div className="card p-5">
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Recent AI Decisions</div>
          <div className="space-y-1.5 max-h-96 overflow-y-auto">
            {data.decisions.length === 0 ? (
              <div className="text-slate-500 text-xs py-8 text-center">No decisions yet</div>
            ) : (
              data.decisions.slice(0, 30).map((d) => (
                <div key={d.id} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2.5">
                  <div className="text-xs font-mono text-slate-400 w-20">{new Date(d.createdAt).toLocaleTimeString()}</div>
                  <Badge color={d.action === "buy" ? "emerald" : d.action === "sell" ? "rose" : "slate"}>{d.action}</Badge>
                  <div className="text-sm text-slate-200 flex-1">{d.symbol}</div>
                  <Badge color={d.quality === "A+" || d.quality === "A" ? "emerald" : "slate"}>{d.quality}</Badge>
                  <div className="text-xs text-slate-400 w-16 text-right">{Number(d.confidence).toFixed(0)}%</div>
                  {d.outcome && (
                    <Badge color={d.outcome === "win" ? "emerald" : d.outcome === "loss" ? "rose" : "amber"}>
                      {d.outcome}
                    </Badge>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}
