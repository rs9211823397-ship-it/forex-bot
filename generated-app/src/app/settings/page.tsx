"use client";

import { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { Badge } from "@/components/Badge";
import { useApp } from "@/components/Provider";

interface BotSettings {
  id: number;
  defaultRiskPercent: string;
  maxDailyLossPercent: string;
  maxWeeklyLossPercent: string;
  maxConsecutiveLosses: number;
  correlationFilter: boolean;
  newsBlackout: boolean;
  emaFast: number;
  emaMid: number;
  emaSlow: number;
  rsiPeriod: number;
  atrMultiplier: string;
  rrTarget: string;
  updatedAt: string;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<BotSettings | null>(null);
  const [pw, setPw] = useState({ currentPassword: "", newPassword: "", confirm: "" });
  const { showToast, user } = useApp();

  const load = useCallback(async () => {
    const r = await fetch("/api/bot/settings");
    const d = await r.json();
    setSettings(d.settings);
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (patch: Record<string, number | boolean>) => {
    const r = await fetch("/api/bot/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (r.ok) {
      showToast("Settings saved", "success");
      load();
    } else {
      showToast("Save failed", "error");
    }
  };

  const changePassword = async () => {
    if (pw.newPassword !== pw.confirm) {
      showToast("Passwords do not match", "error");
      return;
    }
    const r = await fetch("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ currentPassword: pw.currentPassword, newPassword: pw.newPassword }),
    });
    const d = await r.json();
    if (r.ok) {
      showToast("Login password updated", "success");
      setPw({ currentPassword: "", newPassword: "", confirm: "" });
    } else {
      showToast(d.error || "Failed", "error");
    }
  };

  if (!settings) return <Shell><div className="grid place-items-center h-96 text-slate-500">Loading…</div></Shell>;

  return (
    <Shell>
      <div className="space-y-6">
        <div>
          <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Administration</div>
          <h1 className="text-3xl font-semibold gradient-text">Bot & Security Settings</h1>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Bot settings */}
          <div className="card p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="text-xs text-slate-500 uppercase tracking-widest">Master Bot Settings</div>
              <Badge color="indigo">persisted</Badge>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Default Risk %" value={settings.defaultRiskPercent} onSave={(v) => save({ defaultRiskPercent: Number(v) })} />
              <Field label="Max Daily Loss %" value={settings.maxDailyLossPercent} onSave={(v) => save({ maxDailyLossPercent: Number(v) })} />
              <Field label="Max Weekly Loss %" value={settings.maxWeeklyLossPercent} onSave={(v) => save({ maxWeeklyLossPercent: Number(v) })} />
              <Field label="Consec. Loss Limit" value={String(settings.maxConsecutiveLosses)} onSave={(v) => save({ maxConsecutiveLosses: Number(v) })} />
              <Field label="EMA Fast" value={String(settings.emaFast)} onSave={(v) => save({ emaFast: Number(v) })} />
              <Field label="EMA Mid" value={String(settings.emaMid)} onSave={(v) => save({ emaMid: Number(v) })} />
              <Field label="EMA Slow" value={String(settings.emaSlow)} onSave={(v) => save({ emaSlow: Number(v) })} />
              <Field label="RSI Period" value={String(settings.rsiPeriod)} onSave={(v) => save({ rsiPeriod: Number(v) })} />
              <Field label="ATR Multiplier" value={settings.atrMultiplier} onSave={(v) => save({ atrMultiplier: Number(v) })} />
              <Field label="R:R Target" value={settings.rrTarget} onSave={(v) => save({ rrTarget: Number(v) })} />
            </div>
            <div className="mt-4 space-y-2">
              <Toggle label="Correlation filter" desc="Block same-direction correlated pairs" value={settings.correlationFilter} onToggle={() => save({ correlationFilter: !settings.correlationFilter })} />
              <Toggle label="News blackout" desc="Avoid high-impact events" value={settings.newsBlackout} onToggle={() => save({ newsBlackout: !settings.newsBlackout })} />
            </div>
          </div>

          {/* Security */}
          <div className="space-y-4">
            <div className="card p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="text-xs text-slate-500 uppercase tracking-widest">Operator Account</div>
                <Badge color="emerald">{user?.role || "admin"}</Badge>
              </div>
              <div className="text-sm text-slate-300 mb-4">Signed in as <span className="font-mono text-indigo-300">{user?.username}</span></div>
              <div className="space-y-3">
                <div>
                  <label className="text-[10px] text-slate-500 uppercase">Current password</label>
                  <input type="password" value={pw.currentPassword} onChange={(e) => setPw({ ...pw, currentPassword: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase">New password (min 8 chars)</label>
                  <input type="password" value={pw.newPassword} onChange={(e) => setPw({ ...pw, newPassword: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="text-[10px] text-slate-500 uppercase">Confirm new password</label>
                  <input type="password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} className="w-full mt-1 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2 text-sm" />
                </div>
                <button onClick={changePassword} disabled={!pw.currentPassword || pw.newPassword.length < 8} className="w-full py-2 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 hover:bg-indigo-500/30 text-sm font-semibold disabled:opacity-40">
                  Update Login Password
                </button>
              </div>
            </div>

            <div className="card p-5">
              <div className="text-xs text-slate-500 uppercase tracking-widest mb-3">Security posture</div>
              <div className="space-y-2 text-xs text-slate-400">
                <div className="flex justify-between"><span>MT5 credentials at rest</span><span className="text-emerald-400">AES-256-GCM</span></div>
                <div className="flex justify-between"><span>Operator passwords</span><span className="text-emerald-400">scrypt + salt</span></div>
                <div className="flex justify-between"><span>Session tokens</span><span className="text-emerald-400">HMAC-SHA256, revocable</span></div>
                <div className="flex justify-between"><span>API protection</span><span className="text-emerald-400">Edge middleware + DB checks</span></div>
                <div className="flex justify-between"><span>Passwords in API responses</span><span className="text-emerald-400">Never</span></div>
                <div className="flex justify-between"><span>Passwords in logs</span><span className="text-emerald-400">Never</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}

function Field({ label, value, onSave }: { label: string; value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  const dirty = v !== value;
  return (
    <div>
      <label className="text-[10px] text-slate-500 uppercase">{label}</label>
      <div className="flex gap-1 mt-1">
        <input value={v} onChange={(e) => setV(e.target.value)} className="flex-1 min-w-0 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-2 py-1.5 text-sm font-mono" />
        <button onClick={() => onSave(v)} disabled={!dirty} className="px-2 py-1 text-[10px] rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 disabled:opacity-30">✓</button>
      </div>
    </div>
  );
}

function Toggle({ label, desc, value, onToggle }: { label: string; desc: string; value: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} className="w-full flex items-center gap-3 rounded-lg bg-[#0a0e1a] border border-[#2a3454] p-3 text-left hover:border-indigo-500/40">
      <div className={`w-9 h-5 rounded-full relative transition-colors ${value ? "bg-emerald-500/60" : "bg-slate-600"}`}>
        <div className={`absolute top-0.5 size-4 rounded-full bg-white transition-all ${value ? "left-4.5" : "left-0.5"}`} style={{ left: value ? "1.25rem" : "0.125rem" }}></div>
      </div>
      <div className="flex-1">
        <div className="text-sm text-slate-200">{label}</div>
        <div className="text-[10px] text-slate-500">{desc}</div>
      </div>
      <Badge color={value ? "emerald" : "slate"}>{value ? "ON" : "OFF"}</Badge>
    </button>
  );
}
