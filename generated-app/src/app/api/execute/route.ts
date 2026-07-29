import { NextResponse } from "next/server";
import { db } from "@/db";
import { signals, trades, tradingAccounts } from "@/db/schema";
import { eq } from "drizzle-orm";
import { buildExecutionPlan, buildTradeFromPlan, AccountRuntime } from "@/lib/engine/execution";
import { getBotState } from "@/lib/bot/controller";
import { canOpenOrder } from "@/lib/bot/state";
import { placeOrder } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Copy-execution: broadcast a master signal to every enabled account with
// per-account risk scaling (Features 1, 2 & 13 from PRD)
export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json()) as {
    signalId: number;
    mode?: "paper" | "live";
    manual?: boolean; // operator-initiated override for when bot is PAUSED
  };
  const [signal] = await db.select().from(signals).where(eq(signals.id, body.signalId));
  if (!signal) return NextResponse.json({ error: "Signal not found" }, { status: 404 });
  if (signal.action === "hold") return NextResponse.json({ error: "Cannot execute HOLD signal" }, { status: 400 });

  // Bot gate (Feature 1): emergency blocks everything; PAUSED blocks auto execution
  const bot = await getBotState();
  const gate = canOpenOrder(bot.status, { manualOperatorTrade: body.manual === true });
  if (!gate.allowed) {
    return NextResponse.json({ error: gate.reason, botStatus: bot.status }, { status: 409 });
  }

  const mode = body.mode || bot.mode;
  const allAccounts = await db.select().from(tradingAccounts);
  // Only enabled accounts receive copies; live mode also requires connection
  const accounts = allAccounts.filter(
    (a) => a.status === "active" && a.tradingEnabled &&
      (mode === "paper" ? true : a.connectionStatus === "connected" && a.broker !== "mt5_demo")
  );

  const allTrades = await db.select().from(trades);
  const openByAccount = new Map<number, Set<string>>();
  for (const t of allTrades.filter((x) => x.status === "open")) {
    if (!openByAccount.has(t.accountId)) openByAccount.set(t.accountId, new Set());
    openByAccount.get(t.accountId)!.add(t.symbol);
  }
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfWeek = new Date(now);
  startOfWeek.setDate(now.getDate() - now.getDay());
  startOfWeek.setHours(0, 0, 0, 0);

  const runtimes: AccountRuntime[] = accounts.map((a) => {
    const closed = allTrades.filter((t) => t.accountId === a.id && t.status === "closed");
    const dailyPnL = closed.filter((t) => t.closedAt && new Date(t.closedAt) >= startOfDay).reduce((s, t) => s + Number(t.profit), 0);
    const weeklyPnL = closed.filter((t) => t.closedAt && new Date(t.closedAt) >= startOfWeek).reduce((s, t) => s + Number(t.profit), 0);
    const recent = closed
      .filter((t) => t.closedAt)
      .sort((a, b) => new Date(b.closedAt!).getTime() - new Date(a.closedAt!).getTime())
      .slice(0, 10);
    let consec = 0;
    for (const t of recent) {
      if (Number(t.profit) < 0) consec++;
      else break;
    }
    return {
      account: a,
      openSymbols: Array.from(openByAccount.get(a.id) || []),
      dailyPnL,
      weeklyPnL,
      consecutiveLosses: consec,
    };
  });

  const plans = buildExecutionPlan(signal, runtimes, mode);
  const executed: Array<{ accountId: number; tradeId: number | undefined; lots: number }> = [];
  const blocked: Array<{ accountId: number; accountName: string; reason: string }> = [];
  for (const plan of plans) {
    if (!plan.allowed) {
      blocked.push({ accountId: plan.accountId, accountName: plan.accountName, reason: plan.blockedReason || "blocked" });
      continue;
    }
    // Route through MT5 manager for uniform audit + tickets
    const res = await placeOrder(plan.accountId, {
      symbol: signal.symbol,
      direction: signal.action as "buy" | "sell",
      lots: plan.lots,
      entryPrice: plan.entryPrice,
      stopLoss: plan.stopLoss || undefined,
      takeProfit: plan.takeProfit || undefined,
      mode,
      signalId: signal.id,
      reason: `signal_copy quality=${signal.quality} confidence=${signal.confidence}`,
      comment: `aaqts-sig-${signal.id}`,
    });
    if (res.success) executed.push({ accountId: plan.accountId, tradeId: res.tradeId, lots: plan.lots });
    else blocked.push({ accountId: plan.accountId, accountName: plan.accountName, reason: res.error || "order rejected" });
  }
  // keep legacy buildTradeFromPlan import referenced for compatibility
  void buildTradeFromPlan;
  await db.update(signals).set({ executed: executed.length > 0 }).where(eq(signals.id, signal.id));
  return NextResponse.json({
    botStatus: bot.status,
    mode,
    executed,
    blocked,
    summary: {
      accountCount: accounts.length,
      executedCount: executed.length,
      blockedCount: blocked.length,
      totalLots: executed.reduce((s, e) => s + e.lots, 0),
    },
  });
}
