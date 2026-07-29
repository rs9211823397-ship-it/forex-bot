import { NextResponse } from "next/server";
import { db } from "@/db";
import { trades } from "@/db/schema";
import { desc, eq } from "drizzle-orm";

export const dynamic = "force-dynamic";

// Trade history (closed positions)
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const accountId = searchParams.get("accountId");
  const limit = Math.min(500, Number(searchParams.get("limit") ?? 100));
  const rows = accountId
    ? await db.select().from(trades).where(eq(trades.accountId, Number(accountId))).orderBy(desc(trades.closedAt)).limit(limit)
    : await db.select().from(trades).orderBy(desc(trades.closedAt)).limit(limit);
  return NextResponse.json({ history: rows.filter((r) => r.status !== "open") });
}
