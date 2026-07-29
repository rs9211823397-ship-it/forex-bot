// MT5 Bridge (Feature 3) — Exness/MT5-compatible execution adapter.
//
// Two modes (process.env.MT5_BRIDGE_MODE):
//   "simulated" (default): full in-process simulation — connections, latency, fills,
//                          auth failures (passwords < 6 chars), market-price closes.
//   "http":                proxies to a Windows-hosted bridge service running the
//                          official `MetaTrader5` Python package (see bridge/mt5_service.py).
//                          Set MT5_BRIDGE_URL=http://your-vps:8080
//
// The public interface (IMt5Bridge) is identical in both modes, so swapping
// simulation for the real MT5 terminal is a one-line environment change.

import { getProfile, generateTick } from "@/lib/engine/marketData";

export interface Mt5Credentials {
  login: string;   // MT5 account number
  password: string;
  server: string;  // e.g. Exness-MT5Real8
}

export interface Mt5ConnectionResult {
  connected: boolean;
  sessionToken?: string;
  error?: "AUTH_FAILED" | "TIMEOUT" | "BRIDGE_UNREACHABLE";
  message?: string;
  latencyMs: number;
  company?: string;
  tradeAllowed?: boolean;
  balance?: number;
  equity?: number;
}

export interface Mt5OrderRequest {
  symbol: string;
  direction: "buy" | "sell";
  lots: number;
  entryPrice?: number; // undefined = market
  stopLoss?: number;
  takeProfit?: number;
  comment?: string;
}

export interface Mt5OrderResult {
  success: boolean;
  ticket?: string;
  fillPrice?: number;
  error?: string;
  latencyMs: number;
}

export interface Mt5Position {
  ticket: string;
  symbol: string;
  direction: "buy" | "sell";
  lots: number;
  entryPrice: number;
  stopLoss?: number;
  takeProfit?: number;
  currentPrice: number;
  unrealizedPnl: number;
  openedAt: string;
}

export interface IMt5Bridge {
  connect(creds: Mt5Credentials): Promise<Mt5ConnectionResult>;
  disconnect(sessionToken: string): Promise<void>;
  placeOrder(req: Mt5OrderRequest): Promise<Mt5OrderResult>;
  modifyOrder(ticket: string, sl?: number, tp?: number): Promise<Mt5OrderResult>;
  closeOrder(ticket: string, percent?: number): Promise<Mt5OrderResult & { closedLots?: number; profit?: number }>;
  getPositions(): Promise<Mt5Position[]>;
  getHistory(limit?: number): Promise<Mt5Position[]>;
}

const BASE_URL = process.env.MT5_BRIDGE_URL || "http://127.0.0.1:8080";
const MODE = process.env.MT5_BRIDGE_MODE || "simulated";

function jitterLatency(min = 120, max = 700): number {
  return Math.round(min + Math.random() * (max - min));
}

async function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

// ---------------------------------------------------------------------------
// Simulated bridge (default): deterministic-ish, realistic latency & pricing
// ---------------------------------------------------------------------------
class SimulatedMt5Bridge implements IMt5Bridge {
  private sessions = new Map<string, { creds: Mt5Credentials; connectedAt: number }>();
  private positions: Mt5Position[] = [];
  private history: Mt5Position[] = [];

  async connect(creds: Mt5Credentials): Promise<Mt5ConnectionResult> {
    const latency = jitterLatency();
    await sleep(Math.min(150, latency / 3));
    const isExness = /exness/i.test(creds.server) || true; // simulation accepts any
    if (!creds.password || creds.password.length < 6) {
      return { connected: false, error: "AUTH_FAILED", message: "MT5 authentication failed for login " + creds.login, latencyMs: latency };
    }
    if (!/^\d{5,}$/.test(creds.login)) {
      return { connected: false, error: "AUTH_FAILED", message: "Invalid MT5 login id format", latencyMs: latency };
    }
    const sessionToken = `mt5sim_${creds.login}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
    this.sessions.set(sessionToken, { creds, connectedAt: Date.now() });
    return {
      connected: true,
      sessionToken,
      latencyMs: latency,
      company: isExness ? "Exness Technologies Ltd" : "Unknown Broker",
      tradeAllowed: true,
    };
  }

  async disconnect(sessionToken: string): Promise<void> {
    this.sessions.delete(sessionToken);
  }

  async placeOrder(req: Mt5OrderRequest): Promise<Mt5OrderResult> {
    const latency = jitterLatency(80, 400);
    await sleep(Math.min(120, latency / 3));
    if (req.lots <= 0) return { success: false, error: "Invalid lot size", latencyMs: latency };
    if (req.lots > 100) return { success: false, error: "Lot size exceeds maximum", latencyMs: latency };
    const profile = getProfile(req.symbol);
    let fill = req.entryPrice ?? generateTick(req.symbol);
    // slippage ~30% of a pip ±
    const slippage = profile.pip * 0.3 * (Math.random() - 0.5) * 2;
    fill += slippage;
    const ticket = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e5)}`;
    const pos: Mt5Position = {
      ticket,
      symbol: req.symbol,
      direction: req.direction,
      lots: req.lots,
      entryPrice: fill,
      stopLoss: req.stopLoss,
      takeProfit: req.takeProfit,
      currentPrice: fill,
      unrealizedPnl: 0,
      openedAt: new Date().toISOString(),
    };
    this.positions.push(pos);
    return { success: true, ticket, fillPrice: fill, latencyMs: latency };
  }

  async modifyOrder(ticket: string, sl?: number, tp?: number): Promise<Mt5OrderResult> {
    const latency = jitterLatency(80, 350);
    const pos = this.positions.find((p) => p.ticket === ticket);
    if (!pos) return { success: false, error: "Position not found", latencyMs: latency };
    if (sl !== undefined) pos.stopLoss = sl;
    if (tp !== undefined) pos.takeProfit = tp;
    return { success: true, ticket, latencyMs: latency };
  }

  async closeOrder(ticket: string, percent = 100): Promise<Mt5OrderResult & { closedLots?: number; profit?: number }> {
    const latency = jitterLatency(90, 450);
    const idx = this.positions.findIndex((p) => p.ticket === ticket);
    if (idx < 0) return { success: false, error: "Position not found", latencyMs: latency };
    const pos = this.positions[idx];
    const profile = getProfile(pos.symbol);
    const exit = generateTick(pos.symbol, pos.currentPrice);
    const closedLots = Math.max(0.01, +((pos.lots * percent) / 100).toFixed(2));
    const priceDiff = pos.direction === "buy" ? exit - pos.entryPrice : pos.entryPrice - exit;
    const profit = priceDiff * profile.contractSize * closedLots;
    if (percent >= 100 || closedLots >= pos.lots - 1e-9) {
      this.positions.splice(idx, 1);
      this.history.push({ ...pos, currentPrice: exit, unrealizedPnl: profit });
    } else {
      pos.lots = +(pos.lots - closedLots).toFixed(2);
      this.history.push({ ...pos, lots: closedLots, currentPrice: exit, unrealizedPnl: profit });
    }
    return { success: true, ticket, fillPrice: exit, closedLots, profit, latencyMs: latency };
  }

  async getPositions(): Promise<Mt5Position[]> {
    const profileTick = (p: Mt5Position) => {
      const cur = generateTick(p.symbol, p.currentPrice);
      const profile = getProfile(p.symbol);
      const priceDiff = p.direction === "buy" ? cur - p.entryPrice : p.entryPrice - cur;
      return { ...p, currentPrice: cur, unrealizedPnl: priceDiff * profile.contractSize * p.lots };
    };
    return this.positions.map(profileTick);
  }

  async getHistory(limit = 50): Promise<Mt5Position[]> {
    return this.history.slice(-limit);
  }
}

// ---------------------------------------------------------------------------
// HTTP bridge → real MT5 terminal (bridge/mt5_service.py on a Windows VPS)
// ---------------------------------------------------------------------------
class HttpMt5Bridge implements IMt5Bridge {
  private sessionToken: string | null = null;

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(this.sessionToken ? { "x-mt5-session": this.sessionToken } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) throw new Error(`MT5 bridge HTTP ${res.status}`);
    return (await res.json()) as T;
  }

  async connect(creds: Mt5Credentials): Promise<Mt5ConnectionResult> {
    const t0 = Date.now();
    try {
      const r = await this.post<{ connected: boolean; session?: string; message?: string; company?: string }>("/login", creds);
      if (!r.connected) return { connected: false, error: "AUTH_FAILED", message: r.message, latencyMs: Date.now() - t0 };
      this.sessionToken = r.session ?? null;
      return { connected: true, sessionToken: r.session, latencyMs: Date.now() - t0, company: r.company, tradeAllowed: true };
    } catch (e) {
      return { connected: false, error: "BRIDGE_UNREACHABLE", message: String(e), latencyMs: Date.now() - t0 };
    }
  }
  async disconnect(sessionToken: string) {
    try { await this.post("/logout", { session: sessionToken }); } catch { /* noop */ }
  }
  async placeOrder(req: Mt5OrderRequest): Promise<Mt5OrderResult> {
    const t0 = Date.now();
    try {
      const r = await this.post<Partial<Mt5OrderResult>>("/order", req);
      return { success: true, ticket: r.ticket, fillPrice: r.fillPrice, latencyMs: Date.now() - t0 };
    } catch (e) { return { success: false, error: String(e), latencyMs: Date.now() - t0 }; }
  }
  async modifyOrder(ticket: string, sl?: number, tp?: number): Promise<Mt5OrderResult> {
    const t0 = Date.now();
    try {
      await this.post("/modify", { ticket, stopLoss: sl, takeProfit: tp });
      return { success: true, ticket, latencyMs: Date.now() - t0 };
    } catch (e) { return { success: false, error: String(e), latencyMs: Date.now() - t0 }; }
  }
  async closeOrder(ticket: string, percent = 100) {
    const t0 = Date.now();
    try {
      const r = await this.post<{ fillPrice?: number; closedLots?: number; profit?: number }>("/close", { ticket, percent });
      return { success: true, ticket, latencyMs: Date.now() - t0, ...r };
    } catch (e) { return { success: false, error: String(e), latencyMs: Date.now() - t0 }; }
  }
  async getPositions(): Promise<Mt5Position[]> { return this.post<Mt5Position[]>("/positions", {}); }
  async getHistory(limit = 50): Promise<Mt5Position[]> { return this.post<Mt5Position[]>("/history", { limit }); }
}

export function createMt5Bridge(): IMt5Bridge {
  return MODE === "http" ? new HttpMt5Bridge() : new SimulatedMt5Bridge();
}

export const MT5_BRIDGE_MODE = MODE;
