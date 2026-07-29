"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { useApp } from "@/components/Provider";
import { SYMBOLS, TIMEFRAMES } from "@/lib/engine/seed";

interface Backtest {
  id: number;
  name: string;
  symbol: string;
  timeframe: string;
  startDate: string;
  endDate: string;
  initialBalance: string;
  finalBalance: string;
  totalTrades: number;
  winningTrades: number;
  losingTrades: number;
  winRate: string;
  profitFactor: string;
  maxDrawdown: string;
  sharpeRatio: string;
  averageRR: string;
  strategyRating: string;
  createdAt: string;
}

export default function BacktestPage() {
  const [runs, setRuns] = useState<Backtest[]>([]);
  const [form, setForm] = useState({
    name: "Test Run",
    symbol: "EURUSD",
    timeframe: "H1",
    candleCount: 1000,
    initialBalance: 10000,
  });
  const [running, setRunning] = useState(false);
  const { showToast } = useApp();

  const load = useCallback(async () => {
    const r = await fetch("/api/backtest", { cache: "no-store" });
    const d = await r.json();
    setRuns(d.backtests);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const runBacktest = async () => {
    setRunning(true);
    showToast("Running backtest…", "info");
    try {
      const r = await fetch("/api/backtest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (r.ok) {
        showToast("Backtest complete", "success");
        load();
      } else {
        showToast("Backtest failed", "error");
      }
    } finally {
      setRunning(false);
    }
  };

  return (
    <Shell>
      <div className="space-y-6">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Phase 3</div>
          <h1 className="text-3xl font-semibold gradient-text">Backtesting Engine</h1>
          <p className="text-sm text-slate-400 mt-1">Walk-forward historical testing with strategy rating</p>
        </div>

        <div className="card p-5">
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">New Backtest</div>
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
            <div>
              <label className="text-[10px] text-slate-500 uppercase">Name</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase">Symbol</label>
              <select value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm">
                {SYMBOLS.map((s) => <option key={s.ticker} value={s.ticker}>{s.ticker}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase">Timeframe</label>
              <select value={form.timeframe} onChange={(e) => setForm({ ...form, timeframe: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm">
                {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase">Candles</label>
              <input type="number" value={form.candleCount} onChange={(e) => setForm({ ...form, candleCount: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
            </div>
            <div>
              <label className="text-[10px] text-slate-500 uppercase">Initial Balance</label>
              <input type="number" value={form.initialBalance} onChange={(e) => setForm({ ...form, initialBalance: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
            </div>
            <div className="flex items-end">
              <button onClick={runBacktest} disabled={running} className="w-full py-2 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 hover:bg-indigo-500/30 text-sm font-semibold disabled:opacity-50">
                {running ? "Running…" : "Run Backtest"}
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          {runs.map((r) => {
            const totalReturn = ((Number(r.finalBalance) - Number(r.initialBalance)) / Number(r.initialBalance)) * 100;
            return (
              <div key={r.id} className="card p-5">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <div className="text-lg font-semibold text-slate-100">{r.name}</div>
                      <Badge color={r.strategyRating === "A+" ? "emerald" : r.strategyRating === "A" ? "cyan" : r.strategyRating === "B" ? "amber" : "rose"}>
                        Rating: {r.strategyRating}
                      </Badge>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {r.symbol} • {r.timeframe} • {new Date(r.startDate).toLocaleDateString()} → {new Date(r.endDate).toLocaleDateString()}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-slate-500">Total Return</div>
                    <div className={`text-2xl font-bold font-mono ${totalReturn >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                      {totalReturn >= 0 ? "+" : ""}{totalReturn.toFixed(2)}%
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">${Number(r.initialBalance).toFixed(0)} → ${Number(r.finalBalance).toFixed(0)}</div>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-7 gap-2">
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Trades</div>
                    <div className="text-sm font-mono text-slate-200">{r.totalTrades}</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Win Rate</div>
                    <div className={`text-sm font-mono ${Number(r.winRate) >= 50 ? "text-emerald-400" : "text-rose-400"}`}>{Number(r.winRate).toFixed(1)}%</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Wins</div>
                    <div className="text-sm font-mono text-emerald-400">{r.winningTrades}</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Losses</div>
                    <div className="text-sm font-mono text-rose-400">{r.losingTrades}</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Profit Factor</div>
                    <div className="text-sm font-mono text-amber-400">{Number(r.profitFactor).toFixed(2)}</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Max DD</div>
                    <div className="text-sm font-mono text-rose-400">{Number(r.maxDrawdown).toFixed(1)}%</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                    <div className="text-[10px] text-slate-500">Sharpe</div>
                    <div className="text-sm font-mono text-indigo-400">{Number(r.sharpeRatio).toFixed(2)}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {runs.length === 0 && (
          <div className="card p-12 text-center">
            <div className="text-slate-500 mb-2">No backtests yet</div>
            <div className="text-xs text-slate-600">Run a backtest above to see results</div>
          </div>
        )}
      </div>
    </Shell>
  );
}
