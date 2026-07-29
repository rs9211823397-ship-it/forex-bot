import { NextResponse } from "next/server";
import { db } from "@/db";
import { signals } from "@/db/schema";
import { desc } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET() {
  const rows = await db.select().from(signals).orderBy(desc(signals.createdAt)).limit(50);
  return NextResponse.json({ signals: rows });
}
