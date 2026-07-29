import { NextResponse } from "next/server";
import { db } from "@/db";
import { executionEvents, mt5Events } from "@/db/schema";
import { desc } from "drizzle-orm";

export const dynamic = "force-dynamic";

// Audit trail for the backend (Feature 6): execution + MT5 connection events
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const limit = Math.min(200, Number(searchParams.get("limit") ?? 50));
  const [exec, mt5] = await Promise.all([
    db.select().from(executionEvents).orderBy(desc(executionEvents.createdAt)).limit(limit),
    db.select().from(mt5Events).orderBy(desc(mt5Events.createdAt)).limit(limit),
  ]);
  return NextResponse.json({ executionEvents: exec, mt5Events: mt5 });
}
