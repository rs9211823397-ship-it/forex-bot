import { NextResponse } from "next/server";
import { db } from "@/db";
import { users } from "@/db/schema";
import { eq } from "drizzle-orm";
import { hashPassword, verifyPassword } from "@/lib/security/passwords";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Change the login user password (web admin password, not MT5 account passwords)
export async function POST(req: Request) {
  const auth = await requireUser(req);
  const body = (await req.json().catch(() => ({}))) as { currentPassword?: string; newPassword?: string };
  if (!body.currentPassword || !body.newPassword) {
    return NextResponse.json({ error: "currentPassword and newPassword required" }, { status: 400 });
  }
  if (body.newPassword.length < 8) {
    return NextResponse.json({ error: "New password must be at least 8 characters" }, { status: 400 });
  }
  const [user] = await db.select().from(users).where(eq(users.id, auth.id));
  if (!user) return NextResponse.json({ error: "User not found" }, { status: 404 });
  const ok = await verifyPassword(body.currentPassword, user.passwordHash);
  if (!ok) return NextResponse.json({ error: "Current password incorrect" }, { status: 403 });
  await db.update(users).set({ passwordHash: await hashPassword(body.newPassword) }).where(eq(users.id, user.id));
  return NextResponse.json({ ok: true });
}
