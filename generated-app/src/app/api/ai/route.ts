import { NextResponse } from "next/server";
import { db } from "@/db";
import { aiDecisions, signals, trades } from "@/db/schema";
import { desc, eq } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET() {
  const decisions = await db.select().from(aiDecisions).orderBy(desc(aiDecisions.createdAt)).limit(50);
  // Compute win rate from last 100 signals that were executed
  const recentTrades = await db
    .select()
    .from(trades)
    .where(eq(trades.status, "closed"))
    .orderBy(desc(trades.closedAt))
    .limit(100);
  const wins = recentTrades.filter((t) => Number(t.profit) > 0).length;
  const losses = recentTrades.filter((t) => Number(t.profit) < 0).length;
  const winRate = recentTrades.length > 0 ? (wins / recentTrades.length) * 100 : 0;
  const totalProfit = recentTrades.reduce((s, t) => s + Number(t.profit), 0);
  // Per-symbol performance
  const bySymbol: Record<string, { wins: number; losses: number; profit: number; trades: number }> = {};
  for (const t of recentTrades) {
    if (!bySymbol[t.symbol]) bySymbol[t.symbol] = { wins: 0, losses: 0, profit: 0, trades: 0 };
    bySymbol[t.symbol].trades++;
    bySymbol[t.symbol].profit += Number(t.profit);
    if (Number(t.profit) > 0) bySymbol[t.symbol].wins++;
    else bySymbol[t.symbol].losses++;
  }
  // Per-quality
  const byQuality: Record<string, { wins: number; losses: number; total: number }> = {};
  for (const t of recentTrades) {
    const q = t.quality || "B";
    if (!byQuality[q]) byQuality[q] = { wins: 0, losses: 0, total: 0 };
    byQuality[q].total++;
    if (Number(t.profit) > 0) byQuality[q].wins++;
    else byQuality[q].losses++;
  }
  return NextResponse.json({
    decisions,
    summary: {
      totalTrades: recentTrades.length,
      wins,
      losses,
      winRate: Math.round(winRate * 100) / 100,
      totalProfit: Math.round(totalProfit * 100) / 100,
      bySymbol,
      byQuality,
    },
  });
}

export async function POST(req: Request) {
  const body = (await req.json()) as {
    symbol: string;
    action: string;
    quality: string;
    confidence: number;
    regime: string;
    outcome: "win" | "loss" | "pending";
    reward: number;
    features: Record<string, number>;
    notes?: string;
    signalId?: number;
  };
  const [dec] = await db
    .insert(aiDecisions)
    .values({
      symbol: body.symbol,
      action: body.action,
      quality: body.quality,
      confidence: String(body.confidence),
      regime: body.regime,
      outcome: body.outcome,
      reward: String(body.reward),
      features: body.features,
      notes: body.notes ?? null,
      signalId: body.signalId ?? null,
    })
    .returning();
  return NextResponse.json({ decision: dec });
}
