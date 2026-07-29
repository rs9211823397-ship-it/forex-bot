import { NextResponse } from "next/server";
import { placeOrder } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";
import { getBotState } from "@/lib/bot/controller";
import { canOpenOrder } from "@/lib/bot/state";

export const dynamic = "force-dynamic";

// BUY/SELL order on a single MT5 account (Feature 3):
// { accountId, symbol, direction, lots, entryPrice?, stopLoss?, takeProfit?, mode: paper|live }
export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as {
    accountId?: number; symbol?: string; direction?: "buy" | "sell";
    lots?: number; entryPrice?: number; stopLoss?: number; takeProfit?: number;
    mode?: "paper" | "live"; signalId?: number; reason?: string;
  };
  if (!body.accountId || !body.symbol || !body.direction || !body.lots) {
    return NextResponse.json({ error: "accountId, symbol, direction, lots required" }, { status: 400 });
  }
  const bot = await getBotState();
  const gate = canOpenOrder(bot.status);
  // Manual operator orders are allowed while RUNNING (and when STOPPED, manual trades are
  // intentionally blocked too — consistent with "stop opening new positions").
  if (!gate.allowed) return NextResponse.json({ error: gate.reason, botStatus: bot.status }, { status: 409 });
  const res = await placeOrder(body.accountId, {
    symbol: body.symbol,
    direction: body.direction,
    lots: body.lots,
    entryPrice: body.entryPrice,
    stopLoss: body.stopLoss,
    takeProfit: body.takeProfit,
    mode: body.mode ?? bot.mode,
    signalId: body.signalId,
    reason: body.reason ?? "manual_operator_order",
  });
  if (!res.success) return NextResponse.json(res, { status: 400 });
  return NextResponse.json(res);
}
