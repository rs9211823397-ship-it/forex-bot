import { NextResponse } from "next/server";
import { db } from "@/db";
import { signals, regimeSnapshots, systemState } from "@/db/schema";
import { desc, eq, sql } from "drizzle-orm";
import { generateCandles } from "@/lib/engine/marketData";
import { analyzeMarket } from "@/lib/engine/signalEngine";

export const dynamic = "force-dynamic";

interface AnalysisResult {
  action: "buy" | "sell" | "hold";
  quality: "A+" | "A" | "B" | "C" | "reject";
  confidence: number;
  score: number;
  reasons: string[];
  indicators: Record<string, number>;
  regime: "trending" | "ranging" | "volatile" | "low_volatility";
  volatility: "low" | "normal" | "high";
  recommendation: string;
  entryPrice?: number;
  stopLoss?: number;
  takeProfit?: number;
  riskReward: number;
}

async function getOrComputeSignals(
  symbol: string,
  timeframe: string,
  force: boolean
): Promise<AnalysisResult> {
  const cacheKey = `signal:${symbol}:${timeframe}`;
  const [cached] = await db.select().from(systemState).where(eq(systemState.key, cacheKey));
  if (!force && cached) {
    const ageMs = Date.now() - new Date(cached.updatedAt).getTime();
    if (ageMs < 5 * 60 * 1000) {
      return cached.value as AnalysisResult;
    }
  }
  const candles = generateCandles(symbol, timeframe, 250);
  const result = analyzeMarket(candles, symbol);
  if (cached) {
    await db
      .update(systemState)
      .set({ value: result, updatedAt: new Date() })
      .where(eq(systemState.key, cacheKey));
  } else {
    await db.insert(systemState).values({ key: cacheKey, value: result });
  }
  return result;
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const symbol = searchParams.get("symbol") || "EURUSD";
  const timeframe = searchParams.get("timeframe") || "H1";
  const force = searchParams.get("force") === "1";
  const result = await getOrComputeSignals(symbol, timeframe, force);
  // Save regime snapshot
  await db.insert(regimeSnapshots).values({
    symbol,
    timeframe,
    regime: result.regime,
    volatility: result.volatility,
    adx: String(result.indicators?.adx ?? 0),
    atr: String(result.indicators?.atr ?? 0),
    ema20: String(result.indicators?.ema20 ?? 0),
    ema50: String(result.indicators?.ema50 ?? 0),
    ema200: String(result.indicators?.ema200 ?? 0),
    rsi: String(result.indicators?.rsi ?? 0),
    recommendation: result.recommendation,
  });
  return NextResponse.json({ signal: result });
}

export async function POST(req: Request) {
  const body = (await req.json()) as {
    action: "buy" | "sell";
    symbol: string;
    timeframe: string;
  };
  const { searchParams } = new URL(req.url);
  const force = searchParams.get("force") === "1";
  const result = await getOrComputeSignals(body.symbol, body.timeframe, force);
  if (result.action !== body.action || result.quality === "reject") {
    return NextResponse.json({ error: "Signal does not match requested action or rejected", result }, { status: 400 });
  }
  const [saved] = await db
    .insert(signals)
    .values({
      symbol: body.symbol,
      timeframe: body.timeframe,
      action: body.action,
      quality: result.quality,
      confidence: String(result.confidence ?? 0),
      score: result.score ?? 0,
      entryPrice: result.entryPrice ? String(result.entryPrice) : null,
      stopLoss: result.stopLoss ? String(result.stopLoss) : null,
      takeProfit: result.takeProfit ? String(result.takeProfit) : null,
      riskReward: String(result.riskReward ?? 2),
      regime: result.regime,
      volatility: result.volatility,
      reasons: result.reasons,
      indicators: result.indicators,
      executed: false,
    })
    .returning();
  return NextResponse.json({ signal: saved, analysis: result });
}

export async function DELETE() {
  const old = await db
    .select({ id: signals.id })
    .from(signals)
    .orderBy(desc(signals.createdAt))
    .offset(1000)
    .limit(1000);
  if (old.length > 0) {
    const ids = old.map((o) => o.id);
    await db.delete(signals).where(sql`id = ANY(${ids})`);
  }
  return NextResponse.json({ removed: old.length });
}
