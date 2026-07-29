import { NextResponse } from "next/server";
import { modifyOrder } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Modify SL / TP on an open position
export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { accountId?: number; tradeId?: number; stopLoss?: number; takeProfit?: number };
  if (!body.accountId || !body.tradeId) return NextResponse.json({ error: "accountId and tradeId required" }, { status: 400 });
  if (body.stopLoss == null && body.takeProfit == null) return NextResponse.json({ error: "stopLoss and/or takeProfit required" }, { status: 400 });
  const res = await modifyOrder(body.accountId, body.tradeId, body.stopLoss, body.takeProfit);
  if (!res.success) return NextResponse.json(res, { status: 404 });
  return NextResponse.json(res);
}
