import { NextResponse } from "next/server";
import { db } from "@/db";
import { trades, tradingAccounts, signals, regimeSnapshots } from "@/db/schema";
import { desc, eq, gte } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  void req;
  const accounts = await db.select().from(tradingAccounts);
  // Passwords are stripped — dashboard never receives credentials
  const safeAccounts = accounts.map(({ password: _p, sessionToken: _s, ...a }) => { void _p; void _s; return a; });
  const openTrades = await db.select().from(trades).where(eq(trades.status, "open"));
  const closed = await db.select().from(trades).where(eq(trades.status, "closed")).orderBy(desc(trades.closedAt)).limit(500);
  const recentSignals = await db.select().from(signals).orderBy(desc(signals.createdAt)).limit(20);
  const recentRegimes = await db.select().from(regimeSnapshots).orderBy(desc(regimeSnapshots.createdAt)).limit(20);

  // Aggregate metrics
  const totalBalance = accounts.reduce((s, a) => s + Number(a.balance), 0);
  const totalEquity = accounts.reduce((s, a) => s + Number(a.equity), 0);
  const totalPnL = closed.reduce((s, t) => s + Number(t.profit), 0);
  const wins = closed.filter((t) => Number(t.profit) > 0);
  const losses = closed.filter((t) => Number(t.profit) < 0);
  const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;
  const profitFactor = losses.reduce((s, t) => s + Math.abs(Number(t.profit)), 0) > 0
    ? wins.reduce((s, t) => s + Number(t.profit), 0) / losses.reduce((s, t) => s + Math.abs(Number(t.profit)), 0)
    : 0;

  // Equity curve (cumulative PnL over last 50 closed)
  const equityCurve = closed
    .slice(0, 50)
    .reverse()
    .map((t, i) => ({ x: i, balance: closed.slice(0, 50).slice(0, i + 1).reduce((s, x) => s + Number(x.profit), 0) + Number(accounts[0]?.balance ?? 10000) }));

  return NextResponse.json({
    accounts: safeAccounts,
    openTrades,
    closedTrades: closed.slice(0, 30),
    signals: recentSignals,
    regimes: recentRegimes,
    metrics: {
      totalAccounts: accounts.length,
      activeAccounts: accounts.filter((a) => a.status === "active").length,
      openPositions: openTrades.length,
      totalBalance: Math.round(totalBalance * 100) / 100,
      totalEquity: Math.round(totalEquity * 100) / 100,
      totalPnL: Math.round(totalPnL * 100) / 100,
      winRate: Math.round(winRate * 100) / 100,
      profitFactor: Math.round(profitFactor * 100) / 100,
      totalTrades: closed.length,
    },
    equityCurve,
  });
}
