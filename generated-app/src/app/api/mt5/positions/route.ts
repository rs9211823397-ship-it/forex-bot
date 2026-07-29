import { NextResponse } from "next/server";
import { db } from "@/db";
import { trades, tradingAccounts } from "@/db/schema";
import { eq, and } from "drizzle-orm";
import { generateTick, getProfile } from "@/lib/engine/marketData";

export const dynamic = "force-dynamic";

// Open positions with live unrealized PnL — used by web + mobile TradeMonitor
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const accountId = searchParams.get("accountId");
  const where = accountId
    ? and(eq(trades.status, "open"), eq(trades.accountId, Number(accountId)))
    : eq(trades.status, "open");
  const open = await db.select().from(trades).where(where);
  const accounts = await db.select().from(tradingAccounts);
  const accountMap = new Map(accounts.map((a) => [a.id, a]));
  const positions = open.map((t) => {
    const profile = getProfile(t.symbol);
    const entry = Number(t.entryPrice);
    const lots = Number(t.lots);
    const current = generateTick(t.symbol, entry);
    const diff = t.direction === "buy" ? current - entry : entry - current;
    const unrealizedPnL = +(diff * profile.contractSize * lots).toFixed(2);
    const acc = accountMap.get(t.accountId);
    return {
      tradeId: t.id,
      ticket: t.mt5Ticket,
      accountId: t.accountId,
      accountName: acc?.name,
      symbol: t.symbol,
      direction: t.direction,
      lots,
      entryPrice: entry,
      currentPrice: current,
      stopLoss: t.stopLoss ? Number(t.stopLoss) : null,
      takeProfit: t.takeProfit ? Number(t.takeProfit) : null,
      unrealizedPnL,
      openedAt: t.openedAt,
      mode: t.mode,
    };
  });
  return NextResponse.json({ positions, count: positions.length });
}
