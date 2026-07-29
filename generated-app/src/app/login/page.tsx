"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#0a0e1a]" />}>
      <LoginInner />
    </Suspense>
  );
}

function LoginInner() {
  const router = useRouter();
  const search = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [bootstrapped, setBootstrapped] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/api/auth/bootstrap").then((r) => r.json()).then((d) => setBootstrapped(d.bootstrapped)).catch(() => setBootstrapped(false));
  }, []);

  const login = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      // Ensure the one-time security bootstrap has run
      if (!bootstrapped) await fetch("/api/auth/bootstrap", { method: "POST" });
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const d = await r.json();
      if (!r.ok) {
        setError(d.error || "Login failed");
      } else {
        router.push(search.get("next") || "/");
      }
    } catch {
      setError("Connection error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid place-items-center bg-[#0a0e1a] px-6 relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,rgba(99,102,241,0.15),transparent_50%),radial-gradient(ellipse_at_bottom_right,rgba(236,72,153,0.1),transparent_50%)]"></div>
      <div className="relative w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex size-16 rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-pink-500 items-center justify-center text-3xl font-bold text-white shadow-2xl shadow-indigo-500/30 mb-4">
            A
          </div>
          <h1 className="text-2xl font-semibold text-slate-100">AI Adaptive Quant Trading System</h1>
          <p className="text-sm text-slate-500 mt-1">AI Trading Manager — secure operator access</p>
        </div>

        <form onSubmit={login} className="card p-8 space-y-4 glow">
          <div>
            <label className="text-[10px] text-slate-500 uppercase tracking-widest">Username</label>
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full mt-1.5 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
              placeholder="admin"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 uppercase tracking-widest">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full mt-1.5 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50"
              placeholder="••••••••••"
              autoComplete="current-password"
            />
          </div>
          {error && <div className="text-xs text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3 py-2">{error}</div>}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-500 text-white text-sm font-semibold hover:from-indigo-400 hover:to-violet-400 disabled:opacity-50 shadow-lg shadow-indigo-500/25"
          >
            {loading ? "Authenticating…" : "Login"}
          </button>
          {bootstrapped === false && (
            <div className="text-[10px] text-slate-500 bg-[#0a0e1a] border border-[#2a3454] rounded-lg px-3 py-2">
              First run detected — the security bootstrap will run automatically (default: <span className="font-mono text-slate-300">admin / admin123</span>, change it in Settings).
            </div>
          )}
        </form>

        <div className="mt-6 grid grid-cols-3 gap-2 text-center text-[10px] text-slate-600">
          <div className="rounded-lg border border-[#2a3454] bg-[#0f1424] p-2">AES-256-GCM<br/>credentials</div>
          <div className="rounded-lg border border-[#2a3454] bg-[#0f1424] p-2">scrypt<br/>passwords</div>
          <div className="rounded-lg border border-[#2a3454] bg-[#0f1424] p-2">HMAC session<br/>tokens</div>
        </div>
      </div>
    </div>
  );
}
