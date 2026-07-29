import { NextResponse } from "next/server";
import { db } from "@/db";
import { tradingAccounts } from "@/db/schema";
import { eq } from "drizzle-orm";
import { encryptCredential } from "@/lib/security/crypto";
import { requireUser } from "@/lib/security/session";

export const dynamic = "force-dynamic";

// Passwords are NEVER returned (Feature 4)
function sanitize<T extends { password?: unknown; sessionToken?: unknown }>(acc: T) {
  const { password: _p, sessionToken: _s, ...rest } = acc;
  void _p; void _s;
  return rest;
}

export async function GET() {
  const accounts = await db.select().from(tradingAccounts).orderBy(tradingAccounts.id);
  return NextResponse.json({ accounts: accounts.map(sanitize) });
}

export async function POST(req: Request) {
  const auth = await requireUser(req);
  const body = (await req.json()) as {
    name: string;
    accountNumber: string;
    password: string;
    server: string;
    broker?: "exness" | "ic_markets" | "pepperstone" | "mt5_demo" | "other";
    accountType?: "standard" | "raw_spread" | "pro" | "demo";
    balance?: number;
    riskPercent?: number;
    maxDailyLoss?: number;
    maxWeeklyLoss?: number;
    maxConsecutiveLosses?: number;
  };
  if (!body.password || body.password.length < 6) {
    return NextResponse.json({ error: "MT5 password must be at least 6 characters" }, { status: 400 });
  }
  const [created] = await db
    .insert(tradingAccounts)
    .values({
      userId: auth.id,
      name: body.name,
      accountNumber: body.accountNumber,
      password: encryptCredential(body.password), // AES-256-GCM at rest
      server: body.server,
      broker: body.broker || "exness",
      accountType: body.accountType || "standard",
      connectionStatus: "not_configured",
      balance: String(body.balance ?? 10000),
      equity: String(body.balance ?? 10000),
      freeMargin: String(body.balance ?? 10000),
      riskPercent: String(body.riskPercent ?? 1),
      maxDailyLoss: String(body.maxDailyLoss ?? 3),
      maxWeeklyLoss: String(body.maxWeeklyLoss ?? 8),
      maxConsecutiveLosses: body.maxConsecutiveLosses ?? 3,
    })
    .returning();
  return NextResponse.json({ account: sanitize(created) });
}

export async function PATCH(req: Request) {
  await requireUser(req);
  const body = (await req.json()) as {
    id: number;
    status?: "active" | "paused" | "stopped" | "error";
    tradingEnabled?: boolean;
    riskPercent?: number;
    balance?: number;
    equity?: number;
  };
  const update: Record<string, unknown> = { updatedAt: new Date() };
  if (body.status) update.status = body.status;
  if (body.tradingEnabled !== undefined) update.tradingEnabled = body.tradingEnabled;
  if (body.riskPercent !== undefined) update.riskPercent = String(body.riskPercent);
  if (body.balance !== undefined) update.balance = String(body.balance);
  if (body.equity !== undefined) update.equity = String(body.equity);
  const [updated] = await db
    .update(tradingAccounts)
    .set(update)
    .where(eq(tradingAccounts.id, body.id))
    .returning();
  return NextResponse.json({ account: sanitize(updated) });
}

export async function DELETE(req: Request) {
  await requireUser(req);
  const { searchParams } = new URL(req.url);
  const id = Number(searchParams.get("id"));
  if (!id) return NextResponse.json({ error: "id required" }, { status: 400 });
  await db.delete(tradingAccounts).where(eq(tradingAccounts.id, id));
  return NextResponse.json({ ok: true });
}
