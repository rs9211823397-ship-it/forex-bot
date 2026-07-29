import { NextResponse } from "next/server";
import { disconnectAccount } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { accountId?: number };
  if (!body.accountId) return NextResponse.json({ error: "accountId required" }, { status: 400 });
  await disconnectAccount(body.accountId);
  return NextResponse.json({ ok: true });
}
