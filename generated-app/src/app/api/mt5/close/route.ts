import { NextResponse } from "next/server";
import { closeOrder } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Close trade (full or partial). percent: 1..100 (default 100)
export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { accountId?: number; tradeId?: number; percent?: number };
  if (!body.accountId || !body.tradeId) return NextResponse.json({ error: "accountId and tradeId required" }, { status: 400 });
  const percent = Math.max(1, Math.min(100, body.percent ?? 100));
  const res = await closeOrder(body.accountId, body.tradeId, percent);
  if (!res.success) return NextResponse.json(res, { status: 404 });
  return NextResponse.json(res);
}
