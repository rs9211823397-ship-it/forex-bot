// MT5 Manager (Features 2 & 3) — in-memory registry of live bridge sessions
// keyed by trading account id, with DB persistence of connection state and
// a full audit trail. Passwords are decrypted only inside connect/change flows
// and are never written to logs or API responses.

import { db } from "@/db";
import { tradingAccounts, mt5Events, executionEvents, trades } from "@/db/schema";
import { eq } from "drizzle-orm";
import { decryptCredential, encryptCredential, isEncrypted } from "@/lib/security/crypto";
import { createMt5Bridge, IMt5Bridge, Mt5OrderRequest } from "./bridge";

interface LiveSession {
  bridge: IMt5Bridge;
  sessionToken: string;
  connectedAt: number;
  company?: string;
  latencyMs: number;
}

const registry = (globalThis as typeof globalThis & { __aaqtsMt5Registry?: Map<number, LiveSession> }).__aaqtsMt5Registry ?? new Map<number, LiveSession>();
(globalThis as typeof globalThis & { __aaqtsMt5Registry?: Map<number, LiveSession> }).__aaqtsMt5Registry = registry;

async function logEvent(accountId: number | null, event: string, detail: Record<string, unknown>) {
  await db.insert(mt5Events).values({ accountId, event, detail });
}

async function setConnectionState(accountId: number, patch: Partial<Record<string, string | null | Date>>) {
  await db.update(tradingAccounts).set({ ...patch, updatedAt: new Date() }).where(eq(tradingAccounts.id, accountId));
}

export function getLiveSession(accountId: number) {
  return registry.get(accountId) ?? null;
}

export function listLiveAccountIds(): number[] {
  return Array.from(registry.keys());
}

export async function connectAccount(accountId: number): Promise<{
  connected: boolean;
  error?: string;
  message?: string;
  latencyMs?: number;
  company?: string;
}> {
  const [acc] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, accountId));
  if (!acc) return { connected: false, error: "NOT_FOUND", message: "Account not found" };
  const password = decryptCredential(acc.password);
  const bridge = createMt5Bridge();
  const res = await bridge.connect({ login: acc.accountNumber, password, server: acc.server });
  if (!res.connected) {
    await setConnectionState(accountId, { connectionStatus: "auth_failed", sessionToken: null });
    // Never log the password — only account number + error code
    await logEvent(accountId, "AUTH_FAILED", { login: acc.accountNumber, server: acc.server, error: res.error });
    return { connected: false, error: res.error, message: res.message, latencyMs: res.latencyMs };
  }
  const sessionToken = encryptCredential(res.sessionToken!); // stored encrypted at rest
  registry.set(accountId, {
    bridge,
    sessionToken: res.sessionToken!,
    connectedAt: Date.now(),
    company: res.company,
    latencyMs: res.latencyMs,
  });
  await setConnectionState(accountId, {
    connectionStatus: "connected",
    sessionToken,
    lastConnectedAt: new Date(),
  });
  await logEvent(accountId, "CONNECT", { login: acc.accountNumber, server: acc.server, company: res.company, latencyMs: res.latencyMs });
  return { connected: true, company: res.company, latencyMs: res.latencyMs };
}

export async function disconnectAccount(accountId: number): Promise<void> {
  const live = registry.get(accountId);
  if (live) {
    await live.bridge.disconnect(live.sessionToken);
    registry.delete(accountId);
  }
  await setConnectionState(accountId, { connectionStatus: "disconnected", sessionToken: null });
  await logEvent(accountId, "DISCONNECT", {});
}

export async function changeAccountPassword(accountId: number, newPassword: string) {
  await db.update(tradingAccounts).set({ password: encryptCredential(newPassword), updatedAt: new Date() }).where(eq(tradingAccounts.id, accountId));
  // invalidate live session — force reconnect with new creds
  await disconnectAccount(accountId);
}

export interface PlaceOrderOutcome {
  success: boolean;
  tradeId?: number;
  ticket?: string;
  fillPrice?: number;
  error?: string;
  latencyMs?: number;
}

export async function placeOrder(accountId: number, req: Mt5OrderRequest & { mode: "paper" | "live"; signalId?: number; reason?: string | null }): Promise<PlaceOrderOutcome> {
  const [acc] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, accountId));
  if (!acc) return { success: false, error: "Account not found" };
  if (acc.status !== "active") return { success: false, error: `Account status ${acc.status}` };
  if (!acc.tradingEnabled) return { success: false, error: "Trading disabled on account" };

  const t0 = Date.now();
  let ticket: string | undefined;
  let fill: number | undefined;
  const live = registry.get(accountId);
  if (req.mode === "live") {
    // Live mode requires an authenticated MT5 session
    if (!live) return { success: false, error: "MT5 session not connected" };
    const r = await live.bridge.placeOrder(req);
    if (!r.success) return { success: false, error: r.error, latencyMs: r.latencyMs };
    ticket = r.ticket;
    fill = r.fillPrice;
  } else {
    // Paper mode — route through the same bridge simulation without needing login
    const bridge = createMt5Bridge();
    const r = await bridge.placeOrder(req);
    if (!r.success) return { success: false, error: r.error, latencyMs: r.latencyMs };
    ticket = r.ticket;
    fill = r.fillPrice;
  }

  const [trade] = await db
    .insert(trades)
    .values({
      accountId,
      signalId: req.signalId ?? null,
      mt5Ticket: ticket ?? null,
      symbol: req.symbol,
      direction: req.direction,
      mode: req.mode,
      status: "open",
      lots: String(req.lots),
      entryPrice: String(fill ?? req.entryPrice ?? 0),
      stopLoss: req.stopLoss != null ? String(req.stopLoss) : null,
      takeProfit: req.takeProfit != null ? String(req.takeProfit) : null,
      profit: "0",
      pips: "0",
      reason: req.reason ?? req.comment ?? null,
    })
    .returning();
  const latencyMs = Date.now() - t0;
  await db.insert(executionEvents).values({
    accountId,
    tradeId: trade.id,
    action: "ORDER_OPEN",
    latencyMs,
    detail: { symbol: req.symbol, direction: req.direction, lots: req.lots, mode: req.mode, ticket, sl: req.stopLoss, tp: req.takeProfit },
  });
  await logEvent(accountId, "ORDER_OPEN", { tradeId: trade.id, symbol: req.symbol, ticket, mode: req.mode });
  return { success: true, tradeId: trade.id, ticket, fillPrice: fill, latencyMs };
}

export async function modifyOrder(accountId: number, tradeId: number, sl?: number, tp?: number) {
  const [trade] = await db.select().from(trades).where(eq(trades.id, tradeId));
  if (!trade || trade.accountId !== accountId) return { success: false as const, error: "Trade not found" };
  const live = registry.get(accountId);
  if (trade.mt5Ticket && live) {
    await live.bridge.modifyOrder(trade.mt5Ticket, sl, tp);
  }
  await db.update(trades).set({
    stopLoss: sl != null ? String(sl) : trade.stopLoss,
    takeProfit: tp != null ? String(tp) : trade.takeProfit,
  }).where(eq(trades.id, tradeId));
  await db.insert(executionEvents).values({ accountId, tradeId, action: "ORDER_MODIFY", detail: { sl, tp } });
  return { success: true as const };
}

export async function closeOrder(accountId: number, tradeId: number, percent = 100) {
  const [trade] = await db.select().from(trades).where(eq(trades.id, tradeId));
  if (!trade || trade.accountId !== accountId) return { success: false as const, error: "Trade not found" };
  if (trade.status !== "open") return { success: false as const, error: "Trade not open" };
  const profile = (await import("@/lib/engine/marketData")).getProfile(trade.symbol);
  const { generateTick } = await import("@/lib/engine/marketData");
  let exit = generateTick(trade.symbol);
  let closedLots = Number(trade.lots);
  if (trade.mt5Ticket && registry.get(accountId)) {
    const r = await registry.get(accountId)!.bridge.closeOrder(trade.mt5Ticket, percent);
    if (r.fillPrice) exit = r.fillPrice;
    if (r.closedLots) closedLots = r.closedLots;
  }
  const entry = Number(trade.entryPrice);
  const lots = Number(trade.lots);
  const priceDiff = trade.direction === "buy" ? exit - entry : entry - exit;
  const profit = priceDiff * profile.contractSize * closedLots;
  const pips = priceDiff / profile.pip;
  if (percent >= 100) {
    await db.update(trades).set({
      status: "closed", exitPrice: String(exit), profit: String(profit), pips: String(pips), closedAt: new Date(),
    }).where(eq(trades.id, tradeId));
    const [acc] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, accountId));
    if (acc) {
      const nb = Number(acc.balance) + profit;
      await db.update(tradingAccounts).set({ balance: String(nb), equity: String(nb), updatedAt: new Date() }).where(eq(tradingAccounts.id, accountId));
    }
  } else {
    const remaining = (lots - closedLots).toFixed(2);
    await db.update(trades).set({ lots: String(remaining), profit: String(profit) }).where(eq(trades.id, tradeId));
  }
  await db.insert(executionEvents).values({ accountId, tradeId, action: "ORDER_CLOSE", detail: { percent, exit, profit, closedLots } });
  await logEvent(accountId, "ORDER_CLOSE", { tradeId, symbol: trade.symbol, profit });
  return { success: true as const, exitPrice: exit, profit, closedLots };
}

// Used by one-time migration: re-encrypt any legacy plaintext passwords in place.
export async function migrateLegacyPasswords(): Promise<number> {
  const all = await db.select().from(tradingAccounts);
  let migrated = 0;
  for (const acc of all) {
    if (acc.password && !isEncrypted(acc.password)) {
      await db.update(tradingAccounts).set({ password: encryptCredential(acc.password) }).where(eq(tradingAccounts.id, acc.id));
      migrated++;
    }
  }
  return migrated;
}
