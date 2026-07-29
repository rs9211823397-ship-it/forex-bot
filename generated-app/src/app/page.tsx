"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/Badge";
import { Sparkline, BarChart } from "@/components/Sparkline";
import { SYMBOLS, TIMEFRAMES } from "@/lib/engine/seed";
import { useApp } from "@/components/Provider";

function BotBanner() {
  const { bot, botCommand } = useApp();
  const styles: Record<string, string> = {
    RUNNING: "border-emerald-500/40 bg-emerald-500/5",
    PAUSED: "border-amber-500/40 bg-amber-500/5",
    STOPPED: "border-slate-500/40 bg-slate-500/5",
    EMERGENCY_STOP: "border-rose-500/40 bg-rose-500/5",
  };
  const labels: Record<string, { title: string; desc: string }> = {
    RUNNING: { title: "Bot is RUNNING", desc: "Signals → risk checks → execution are automatic across all enabled accounts." },
    PAUSED: { title: "Bot is PAUSED", desc: "Market monitoring continues; new trade execution is blocked. Resume any time." },
    STOPPED: { title: "Bot is STOPPED", desc: "No new signals or trades. Open positions continue to be monitored." },
    EMERGENCY_STOP: { title: "EMERGENCY STOP ACTIVE", desc: "All trading halted. Issue RESET from the sidebar to re-enable." },
  };
  const l = labels[bot.status];
  return (
    <div className={`card p-4 border ${styles[bot.status]} flex items-center justify-between gap-4`}>
      <div className="flex items-center gap-3">
        <div className={`size-2.5 rounded-full ${bot.status === "RUNNING" ? "bg-emerald-400 pulse-dot" : bot.status === "PAUSED" ? "bg-amber-400" : bot.status === "EMERGENCY_STOP" ? "bg-rose-400" : "bg-slate-400"}`}></div>
        <div>
          <div className="text-sm font-bold text-slate-100">{l.title} <span className="text-slate-500 font-normal">• {bot.mode.toUpperCase()} mode</span></div>
          <div className="text-xs text-slate-500">{l.desc}</div>
        </div>
      </div>
      <div className="flex gap-2">
        {bot.status === "STOPPED" && (
          <button onClick={() => botCommand("start", bot.mode)} className="px-4 py-2 text-xs font-bold rounded-lg bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/25">▶ Start Bot</button>
        )}
        {bot.status === "RUNNING" && (
          <button onClick={() => botCommand("pause")} className="px-4 py-2 text-xs font-bold rounded-lg bg-amber-500/15 text-amber-300 border border-amber-500/40 hover:bg-amber-500/25">❚❚ Pause</button>
        )}
        {bot.status === "PAUSED" && (
          <button onClick={() => botCommand("resume")} className="px-4 py-2 text-xs font-bold rounded-lg bg-emerald-500/15 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-500/25">▶ Resume</button>
        )}
        {bot.status === "EMERGENCY_STOP" && (
          <button onClick={() => botCommand("reset")} className="px-4 py-2 text-xs font-bold rounded-lg bg-slate-500/15 text-slate-300 border border-slate-500/40 hover:bg-slate-500/25">Reset</button>
        )}
      </div>
    </div>
  );
}

function SeedBanner({ onDone }: { onDone: () => void }) {
  const { showToast } = useApp();
  const [busy, setBusy] = useState(false);
  const seed = async () => {
    setBusy(true);
    const r = await fetch("/api/seed", { method: "POST" });
    if (r.ok) {
      showToast("Demo data loaded", "success");
      onDone();
    } else {
      showToast("Seed failed", "error");
    }
    setBusy(false);
  };
  return (
    <div className="card p-6 border-indigo-500/40 bg-indigo-500/5 text-center">
      <div className="text-lg font-semibold text-slate-100 mb-1">Welcome to AAQTS</div>
      <div className="text-sm text-slate-400 mb-4">No trading accounts exist yet. Load demo data (5 Exness/ICM accounts, sample trades & signals) or add accounts manually.</div>
      <button onClick={seed} disabled={busy} className="px-5 py-2.5 text-sm font-semibold rounded-lg bg-indigo-500/20 text-indigo-200 border border-indigo-500/40 hover:bg-indigo-500/30 disabled:opacity-50">
        {busy ? "Loading…" : "Load demo data"}
      </button>
    </div>
  );
}

interface DashboardData {
  accounts: Array<{ id: number; name: string; accountNumber: string; broker: string; accountType: string; status: string; balance: string; equity: string; riskPercent: string; }>;
  openTrades: Array<{ id: number; accountId: number; symbol: string; direction: string; lots: string; entryPrice: string; stopLoss: string | null; takeProfit: string | null; profit: string; openedAt: string; }>;
  closedTrades: Array<{ id: number; symbol: string; direction: string; profit: string; closedAt: string | null; quality: string | null; }>;
  signals: Array<{ id: number; symbol: string; action: string; quality: string; confidence: string; score: number; recommendation: string; createdAt: string; timeframe: string; executed: boolean; }>;
  regimes: Array<{ symbol: string; timeframe: string; regime: string; volatility: string; recommendation: string; createdAt: string; }>;
  metrics: {
    totalAccounts: number; activeAccounts: number; openPositions: number;
    totalBalance: number; totalEquity: number; totalPnL: number;
    winRate: number; profitFactor: number; totalTrades: number;
  };
  equityCurve: Array<{ x: number; balance: number }>;
}

interface SignalAnalysis {
  action: string; quality: string; confidence: number; score: number;
  reasons: string[]; regime: string; volatility: string; recommendation: string;
  entryPrice?: number; stopLoss?: number; takeProfit?: number;
  riskReward: number; indicators: Record<string, number>;
}

export default function Overview() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [symbol, setSymbol] = useState("EURUSD");
  const [timeframe, setTimeframe] = useState("H1");
  const [analysis, setAnalysis] = useState<SignalAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const { showToast } = useApp();

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/dashboard", { cache: "no-store" });
      const d = await r.json();
      setData(d);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const runAnalysis = useCallback(async (force = false) => {
    setAnalyzing(true);
    try {
      const r = await fetch(`/api/signals?symbol=${symbol}&timeframe=${timeframe}${force ? "&force=1" : ""}`, { cache: "no-store" });
      const d = await r.json();
      setAnalysis(d.signal);
    } catch (e) {
      console.error(e);
    } finally {
      setAnalyzing(false);
    }
  }, [symbol, timeframe]);

  useEffect(() => {
    runAnalysis(false);
  }, [runAnalysis]);

  const saveAndExecute = useCallback(async (action: "buy" | "sell") => {
    try {
      // Save signal
      const r = await fetch("/api/signals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, symbol, timeframe }),
      });
      const d = await r.json();
      if (!d.signal) {
        showToast(d.error || "Signal rejected", "error");
        return;
      }
      // Execute across accounts
      const ex = await fetch("/api/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signalId: d.signal.id, mode: "paper" }),
      });
      const exData = await ex.json();
      const executed = exData.executed?.length || 0;
      showToast(`${action.toUpperCase()} ${symbol} executed on ${executed} account(s)`, "success");
      load();
    } catch (e) {
      console.error(e);
      showToast("Execution failed", "error");
    }
  }, [symbol, timeframe, showToast, load]);

  if (!data) {
    return (
      <Shell>
        <div className="grid place-items-center h-96">
          <div className="text-slate-500 text-sm">Loading system state…</div>
        </div>
      </Shell>
    );
  }

  const recentPnL = data.closedTrades.slice(0, 30).map((t) => Number(t.profit));
  const winSymbolCount = data.closedTrades.filter((t) => Number(t.profit) > 0).length;
  const lossSymbolCount = data.closedTrades.filter((t) => Number(t.profit) < 0).length;

  return (
    <Shell>
      <div className="space-y-6">
        {/* Bot status banner (Feature 1) */}
        <BotBanner />
        {data.metrics.totalAccounts === 0 && <SeedBanner onDone={load} />}

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Master Command</div>
            <h1 className="text-3xl font-semibold gradient-text">Trading Overview</h1>
          </div>
          <div className="flex items-center gap-2">
            <Badge color="emerald">Phase 1–13</Badge>
            <Badge color="indigo">{data.metrics.activeAccounts} Active</Badge>
            <Badge color={data.metrics.openPositions > 0 ? "amber" : "slate"}>{data.metrics.openPositions} Open</Badge>
          </div>
        </div>

        {/* KPI cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard
            label="Total Balance"
            value={`$${data.metrics.totalBalance.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            change={`${data.metrics.activeAccounts} accounts`}
            trend="neutral"
            icon="$"
            color="indigo"
          />
          <StatCard
            label="Equity"
            value={`$${data.metrics.totalEquity.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            change={`Δ ${data.metrics.totalEquity - data.metrics.totalBalance >= 0 ? "+" : ""}${(data.metrics.totalEquity - data.metrics.totalBalance).toFixed(2)}`}
            trend={data.metrics.totalEquity >= data.metrics.totalBalance ? "up" : "down"}
            icon="◆"
            color="cyan"
          />
          <StatCard
            label="Realized PnL"
            value={`${data.metrics.totalPnL >= 0 ? "+" : ""}$${data.metrics.totalPnL.toFixed(2)}`}
            change={`${data.metrics.totalTrades} trades`}
            trend={data.metrics.totalPnL >= 0 ? "up" : "down"}
            icon="∑"
            color={data.metrics.totalPnL >= 0 ? "emerald" : "rose"}
          />
          <StatCard
            label="Win Rate"
            value={`${data.metrics.winRate.toFixed(1)}%`}
            change={`${winSymbolCount}W / ${lossSymbolCount}L`}
            trend={data.metrics.winRate >= 50 ? "up" : "down"}
            icon="%"
            color={data.metrics.winRate >= 50 ? "emerald" : "amber"}
          />
          <StatCard
            label="Profit Factor"
            value={data.metrics.profitFactor.toFixed(2)}
            change={data.metrics.profitFactor >= 1.5 ? "Excellent" : data.metrics.profitFactor >= 1 ? "OK" : "Poor"}
            trend={data.metrics.profitFactor >= 1.5 ? "up" : data.metrics.profitFactor >= 1 ? "neutral" : "down"}
            icon="×"
            color="violet"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Live Signal Analyzer */}
          <div className="lg:col-span-2 card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-widest">Live Signal Engine</div>
                <div className="text-sm font-medium text-slate-200">Multi-Indicator Confluence</div>
              </div>
              <div className="flex items-center gap-2">
                <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="bg-[#161c30] border border-[#2a3454] rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500">
                  {SYMBOLS.map((s) => (
                    <option key={s.ticker} value={s.ticker}>{s.ticker}</option>
                  ))}
                </select>
                <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className="bg-[#161c30] border border-[#2a3454] rounded-lg px-3 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500">
                  {TIMEFRAMES.map((tf) => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
                <button onClick={() => runAnalysis(true)} disabled={analyzing} className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/20 disabled:opacity-50">
                  {analyzing ? "Analyzing…" : "Re-analyze"}
                </button>
              </div>
            </div>

            {analysis ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                    <div className="text-[10px] text-slate-500 uppercase">Action</div>
                    <div className={`text-lg font-bold ${
                      analysis.action === "buy" ? "text-emerald-400" : analysis.action === "sell" ? "text-rose-400" : "text-slate-400"
                    }`}>
                      {analysis.action.toUpperCase()}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">{analysis.recommendation}</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                    <div className="text-[10px] text-slate-500 uppercase">Quality</div>
                    <div className="text-lg font-bold text-amber-400">{analysis.quality}</div>
                    <div className="text-xs text-slate-500 mt-0.5">Score {analysis.score}/100</div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                    <div className="text-[10px] text-slate-500 uppercase">Confidence</div>
                    <div className="text-lg font-bold text-indigo-400">{analysis.confidence.toFixed(1)}%</div>
                    <div className="w-full bg-[#2a3454] rounded-full h-1 mt-1">
                      <div className="h-1 rounded-full bg-indigo-500" style={{ width: `${analysis.confidence}%` }}></div>
                    </div>
                  </div>
                  <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                    <div className="text-[10px] text-slate-500 uppercase">Regime</div>
                    <div className="text-sm font-bold text-cyan-400 capitalize">{analysis.regime.replace("_", " ")}</div>
                    <div className="text-xs text-slate-500 mt-0.5 capitalize">Vol: {analysis.volatility}</div>
                  </div>
                </div>

                {analysis.entryPrice !== undefined && analysis.action !== "hold" && (
                  <div className="grid grid-cols-4 gap-3 text-xs">
                    <div className="rounded-lg bg-[#0a0e1a] p-2 border border-[#2a3454]">
                      <div className="text-slate-500">Entry</div>
                      <div className="text-slate-200 font-mono">{Number(analysis.indicators.price).toFixed(5)}</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] p-2 border border-[#2a3454]">
                      <div className="text-slate-500">Stop</div>
                      <div className="text-rose-400 font-mono">{analysis.stopLoss?.toFixed(5)}</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] p-2 border border-[#2a3454]">
                      <div className="text-slate-500">Target</div>
                      <div className="text-emerald-400 font-mono">{analysis.takeProfit?.toFixed(5)}</div>
                    </div>
                    <div className="rounded-lg bg-[#0a0e1a] p-2 border border-[#2a3454]">
                      <div className="text-slate-500">R:R</div>
                      <div className="text-amber-400 font-mono">1:{analysis.riskReward.toFixed(1)}</div>
                    </div>
                  </div>
                )}

                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                  <div className="text-[10px] text-slate-500 uppercase mb-2">Reasons</div>
                  <div className="space-y-1 text-xs max-h-32 overflow-y-auto">
                    {analysis.reasons.map((r, i) => (
                      <div key={i} className="text-slate-300 font-mono">{r}</div>
                    ))}
                  </div>
                </div>

                {analysis.action !== "hold" && analysis.quality !== "reject" && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => saveAndExecute("buy")}
                      disabled={analysis.action !== "buy"}
                      className="flex-1 py-2.5 rounded-lg bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/20 text-sm font-semibold disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      Execute BUY
                    </button>
                    <button
                      onClick={() => saveAndExecute("sell")}
                      disabled={analysis.action !== "sell"}
                      className="flex-1 py-2.5 rounded-lg bg-rose-500/10 text-rose-300 border border-rose-500/30 hover:bg-rose-500/20 text-sm font-semibold disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      Execute SELL
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="grid place-items-center h-48">
                <div className="text-slate-500 text-sm">Running analysis…</div>
              </div>
            )}
          </div>

          {/* Equity Curve */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-widest">Equity Curve</div>
                <div className="text-sm font-medium text-slate-200">Last 50 Trades</div>
              </div>
              <Badge color={data.metrics.totalPnL >= 0 ? "emerald" : "rose"}>
                {data.metrics.totalPnL >= 0 ? "Profitable" : "Drawdown"}
              </Badge>
            </div>
            <div className="space-y-3">
              <Sparkline
                data={data.equityCurve.map((p) => p.balance)}
                height={120}
                width={300}
                color="#6366f1"
              />
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                  <div className="text-slate-500 text-[10px]">Avg Win</div>
                  <div className="text-emerald-400 font-mono">
                    ${(data.closedTrades.filter((t) => Number(t.profit) > 0).reduce((s, t) => s + Number(t.profit), 0) / Math.max(1, winSymbolCount)).toFixed(2)}
                  </div>
                </div>
                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                  <div className="text-slate-500 text-[10px]">Avg Loss</div>
                  <div className="text-rose-400 font-mono">
                    ${(data.closedTrades.filter((t) => Number(t.profit) < 0).reduce((s, t) => s + Number(t.profit), 0) / Math.max(1, lossSymbolCount)).toFixed(2)}
                  </div>
                </div>
              </div>
            </div>
            <div className="mt-4">
              <div className="text-[10px] text-slate-500 uppercase mb-1">Recent Returns</div>
              <BarChart data={recentPnL.slice(0, 30).reverse()} height={60} width={300} />
            </div>
          </div>
        </div>

        {/* Open positions and accounts summary */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-widest">Open Positions</div>
                <div className="text-sm font-medium text-slate-200">Live Across {data.metrics.activeAccounts} Accounts</div>
              </div>
              <Badge color="amber">{data.openTrades.length} Active</Badge>
            </div>
            {data.openTrades.length === 0 ? (
              <div className="text-center text-slate-500 py-12 text-sm">No open positions. Run an analysis and execute a signal.</div>
            ) : (
              <div className="space-y-1.5 max-h-80 overflow-y-auto">
                {data.openTrades.map((t) => (
                  <div key={t.id} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                    <Badge color={t.direction === "buy" ? "emerald" : "rose"}>{t.direction.toUpperCase()}</Badge>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-slate-100">{t.symbol}</div>
                      <div className="text-[10px] text-slate-500">Account #{t.accountId} • {t.lots} lots</div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-slate-400">Entry</div>
                      <div className="text-sm font-mono text-slate-200">{Number(t.entryPrice).toFixed(5)}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] text-slate-500">SL / TP</div>
                      <div className="text-[10px] font-mono">
                        <span className="text-rose-400">{t.stopLoss ? Number(t.stopLoss).toFixed(5) : "—"}</span>
                        {" / "}
                        <span className="text-emerald-400">{t.takeProfit ? Number(t.takeProfit).toFixed(5) : "—"}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-widest">Account Roster</div>
                <div className="text-sm font-medium text-slate-200">Multi-Account Management</div>
              </div>
              <Badge color="indigo">{data.accounts.length} Total</Badge>
            </div>
            <div className="space-y-1.5 max-h-80 overflow-y-auto">
              {data.accounts.slice(0, 8).map((a) => (
                <div key={a.id} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2.5">
                  <div className={`size-2 rounded-full ${
                    a.status === "active" ? "bg-emerald-400 pulse-dot" : a.status === "paused" ? "bg-amber-400" : "bg-rose-400"
                  }`}></div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-slate-200 truncate">{a.name}</div>
                    <div className="text-[10px] text-slate-500 truncate">{a.broker} • {a.accountType}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-mono text-slate-200">${Number(a.balance).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                    <div className="text-[10px] text-slate-500">Risk {a.riskPercent}%</div>
                  </div>
                </div>
              ))}
              {data.accounts.length === 0 && (
                <div className="text-center text-slate-500 py-8 text-xs">
                  No accounts configured. <a href="/accounts" className="text-indigo-400 underline">Add an account</a>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Recent signals and regime */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-widest">Recent Signals</div>
                <div className="text-sm font-medium text-slate-200">Latest AI Decisions</div>
              </div>
              <a href="/signals" className="text-xs text-indigo-400 hover:underline">View all →</a>
            </div>
            <div className="space-y-1.5 max-h-80 overflow-y-auto">
              {data.signals.slice(0, 8).map((s) => (
                <div key={s.id} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2.5">
                  <Badge color={s.action === "buy" ? "emerald" : s.action === "sell" ? "rose" : "slate"}>
                    {s.action.toUpperCase()}
                  </Badge>
                  <div className="flex-1">
                    <div className="text-sm font-medium text-slate-200">{s.symbol} <span className="text-slate-500 text-xs">{s.timeframe}</span></div>
                    <div className="text-[10px] text-slate-500">Score {s.score} • {s.recommendation}</div>
                  </div>
                  <Badge color={s.quality === "A+" || s.quality === "A" ? "emerald" : s.quality === "B" ? "amber" : "slate"}>{s.quality}</Badge>
                  <div className="text-right">
                    <div className="text-xs font-mono text-slate-200">{Number(s.confidence).toFixed(0)}%</div>
                    <div className="text-[10px] text-slate-500">{s.executed ? "Executed" : "Pending"}</div>
                  </div>
                </div>
              ))}
              {data.signals.length === 0 && (
                <div className="text-center text-slate-500 py-8 text-xs">No signals yet. Run analysis above.</div>
              )}
            </div>
          </div>

          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-xs text-slate-500 uppercase tracking-widest">Market Regime Map</div>
                <div className="text-sm font-medium text-slate-200">Phase 4 Intelligence</div>
              </div>
              <Badge color="cyan">ADX + ATR</Badge>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-80 overflow-y-auto">
              {data.regimes.slice(0, 8).map((r, i) => (
                <div key={i} className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2.5">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-slate-200">{r.symbol}</span>
                    <Badge color={
                      r.regime === "trending" ? "emerald" :
                      r.regime === "ranging" ? "amber" :
                      r.regime === "volatile" ? "rose" : "slate"
                    }>
                      {r.regime}
                    </Badge>
                  </div>
                  <div className="text-[10px] text-slate-500 capitalize">Vol: {r.volatility} • {r.timeframe}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
