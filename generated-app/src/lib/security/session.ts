// Server-side session management (Node runtime only — DB persistence + revocation)
// Works for cookie-based web sessions and Bearer-token mobile clients (same token format).

import { db } from "@/db";
import { sessions, users } from "@/db/schema";
import { eq, and, gt } from "drizzle-orm";
import { signSessionToken, verifySessionToken, sha256Hex, SESSION_TTL_MS, SessionPayload } from "./token";
import { NextResponse } from "next/server";

export const SESSION_COOKIE = "aaqts_session";
export { SESSION_TTL_MS };

export interface AuthUser {
  id: number;
  username: string;
  role: string;
  token: string;
}

export async function createSession(userId: number, username: string, role: string, req?: Request): Promise<{ token: string; expiresAt: Date }> {
  const { token, payload } = await signSessionToken({ uid: userId, u: username, role });
  const tokenHash = await sha256Hex(token);
  const expiresAt = new Date(payload.exp);
  await db.insert(sessions).values({
    tokenHash,
    userId,
    userAgent: req?.headers.get("user-agent") ?? null,
    ip: req?.headers.get("x-forwarded-for") ?? null,
    expiresAt,
  });
  return { token, expiresAt };
}

export async function destroySession(token: string): Promise<void> {
  const tokenHash = await sha256Hex(token);
  await db.delete(sessions).where(eq(sessions.tokenHash, tokenHash));
}

export function extractToken(req: Request): string | null {
  const authz = req.headers.get("authorization");
  if (authz?.toLowerCase().startsWith("bearer ")) return authz.slice(7).trim();
  const cookie = req.headers.get("cookie") || "";
  for (const part of cookie.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === SESSION_COOKIE && rest.length) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export async function getAuthUser(req: Request): Promise<AuthUser | null> {
  const token = extractToken(req);
  if (!token) return null;
  const payload: SessionPayload | null = await verifySessionToken(token);
  if (!payload) return null;
  // DB check (revocation)
  const tokenHash = await sha256Hex(token);
  const [row] = await db
    .select({ id: sessions.id })
    .from(sessions)
    .where(and(eq(sessions.tokenHash, tokenHash), gt(sessions.expiresAt, new Date())));
  if (!row) return null;
  return { id: payload.uid, username: payload.u, role: payload.role, token };
}

export function unauthorized(): NextResponse {
  return NextResponse.json({ error: "UNAUTHORIZED", message: "Login required" }, { status: 401 });
}

// Guard helper for critical API routes
export async function requireUser(req: Request): Promise<AuthUser> {
  const user = await getAuthUser(req);
  if (!user) throw unauthorized();
  return user;
}

export async function ensureAdminUser(username: string, passwordHash: string) {
  const [existing] = await db.select().from(users).where(eq(users.username, username));
  if (existing) return existing;
  const [created] = await db.insert(users).values({ username, passwordHash, role: "admin" }).returning();
  return created;
}
