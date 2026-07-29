import { NextResponse } from "next/server";
import { db } from "@/db";
import { users } from "@/db/schema";
import { eq } from "drizzle-orm";
import { verifyPassword } from "@/lib/security/passwords";
import { createSession, SESSION_COOKIE, SESSION_TTL_MS } from "@/lib/security/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { username?: string; password?: string };
  if (!body.username || !body.password) {
    return NextResponse.json({ error: "username and password required" }, { status: 400 });
  }
  const [user] = await db.select().from(users).where(eq(users.username, body.username.trim().toLowerCase()));
  if (!user) return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  const ok = await verifyPassword(body.password, user.passwordHash);
  if (!ok) return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });

  const { token, expiresAt } = await createSession(user.id, user.username, user.role, req);
  await db.update(users).set({ lastLoginAt: new Date() }).where(eq(users.id, user.id));

  const res = NextResponse.json({
    token, // mobile clients store this and send as Authorization: Bearer
    user: { id: user.id, username: user.username, role: user.role },
    expiresAt: expiresAt.toISOString(),
  });
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
  });
  return res;
}
