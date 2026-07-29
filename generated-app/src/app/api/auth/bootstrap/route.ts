import { NextResponse } from "next/server";
import { db } from "@/db";
import { users, systemState } from "@/db/schema";
import { eq } from "drizzle-orm";
import { hashPassword } from "@/lib/security/passwords";
import { migrateLegacyPasswords } from "@/lib/mt5/manager";

export const dynamic = "force-dynamic";

const FLAG_KEY = "security_bootstrap_v1";

// One-time security bootstrap:
//  - creates the initial admin user if no users exist
//  - encrypts any legacy plaintext MT5 account passwords in-place
//  - marks completion in system_state so it cannot be replayed wholesale
export async function GET() {
  const allUsers = await db.select().from(users);
  const [flag] = await db.select().from(systemState).where(eq(systemState.key, FLAG_KEY));
  return NextResponse.json({ bootstrapped: !!flag, users: allUsers.length });
}

export async function POST() {
  const results: Record<string, unknown> = {};
  const allUsers = await db.select().from(users);
  if (allUsers.length === 0) {
    const username = (process.env.ADMIN_USERNAME || "admin").toLowerCase();
    const password = process.env.ADMIN_PASSWORD || "admin123";
    await db.insert(users).values({ username, passwordHash: await hashPassword(password), role: "admin" });
    results.createdAdmin = username;
    results.usingDefaultPassword = !process.env.ADMIN_PASSWORD;
  }
  const migrated = await migrateLegacyPasswords();
  results.migratedLegacyPasswords = migrated;
  const [flag] = await db.select().from(systemState).where(eq(systemState.key, FLAG_KEY));
  const value = { at: new Date().toISOString() };
  if (flag) await db.update(systemState).set({ value, updatedAt: new Date() }).where(eq(systemState.key, FLAG_KEY));
  else await db.insert(systemState).values({ key: FLAG_KEY, value });
  return NextResponse.json({ ok: true, ...results });
}
