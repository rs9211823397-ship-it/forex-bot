import { NextResponse } from "next/server";
import { changeAccountPassword } from "@/lib/mt5/manager";
import { requireUser } from "@/lib/security/session";
import { db } from "@/db";
import { tradingAccounts } from "@/db/schema";
import { eq } from "drizzle-orm";

export const dynamic = "force-dynamic";

// Change the MT5 account password (Feature 4) — stored AES-256-GCM encrypted,
// invalidates any live MT5 session so the account reconnects with new creds.
export async function POST(req: Request) {
  await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { accountId?: number; newPassword?: string };
  if (!body.accountId || !body.newPassword) {
    return NextResponse.json({ error: "accountId and newPassword required" }, { status: 400 });
  }
  if (body.newPassword.length < 6) {
    return NextResponse.json({ error: "Password must be at least 6 characters" }, { status: 400 });
  }
  const [acc] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, body.accountId));
  if (!acc) return NextResponse.json({ error: "Account not found" }, { status: 404 });
  await changeAccountPassword(body.accountId, body.newPassword);
  return NextResponse.json({ ok: true, message: "Password updated — account marked for reconnection" });
}
