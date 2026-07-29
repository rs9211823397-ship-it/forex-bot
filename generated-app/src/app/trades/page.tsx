"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { useApp } from "@/components/Provider";

interface Trade {
  id: number;
  accountId: number;
  signalId: number | null;
  symbol: string;
  direction: string;
  mode: string;
  status: string;
  lots: string;
  entryPrice: string;
  stopLoss: string | null;
  takeProfit: string | null;
  exitPrice: string | null;
  profit: string;
  pips: string;
  quality: string | null;
  reason: string | null;
  openedAt: string;
  closedAt: string | null;
}

export default function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tab, setTab] = useState<"open" | "closed">("open");
  const { showToast } = useApp();

  const load = useCallback(async () => {
    const r = await fetch(`/api/trades?status=${tab}`, { cache: "no-store" });
    const d = await r.json();
    setTrades(d.trades);
  }, [tab]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const close = async (id: number) => {
    const exitPriceStr = prompt("Exit price (leave empty to close at entry):", "");
    const exitPrice = exitPriceStr ? Number(exitPriceStr) : undefined;
    const r = await fetch("/api/trades", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, action: "close", exitPrice }),
    });
    if (r.ok) {
      showToast("Trade closed", "success");
      load();
    }
  };

  const totalPnL = trades.reduce((s, t) => s + Number(t.profit), 0);
  const wins = trades.filter((t) => Number(t.profit) > 0).length;

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Phase 2 / 10</div>
            <h1 className="text-3xl font-semibold gradient-text">Trade Manager</h1>
            <p className="text-sm text-slate-400 mt-1">Open and closed positions across all accounts</p>
          </div>
          <div className="flex gap-2">
            <Badge color="emerald">{wins} wins</Badge>
            <Badge color={totalPnL >= 0 ? "emerald" : "rose"}>${totalPnL.toFixed(2)}</Badge>
          </div>
        </div>

        <div className="card p-4 flex items-center gap-2">
          {(["open", "closed"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`px-4 py-1.5 text-sm rounded-lg font-semibold uppercase ${
              tab === t ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/40" : "bg-[#0a0e1a] text-slate-400 border border-[#2a3454]"
            }`}>
              {t}
            </button>
          ))}
        </div>

        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#0a0e1a] text-[10px] uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Symbol</th>
                <th className="px-4 py-3 text-left">Dir</th>
                <th className="px-4 py-3 text-right">Lots</th>
                <th className="px-4 py-3 text-right">Entry</th>
                <th className="px-4 py-3 text-right">Exit</th>
                <th className="px-4 py-3 text-right">SL / TP</th>
                <th className="px-4 py-3 text-right">Pips</th>
                <th className="px-4 py-3 text-right">Profit</th>
                <th className="px-4 py-3 text-left">Account</th>
                <th className="px-4 py-3 text-left">Time</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-t border-[#2a3454] hover:bg-[#1e2540]/30">
                  <td className="px-4 py-2.5 font-medium text-slate-100">{t.symbol}</td>
                  <td className="px-4 py-2.5">
                    <Badge color={t.direction === "buy" ? "emerald" : "rose"}>{t.direction.toUpperCase()}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-slate-300">{Number(t.lots).toFixed(2)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-slate-200">{Number(t.entryPrice).toFixed(5)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-slate-200">{t.exitPrice ? Number(t.exitPrice).toFixed(5) : "—"}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-[10px]">
                    <span className="text-rose-400">{t.stopLoss ? Number(t.stopLoss).toFixed(5) : "—"}</span>
                    {" / "}
                    <span className="text-emerald-400">{t.takeProfit ? Number(t.takeProfit).toFixed(5) : "—"}</span>
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono ${Number(t.pips) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                    {Number(t.pips).toFixed(1)}
                  </td>
                  <td className={`px-4 py-2.5 text-right font-mono font-semibold ${Number(t.profit) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                    {Number(t.profit) >= 0 ? "+" : ""}${Number(t.profit).toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-slate-400 text-xs">#{t.accountId}</td>
                  <td className="px-4 py-2.5 text-slate-500 text-[10px]">{new Date(t.openedAt).toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right">
                    {t.status === "open" && (
                      <button onClick={() => close(t.id)} className="px-2 py-1 text-[10px] rounded bg-rose-500/10 text-rose-300 border border-rose-500/30 hover:bg-rose-500/20 font-semibold">
                        CLOSE
                      </button>
                    )}
                    {t.status === "closed" && <Badge color="slate">CLOSED</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length === 0 && (
            <div className="p-12 text-center text-slate-500 text-sm">
              No {tab} trades
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}
