import { NextResponse } from "next/server";
import { db } from "@/db";
import { tradingAccounts, signals, trades, aiDecisions, backtests } from "@/db/schema";
import { sql } from "drizzle-orm";
import { generateCandles, getProfile } from "@/lib/engine/marketData";
import { analyzeMarket } from "@/lib/engine/signalEngine";
import { encryptCredential } from "@/lib/security/crypto";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Idempotent demo-data seeder — requires an authenticated admin session.
// Safe to call repeatedly; each section only fills empty tables/minimums.
export async function POST(req: Request) {
  const auth = await requireUser(req);
  const seeded: Record<string, number> = {};

  // Accounts
  const existing = await db.select().from(tradingAccounts);
  if (existing.length === 0) {
    const demo = [
      { name: "Exness Demo 01", accountNumber: "21184723", server: "Exness-MT5Trial6", broker: "exness" as const, accountType: "demo" as const, balance: 10000, risk: 1 },
      { name: "Exness Demo 02", accountNumber: "21184724", server: "Exness-MT5Trial6", broker: "exness" as const, accountType: "demo" as const, balance: 5000, risk: 0.5 },
      { name: "Exness Live 03", accountNumber: "21184725", server: "Exness-MT5Real8", broker: "exness" as const, accountType: "standard" as const, balance: 25000, risk: 2 },
      { name: "Exness Live Raw 04", accountNumber: "21184726", server: "Exness-MT5Real9", broker: "exness" as const, accountType: "raw_spread" as const, balance: 50000, risk: 1.5 },
      { name: "IC Markets Pro", accountNumber: "10982341", server: "ICMarkets-MT5-01", broker: "ic_markets" as const, accountType: "raw_spread" as const, balance: 8000, risk: 1 },
    ];
    for (const a of demo) {
      await db.insert(tradingAccounts).values({
        userId: auth.id,
        name: a.name,
        accountNumber: a.accountNumber,
        password: encryptCredential("demo-password-" + a.accountNumber), // encrypted at rest
        server: a.server,
        broker: a.broker,
        accountType: a.accountType,
        connectionStatus: "not_configured",
        balance: String(a.balance),
        equity: String(a.balance),
        freeMargin: String(a.balance),
        riskPercent: String(a.risk),
        maxDailyLoss: "3",
        maxWeeklyLoss: "8",
        maxConsecutiveLosses: 3,
      });
      seeded.accounts = (seeded.accounts ?? 0) + 1;
    }
  }

  // Signals
  const sigCount = await db.select({ c: sql<number>`count(*)::int` }).from(signals);
  if ((sigCount[0]?.c ?? 0) < 5) {
    for (const sym of ["EURUSD", "XAUUSD", "GBPUSD", "USDJPY", "BTCUSD"]) {
      const candles = generateCandles(sym, "H1", 250);
      const analysis = analyzeMarket(candles, sym);
      if (analysis.action === "hold") continue;
      await db.insert(signals).values({
        symbol: sym,
        timeframe: "H1",
        action: analysis.action,
        quality: analysis.quality,
        confidence: String(analysis.confidence),
        score: analysis.score,
        entryPrice: analysis.entryPrice ? String(analysis.entryPrice) : null,
        stopLoss: analysis.stopLoss ? String(analysis.stopLoss) : null,
        takeProfit: analysis.takeProfit ? String(analysis.takeProfit) : null,
        riskReward: String(analysis.riskReward),
        regime: analysis.regime,
        volatility: analysis.volatility,
        reasons: analysis.reasons,
        indicators: analysis.indicators,
        executed: false,
        createdAt: new Date(Date.now() - Math.random() * 24 * 60 * 60 * 1000),
      });
      seeded.signals = (seeded.signals ?? 0) + 1;
    }
  }

  // Closed trades (history equity curve)
  const closedCount = await db.select({ c: sql<number>`count(*)::int` }).from(trades).where(sql`status = 'closed'`);
  if ((closedCount[0]?.c ?? 0) < 30) {
    const accounts = await db.select().from(tradingAccounts);
    if (accounts.length > 0) {
      const syms = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY", "BTCUSD"];
      for (let i = 0; i < 40; i++) {
        const acc = accounts[i % accounts.length];
        const sym = syms[i % syms.length];
        const dir = Math.random() > 0.5 ? "buy" : "sell";
        const profile = getProfile(sym);
        const entry = profile.basePrice * (1 + (Math.random() - 0.5) * 0.02);
        const win = Math.random() < 0.6;
        const exit = win ? entry * (1 + Math.random() * 0.005 * (dir === "buy" ? 1 : -1)) : entry * (1 - Math.random() * 0.003 * (dir === "buy" ? 1 : -1));
        const priceDiff = dir === "buy" ? exit - entry : entry - exit;
        const lots = 0.1 + Math.random() * 0.5;
        const profit = priceDiff * profile.contractSize * lots;
        const quality = ["A+", "A", "B", "C"][Math.floor(Math.random() * 4)];
        const openedAt = new Date(Date.now() - i * 3 * 3600000);
        await db.insert(trades).values({
          accountId: acc.id,
          symbol: sym,
          direction: dir as "buy" | "sell",
          mode: "paper",
          status: "closed",
          lots: String(lots),
          entryPrice: String(entry),
          exitPrice: String(exit),
          stopLoss: null,
          takeProfit: null,
          profit: String(profit),
          pips: String(priceDiff / profile.pip),
          quality,
          reason: `${quality} confluence`,
          openedAt,
          closedAt: new Date(openedAt.getTime() + 1800000),
        });
        seeded.closedTrades = (seeded.closedTrades ?? 0) + 1;
      }
    }
  }

  // Open positions
  const openCount = await db.select({ c: sql<number>`count(*)::int` }).from(trades).where(sql`status = 'open'`);
  if ((openCount[0]?.c ?? 0) < 3) {
    const accounts = await db.select().from(tradingAccounts);
    if (accounts.length > 0) {
      const syms = ["XAUUSD", "EURUSD", "BTCUSD"];
      for (let i = 0; i < 3; i++) {
        const acc = accounts[i % accounts.length];
        const sym = syms[i];
        const dir = i % 2 === 0 ? "buy" : "sell";
        const profile = getProfile(sym);
        const entry = profile.basePrice * (1 + (Math.random() - 0.5) * 0.01);
        const sl = entry * 0.005;
        const tp = entry * 0.012;
        await db.insert(trades).values({
          accountId: acc.id,
          symbol: sym,
          direction: dir as "buy" | "sell",
          mode: "paper",
          status: "open",
          lots: String(0.1 + i * 0.1),
          entryPrice: String(entry),
          stopLoss: String(dir === "buy" ? entry - sl : entry + sl),
          takeProfit: String(dir === "buy" ? entry + tp : entry - tp),
          profit: "0",
          pips: "0",
          quality: ["A+", "A", "B"][i],
          reason: "active",
        });
        seeded.openTrades = (seeded.openTrades ?? 0) + 1;
      }
    }
  }

  // AI decisions
  const aiCount = await db.select({ c: sql<number>`count(*)::int` }).from(aiDecisions);
  if ((aiCount[0]?.c ?? 0) < 20) {
    const syms = ["EURUSD", "XAUUSD", "GBPUSD", "BTCUSD"];
    for (let i = 0; i < 25; i++) {
      const outcome = Math.random() > 0.4 ? "win" : "loss";
      await db.insert(aiDecisions).values({
        symbol: syms[i % syms.length],
        action: Math.random() > 0.5 ? "buy" : "sell",
        quality: ["A+", "A", "B", "C"][Math.floor(Math.random() * 4)],
        confidence: String(50 + Math.random() * 45),
        regime: ["trending", "ranging", "volatile"][Math.floor(Math.random() * 3)],
        outcome,
        reward: String(outcome === "win" ? 1 + Math.random() : -1 - Math.random()),
        features: { rsi: 50 + Math.random() * 30, adx: 15 + Math.random() * 30 },
        createdAt: new Date(Date.now() - i * 3600000),
      });
      seeded.aiDecisions = (seeded.aiDecisions ?? 0) + 1;
    }
  }

  const btCount = await db.select({ c: sql<number>`count(*)::int` }).from(backtests);
  if ((btCount[0]?.c ?? 0) < 1) seeded.backtests = 0;

  return NextResponse.json({ ok: true, seeded });
}
