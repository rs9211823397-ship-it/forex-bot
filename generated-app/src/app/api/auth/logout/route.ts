import { NextResponse } from "next/server";
import { destroySession, extractToken, SESSION_COOKIE } from "@/lib/security/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const token = extractToken(req);
  if (token) await destroySession(token);
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  return res;
}
