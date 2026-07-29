import { NextResponse } from "next/server";
import { connectAccount } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Login to an MT5 account stored in the roster — credentials come from
// encrypted storage; the client never needs to resend the password (Feature 4)
export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { accountId?: number };
  if (!body.accountId) return NextResponse.json({ error: "accountId required" }, { status: 400 });
  const res = await connectAccount(body.accountId);
  if (!res.connected) return NextResponse.json(res, { status: 401 });
  return NextResponse.json(res);
}
