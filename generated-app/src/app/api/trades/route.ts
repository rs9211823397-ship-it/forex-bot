import { NextResponse } from "next/server";
import { db } from "@/db";
import { trades, tradingAccounts } from "@/db/schema";
import { desc, eq, and } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const accountId = searchParams.get("accountId");
  const status = searchParams.get("status");
  const mode = searchParams.get("mode");
  const where = [] as ReturnType<typeof eq>[];
  if (accountId) where.push(eq(trades.accountId, Number(accountId)));
  if (status) where.push(eq(trades.status, status as "open" | "closed" | "cancelled"));
  if (mode) where.push(eq(trades.mode, mode as "paper" | "live" | "backtest"));
  const rows = await db
    .select()
    .from(trades)
    .where(where.length > 0 ? and(...where) : undefined)
    .orderBy(desc(trades.openedAt))
    .limit(200);
  return NextResponse.json({ trades: rows });
}

export async function POST(req: Request) {
  const body = (await req.json()) as {
    accountId: number;
    symbol: string;
    direction: "buy" | "sell";
    lots: number;
    entryPrice: number;
    stopLoss?: number;
    takeProfit?: number;
    mode?: "paper" | "live" | "backtest";
    signalId?: number;
    reason?: string;
  };
  const [account] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, body.accountId));
  if (!account) return NextResponse.json({ error: "Account not found" }, { status: 404 });
  const [trade] = await db
    .insert(trades)
    .values({
      accountId: body.accountId,
      signalId: body.signalId ?? null,
      symbol: body.symbol,
      direction: body.direction,
      mode: body.mode || "paper",
      status: "open",
      lots: String(body.lots),
      entryPrice: String(body.entryPrice),
      stopLoss: body.stopLoss != null ? String(body.stopLoss) : null,
      takeProfit: body.takeProfit != null ? String(body.takeProfit) : null,
      profit: "0",
      pips: "0",
      reason: body.reason ?? null,
    })
    .returning();
  return NextResponse.json({ trade });
}

export async function PATCH(req: Request) {
  const body = (await req.json()) as {
    id: number;
    action: "close" | "modify" | "partial_close";
    exitPrice?: number;
    closePercent?: number;
    stopLoss?: number;
    takeProfit?: number;
  };
  const [trade] = await db.select().from(trades).where(eq(trades.id, body.id));
  if (!trade) return NextResponse.json({ error: "Trade not found" }, { status: 404 });
  if (body.action === "close" || body.action === "partial_close") {
    const exitPrice = body.exitPrice ?? Number(trade.entryPrice);
    const entry = Number(trade.entryPrice);
    const lots = Number(trade.lots);
    const dir = trade.direction;
    const pip = 0.0001; // simplified
    const contractSize = 100000;
    const priceDiff = dir === "buy" ? exitPrice - entry : entry - exitPrice;
    const pips = priceDiff / pip;
    const profit = priceDiff * contractSize * lots;
    const [updated] = await db
      .update(trades)
      .set({
        status: body.action === "partial_close" ? trade.status : "closed",
        exitPrice: String(exitPrice),
        profit: String(profit),
        pips: String(pips),
        closedAt: body.action === "partial_close" ? null : new Date(),
      })
      .where(eq(trades.id, body.id))
      .returning();
    // Update account equity
    const [account] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, trade.accountId));
    if (account) {
      const newBalance = Number(account.balance) + profit;
      await db
        .update(tradingAccounts)
        .set({ balance: String(newBalance), equity: String(newBalance) })
        .where(eq(tradingAccounts.id, account.id));
    }
    return NextResponse.json({ trade: updated });
  }
  if (body.action === "modify") {
    const [updated] = await db
      .update(trades)
      .set({
        stopLoss: body.stopLoss != null ? String(body.stopLoss) : trade.stopLoss,
        takeProfit: body.takeProfit != null ? String(body.takeProfit) : trade.takeProfit,
      })
      .where(eq(trades.id, body.id))
      .returning();
    return NextResponse.json({ trade: updated });
  }
  return NextResponse.json({ error: "Unknown action" }, { status: 400 });
}
