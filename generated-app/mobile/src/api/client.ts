// Shared API client — identical on iOS & Android; targets the SAME backend
// API and user authentication as the web dashboard (Feature 5/6).

import Constants from "expo-constants";

// For production set this in app.json → expo.extra.apiBaseUrl, or override at runtime.
const DEFAULT_BASE: string =
  (Constants.expoConfig?.extra as { apiBaseUrl?: string } | undefined)?.apiBaseUrl ??
  "http://127.0.0.1:3000";

let authToken: string | null = null;
let baseUrl = DEFAULT_BASE;

export function setAuthToken(token: string | null) {
  authToken = token;
}
export function setBaseUrl(url: string) {
  baseUrl = url;
}
export function getBaseUrl() {
  return baseUrl;
}

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${baseUrl}${path}`, {
    ...opts,
    headers: {
      "content-type": "application/json",
      ...(authToken ? { authorization: `Bearer ${authToken}` } : {}),
      ...(opts.headers || {}),
    },
  });
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!res.ok) {
    const d = data as { error?: string; message?: string } | null;
    throw new Error(d?.error ?? d?.message ?? `HTTP ${res.status}`);
  }
  return data as T;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; user: { id: number; username: string; role: string } }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),
  logout: () => request("/api/auth/logout", { method: "POST" }),
  me: () => request<{ authenticated: boolean; user: { id: number; username: string; role: string } }>("/api/auth/me"),
  dashboard: () =>
    request<{
      metrics: {
        totalAccounts: number; activeAccounts: number; openPositions: number;
        totalBalance: number; totalEquity: number; totalPnL: number;
        winRate: number; profitFactor: number; totalTrades: number;
      };
      openTrades: Array<{
        id: number; accountId: number; symbol: string; direction: string; lots: string;
        entryPrice: string; stopLoss: string | null; takeProfit: string | null; openedAt: string;
      }>;
      signals: Array<{ id: number; symbol: string; action: string; quality: string; confidence: string; reasons?: string[] }>;
    }>("/api/dashboard"),
  botStatus: () =>
    request<{ bot: { status: "STOPPED" | "RUNNING" | "PAUSED" | "EMERGENCY_STOP"; mode: string; openPositions: number } }>("/api/bot/status"),
  botControl: (command: "start" | "pause" | "resume" | "stop" | "reset", mode?: "paper" | "live") =>
    request<{ ok: boolean; state?: unknown; error?: string }>("/api/bot/control", { method: "POST", body: JSON.stringify({ command, mode }) }),
  botEmergency: (closePositions: boolean) =>
    request<{ ok: boolean; closedPositions: number }>("/api/bot/emergency", { method: "POST", body: JSON.stringify({ confirm: true, closePositions }) }),
  accounts: () =>
    request<{
      accounts: Array<{
        id: number; name: string; accountNumber: string; server: string; broker: string;
        accountType: string; status: string; tradingEnabled: boolean;
        connectionStatus: "not_configured" | "disconnected" | "connected" | "auth_failed";
        balance: string; equity: string; riskPercent: string;
      }>;
    }>("/api/accounts"),
  enableAccount: (id: number, enabled: boolean) =>
    request("/api/accounts", { method: "PATCH", body: JSON.stringify({ id, tradingEnabled: enabled }) }),
  connectAccount: (id: number) =>
    request<{ connected: boolean; message?: string; latencyMs?: number; company?: string }>(
      "/api/mt5/connect", { method: "POST", body: JSON.stringify({ accountId: id }) },
    ),
  disconnectAccount: (id: number) =>
    request("/api/mt5/disconnect", { method: "POST", body: JSON.stringify({ accountId: id }) }),
  changePassword: (accountId: number, newPassword: string) =>
    request("/api/accounts/credentials", { method: "POST", body: JSON.stringify({ accountId, newPassword }) }),
  positions: () =>
    request<{
      positions: Array<{
        tradeId: number; accountId: number; accountName?: string; symbol: string; direction: string;
        lots: number; entryPrice: number; currentPrice: number; stopLoss: number | null;
        takeProfit: number | null; unrealizedPnL: number; openedAt: string;
      }>;
    }>("/api/mt5/positions"),
  closeTrade: (accountId: number, tradeId: number, percent = 100) =>
    request("/api/mt5/close", { method: "POST", body: JSON.stringify({ accountId, tradeId, percent }) }),
  signals: () =>
    request<{
      signals: Array<{
        id: number; symbol: string; timeframe: string; action: string; quality: string;
        confidence: string; score: number; reasons: string[]; regime: string | null; createdAt: string;
      }>;
    }>("/api/signals/all"),
};
