"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { useApp } from "@/components/Provider";

interface Account {
  id: number;
  name: string;
  accountNumber: string;
  server: string;
  broker: string;
  accountType: string;
  status: string;
  tradingEnabled: boolean;
  connectionStatus: "not_configured" | "disconnected" | "connected" | "auth_failed";
  lastConnectedAt: string | null;
  balance: string;
  equity: string;
  margin: string;
  freeMargin: string;
  riskPercent: string;
  maxDailyLoss: string;
  maxWeeklyLoss: string;
  maxConsecutiveLosses: number;
  createdAt: string;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    name: "",
    accountNumber: "",
    password: "",
    server: "Exness-MT5Real8",
    broker: "exness",
    accountType: "standard",
    balance: 10000,
    riskPercent: 1,
    maxDailyLoss: 3,
    maxWeeklyLoss: 8,
    maxConsecutiveLosses: 3,
  });
  const { showToast } = useApp();

  const load = useCallback(async () => {
    const r = await fetch("/api/accounts", { cache: "no-store" });
    const d = await r.json();
    setAccounts(d.accounts);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    if (!form.name || !form.accountNumber || !form.password) {
      showToast("Fill all required fields", "error");
      return;
    }
    const r = await fetch("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (r.ok) {
      showToast("Account created", "success");
      setShowAdd(false);
      setForm({ ...form, name: "", accountNumber: "", password: "" });
      load();
    } else {
      showToast("Failed to create", "error");
    }
  };

  const update = async (id: number, patch: Partial<Account>) => {
    const r = await fetch("/api/accounts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ...patch }),
    });
    if (r.ok) {
      showToast("Updated", "success");
      load();
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this account?")) return;
    await fetch(`/api/accounts?id=${id}`, { method: "DELETE" });
    showToast("Account removed", "info");
    load();
  };

  const mt5 = async (action: "connect" | "disconnect", id: number) => {
    const r = await fetch(`/api/mt5/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accountId: id }),
    });
    const d = await r.json();
    if (d.connected) {
      showToast(`Connected (${d.latencyMs}ms) — ${d.company || "MT5"}`, "success");
    } else if (d.ok) {
      showToast("Disconnected", "info");
    } else {
      showToast(d.message || "Connection failed", "error");
    }
    load();
  };

  const toggleTrading = async (a: Account) => {
    await fetch("/api/accounts", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: a.id, tradingEnabled: !a.tradingEnabled }),
    });
    showToast(`Trading ${a.tradingEnabled ? "disabled" : "enabled"} on ${a.name}`, "info");
    load();
  };

  const changePassword = async (a: Account) => {
    const newPassword = prompt(`New MT5 password for ${a.name} (stored AES-256-GCM encrypted, current session will be invalidated):`);
    if (!newPassword) return;
    const r = await fetch("/api/accounts/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accountId: a.id, newPassword }),
    });
    const d = await r.json();
    if (r.ok) showToast(d.message, "success");
    else showToast(d.error || "Failed", "error");
    load();
  };

  const connectionBadge = (s: Account["connectionStatus"]) => {
    switch (s) {
      case "connected": return <Badge color="emerald">Connected</Badge>;
      case "auth_failed": return <Badge color="rose">Auth failed</Badge>;
      case "disconnected": return <Badge color="slate">Disconnected</Badge>;
      default: return <Badge color="amber">Not configured</Badge>;
    }
  };

  return (
    <Shell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Multi-Account Manager</div>
            <h1 className="text-3xl font-semibold gradient-text">Trading Accounts</h1>
            <p className="text-sm text-slate-400 mt-1">Manage Exness, IC Markets, Pepperstone, and demo MT5 accounts</p>
          </div>
          <button onClick={() => setShowAdd(!showAdd)} className="px-4 py-2 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-500/20 text-sm font-semibold">
            {showAdd ? "Cancel" : "+ Add Account"}
          </button>
        </div>

        {showAdd && (
          <div className="card p-5">
            <div className="text-xs text-slate-500 uppercase tracking-widest mb-4">New Account</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Name</label>
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Exness Standard 01" className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Account #</label>
                <input value={form.accountNumber} onChange={(e) => setForm({ ...form, accountNumber: e.target.value })} placeholder="12345678" className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Password</label>
                <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="••••••••" className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Server</label>
                <select value={form.server} onChange={(e) => setForm({ ...form, server: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm">
                  <option>Exness-MT5Real8</option>
                  <option>Exness-MT5Real9</option>
                  <option>Exness-MT5Real10</option>
                  <option>Exness-MT5Trial6</option>
                  <option>ICMarkets-MT5-01</option>
                  <option>Pepperstone-MT5-Live01</option>
                  <option>MT5-Demo</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Broker</label>
                <select value={form.broker} onChange={(e) => setForm({ ...form, broker: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm">
                  <option value="exness">Exness</option>
                  <option value="ic_markets">IC Markets</option>
                  <option value="pepperstone">Pepperstone</option>
                  <option value="mt5_demo">MT5 Demo</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Account Type</label>
                <select value={form.accountType} onChange={(e) => setForm({ ...form, accountType: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm">
                  <option value="standard">Standard</option>
                  <option value="raw_spread">Raw Spread</option>
                  <option value="pro">Pro</option>
                  <option value="demo">Demo</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Balance ($)</label>
                <input type="number" value={form.balance} onChange={(e) => setForm({ ...form, balance: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Risk %</label>
                <input type="number" step="0.1" value={form.riskPercent} onChange={(e) => setForm({ ...form, riskPercent: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Max Daily Loss %</label>
                <input type="number" step="0.1" value={form.maxDailyLoss} onChange={(e) => setForm({ ...form, maxDailyLoss: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Max Weekly Loss %</label>
                <input type="number" step="0.1" value={form.maxWeeklyLoss} onChange={(e) => setForm({ ...form, maxWeeklyLoss: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase">Consecutive Loss Limit</label>
                <input type="number" value={form.maxConsecutiveLosses} onChange={(e) => setForm({ ...form, maxConsecutiveLosses: Number(e.target.value) })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm font-mono" />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setShowAdd(false)} className="px-4 py-2 rounded-lg bg-slate-500/10 text-slate-300 border border-slate-500/30 text-sm">Cancel</button>
              <button onClick={create} className="px-4 py-2 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 hover:bg-indigo-500/30 text-sm font-semibold">Create Account</button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {accounts.map((a) => (
            <div key={a.id} className="card p-5 relative">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <div className={`size-2 rounded-full ${a.status === "active" ? "bg-emerald-400 pulse-dot" : a.status === "paused" ? "bg-amber-400" : "bg-rose-400"}`}></div>
                    <div className="text-sm font-semibold text-slate-100">{a.name}</div>
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono mt-0.5">{a.accountNumber} • {a.server}</div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  {connectionBadge(a.connectionStatus)}
                  <div className="flex gap-1">
                    <Badge color={a.broker === "exness" ? "amber" : a.broker === "ic_markets" ? "indigo" : a.broker === "pepperstone" ? "rose" : a.broker === "mt5_demo" ? "cyan" : "slate"}>
                      {a.broker.replace("_", " ")}
                    </Badge>
                    <Badge color="slate">{a.accountType}</Badge>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 my-3">
                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                  <div className="text-[10px] text-slate-500">Balance</div>
                  <div className="text-sm font-mono text-slate-100">${Number(a.balance).toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
                </div>
                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                  <div className="text-[10px] text-slate-500">Equity</div>
                  <div className="text-sm font-mono text-slate-100">${Number(a.equity).toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
                </div>
                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                  <div className="text-[10px] text-slate-500">Risk %</div>
                  <div className="text-sm font-mono text-amber-400">{a.riskPercent}%</div>
                </div>
                <div className="rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-2">
                  <div className="text-[10px] text-slate-500">Trading</div>
                  <div className={`text-sm font-semibold ${a.tradingEnabled ? "text-emerald-400" : "text-rose-400"}`}>{a.tradingEnabled ? "ON" : "OFF"}</div>
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex gap-1.5">
                  {a.connectionStatus === "connected" ? (
                    <button onClick={() => mt5("disconnect", a.id)} className="flex-1 py-1.5 text-[10px] rounded bg-slate-500/10 text-slate-300 border border-slate-500/30 hover:bg-slate-500/20 font-semibold">DISCONNECT</button>
                  ) : (
                    <button onClick={() => mt5("connect", a.id)} className="flex-1 py-1.5 text-[10px] rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/40 hover:bg-indigo-500/25 font-semibold">
                      {a.connectionStatus === "auth_failed" ? "RETRY LOGIN" : "CONNECT MT5"}
                    </button>
                  )}
                  <button onClick={() => toggleTrading(a)} className={`flex-1 py-1.5 text-[10px] rounded font-semibold border ${
                    a.tradingEnabled
                      ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20"
                      : "bg-slate-500/10 text-slate-400 border-slate-500/30 hover:bg-slate-500/20"
                  }`}>
                    {a.tradingEnabled ? "TRADING ON" : "TRADING OFF"}
                  </button>
                </div>
                <div className="flex gap-1.5">
                  {a.status === "active" ? (
                    <button onClick={() => update(a.id, { status: "paused" })} className="flex-1 py-1.5 text-[10px] rounded bg-amber-500/10 text-amber-300 border border-amber-500/30 hover:bg-amber-500/20 font-semibold">PAUSE</button>
                  ) : (
                    <button onClick={() => update(a.id, { status: "active" })} className="flex-1 py-1.5 text-[10px] rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/20 font-semibold">ACTIVATE</button>
                  )}
                  <button onClick={() => changePassword(a)} className="flex-1 py-1.5 text-[10px] rounded bg-cyan-500/10 text-cyan-300 border border-cyan-500/30 hover:bg-cyan-500/20 font-semibold">PASSWORD</button>
                  <button onClick={() => remove(a.id)} className="px-2 py-1.5 text-[10px] rounded bg-rose-500/10 text-rose-300 border border-rose-500/30 hover:bg-rose-500/20 font-semibold">✕</button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {accounts.length === 0 && !showAdd && (
          <div className="card p-12 text-center">
            <div className="text-slate-500 mb-3">No accounts configured</div>
            <button onClick={() => setShowAdd(true)} className="text-indigo-400 hover:underline text-sm">Add your first Exness MT5 account →</button>
          </div>
        )}
      </div>
    </Shell>
  );
}
