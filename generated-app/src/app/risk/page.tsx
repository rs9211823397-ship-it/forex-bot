"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { useApp } from "@/components/Provider";
import { StatCard } from "@/components/StatCard";

interface Account {
  id: number; name: string; status: string; balance: string; equity: string;
  riskPercent: string; maxDailyLoss: string; maxWeeklyLoss: string; maxConsecutiveLosses: number;
  broker: string; accountType: string;
}

interface Trade {
  id: number; accountId: number; profit: string; closedAt: string | null; openedAt: string; symbol: string;
}

export default function RiskPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [closedToday, setClosedToday] = useState<Trade[]>([]);
  const [closedWeek, setClosedWeek] = useState<Trade[]>([]);
  const { emergencyStop, bot } = useApp();

  const load = useCallback(async () => {
    const a = await fetch("/api/accounts").then((r) => r.json());
    setAccounts(a.accounts);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const week = new Date(today);
    week.setDate(week.getDate() - 7);
    const t = await fetch("/api/trades?status=closed").then((r) => r.json());
    const closed = t.trades as Trade[];
    setClosedToday(closed.filter((x) => x.closedAt && new Date(x.closedAt) >= today));
    setClosedWeek(closed.filter((x) => x.closedAt && new Date(x.closedAt) >= week));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [load]);

  const aggregatePnL = (trades: Trade[]) => trades.reduce((s, t) => s + Number(t.profit), 0);
  const totalBalance = accounts.reduce((s, a) => s + Number(a.balance), 0);
  const totalEquity = accounts.reduce((s, a) => s + Number(a.equity), 0);
  const dailyPnL = aggregatePnL(closedToday);
  const weeklyPnL = aggregatePnL(closedWeek);

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Phase 8</div>
            <h1 className="text-3xl font-semibold gradient-text">Risk Control Center</h1>
            <p className="text-sm text-slate-400 mt-1">Multi-layer capital protection across all accounts</p>
          </div>
          <div className="flex gap-2">
            <Badge color={bot.status === "RUNNING" ? "emerald" : bot.status === "PAUSED" ? "amber" : "slate"}>Bot: {bot.status}</Badge>
            <button onClick={() => emergencyStop(true)} className="px-3 py-1.5 text-xs font-bold rounded bg-rose-500/20 text-rose-300 border border-rose-500/40 hover:bg-rose-500/30">
              ⚠ EMERGENCY CLOSE ALL
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <StatCard label="Total Balance" value={`$${totalBalance.toFixed(0)}`} color="indigo" icon="$" />
          <StatCard label="Total Equity" value={`$${totalEquity.toFixed(0)}`} color="cyan" icon="◆" />
          <StatCard
            label="Daily PnL"
            value={`${dailyPnL >= 0 ? "+" : ""}$${dailyPnL.toFixed(2)}`}
            color={dailyPnL >= 0 ? "emerald" : "rose"}
            trend={dailyPnL >= 0 ? "up" : "down"}
            icon="◐"
          />
          <StatCard
            label="Weekly PnL"
            value={`${weeklyPnL >= 0 ? "+" : ""}$${weeklyPnL.toFixed(2)}`}
            color={weeklyPnL >= 0 ? "emerald" : "rose"}
            trend={weeklyPnL >= 0 ? "up" : "down"}
            icon="◑"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Per-Account Risk Limits</div>
            <div className="space-y-2">
              {accounts.map((a) => {
                const accountPnL = closedToday.filter((t) => t.accountId === a.id).reduce((s, t) => s + Number(t.profit), 0);
                const dailyPct = (accountPnL / Number(a.balance)) * 100;
                const dailyLimit = Number(a.maxDailyLoss);
                const dailyUtil = Math.abs(dailyPct) / dailyLimit * 100;
                return (
                  <div key={a.id} className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <div className={`size-2 rounded-full ${a.status === "active" ? "bg-emerald-400" : "bg-slate-500"}`}></div>
                        <div className="text-sm font-medium text-slate-200">{a.name}</div>
                        <Badge color="slate">{a.broker}</Badge>
                      </div>
                      <div className="text-xs text-slate-400">Risk {a.riskPercent}%</div>
                    </div>
                    <div className="space-y-1.5">
                      <div>
                        <div className="flex items-center justify-between text-[10px] text-slate-500 mb-0.5">
                          <span>Daily loss limit ({a.maxDailyLoss}%)</span>
                          <span className={Math.abs(dailyPct) >= dailyLimit ? "text-rose-400 font-semibold" : "text-slate-400"}>
                            {dailyPct.toFixed(2)}% / {dailyLimit}%
                          </span>
                        </div>
                        <div className="h-1.5 bg-[#2a3454] rounded-full overflow-hidden">
                          <div
                            className={`h-1.5 rounded-full transition-all ${
                              dailyUtil >= 100 ? "bg-rose-500" : dailyUtil >= 70 ? "bg-amber-500" : "bg-emerald-500"
                            }`}
                            style={{ width: `${Math.min(100, dailyUtil)}%` }}
                          />
                        </div>
                      </div>
                      <div className="text-[10px] text-slate-500">
                        Weekly limit: {a.maxWeeklyLoss}% • Max consecutive losses: {a.maxConsecutiveLosses}
                      </div>
                    </div>
                  </div>
                );
              })}
              {accounts.length === 0 && (
                <div className="text-slate-500 text-xs py-8 text-center">No accounts configured</div>
              )}
            </div>
          </div>

          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Risk Rules Active</div>
            <div className="space-y-2 text-sm">
              <RuleRow active label="Daily Loss Limit" desc="Stop trading after -3% per day per account" />
              <RuleRow active label="Weekly Drawdown Cap" desc="Maximum -8% per week" />
              <RuleRow active label="Consecutive Loss Pause" desc="Pause after 3 consecutive losses" />
              <RuleRow active label="Correlation Filter" desc="Block same-direction USD and metal pairs" />
              <RuleRow active label="Position Sizing" desc="Risk % × Balance ÷ SL distance" />
              <RuleRow active label="ATR-Based Stop Loss" desc="1.5× ATR with 1:2 R:R target" />
              <RuleRow active label="AI Quality Gate" desc="Reject signals below B grade" />
              <RuleRow label="News Blackout" desc="Avoid CPI / NFP / FOMC (manual toggle)" />
            </div>
          </div>
        </div>

        <div className="card p-5">
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Recent Loss Events</div>
          <div className="space-y-1.5 max-h-72 overflow-y-auto">
            {closedToday.filter((t) => Number(t.profit) < 0).slice(0, 10).map((t) => (
              <div key={t.id} className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-rose-500/20 p-2.5">
                <Badge color="rose">LOSS</Badge>
                <div className="flex-1">
                  <div className="text-sm text-slate-200">{t.symbol}</div>
                  <div className="text-[10px] text-slate-500">{t.closedAt && new Date(t.closedAt).toLocaleString()}</div>
                </div>
                <div className="text-sm font-mono text-rose-400">${Number(t.profit).toFixed(2)}</div>
              </div>
            ))}
            {closedToday.filter((t) => Number(t.profit) < 0).length === 0 && (
              <div className="text-slate-500 text-xs py-8 text-center">No losing trades today ✓</div>
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}

function RuleRow({ label, desc, active = false }: { label: string; desc: string; active?: boolean }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3">
      <div className={`size-2 rounded-full ${active ? "bg-emerald-400" : "bg-slate-600"}`}></div>
      <div className="flex-1">
        <div className="text-sm font-medium text-slate-200">{label}</div>
        <div className="text-xs text-slate-500">{desc}</div>
      </div>
      <Badge color={active ? "emerald" : "slate"}>{active ? "ACTIVE" : "INACTIVE"}</Badge>
    </div>
  );
}
