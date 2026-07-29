import { NextResponse } from "next/server";
import { db } from "@/db";
import { backtests, trades } from "@/db/schema";
import { desc, eq } from "drizzle-orm";
import { generateCandles } from "@/lib/engine/marketData";
import { analyzeMarket } from "@/lib/engine/signalEngine";
import { getProfile } from "@/lib/engine/marketData";

export const dynamic = "force-dynamic";

export async function GET() {
  const rows = await db.select().from(backtests).orderBy(desc(backtests.createdAt)).limit(20);
  return NextResponse.json({ backtests: rows });
}

export async function POST(req: Request) {
  const body = (await req.json()) as {
    name: string;
    symbol: string;
    timeframe: string;
    candleCount?: number;
    initialBalance?: number;
  };
  const symbol = body.symbol;
  const timeframe = body.timeframe;
  const candleCount = body.candleCount ?? 1000;
  const initialBalance = body.initialBalance ?? 10000;
  const candles = generateCandles(symbol, timeframe, candleCount);
  // Walk forward — analyze each rolling window
  const windowSize = 60;
  const step = 5;
  const profile = getProfile(symbol);
  let balance = initialBalance;
  let equity = initialBalance;
  let peak = initialBalance;
  let maxDD = 0;
  let wins = 0;
  let losses = 0;
  let totalWins = 0;
  let totalLosses = 0;
  let totalTrades = 0;
  const tradeLog: Array<Record<string, unknown>> = [];
  const dailyReturns: number[] = [];
  for (let i = windowSize; i < candles.length; i += step) {
    const window = candles.slice(i - windowSize, i + 1);
    const analysis = analyzeMarket(window, symbol);
    if (analysis.action === "hold" || analysis.quality === "reject") continue;
    if (!analysis.entryPrice || !analysis.stopLoss || !analysis.takeProfit) continue;
    // Simulate exit on next ~10 candles
    const direction = analysis.action;
    const entry = analysis.entryPrice;
    const sl = analysis.stopLoss;
    const tp = analysis.takeProfit;
    let exit = entry;
    let exitIdx = i;
    let hit = "breakeven";
    for (let j = i + 1; j < Math.min(i + 50, candles.length); j++) {
      const h = Number(candles[j].high);
      const l = Number(candles[j].low);
      if (direction === "buy") {
        if (l <= sl) {
          exit = sl;
          hit = "sl";
          exitIdx = j;
          break;
        }
        if (h >= tp) {
          exit = tp;
          hit = "tp";
          exitIdx = j;
          break;
        }
      } else {
        if (h >= sl) {
          exit = sl;
          hit = "sl";
          exitIdx = j;
          break;
        }
        if (l <= tp) {
          exit = tp;
          hit = "tp";
          exitIdx = j;
          break;
        }
      }
    }
    if (exitIdx === i) continue;
    const riskAmount = balance * 0.01;
    const slDistance = Math.abs(entry - sl);
    const pipsAtRisk = slDistance / profile.pip;
    const lots = pipsAtRisk > 0 ? riskAmount / (pipsAtRisk * profile.pip * profile.contractSize) : 0.01;
    const priceDiff = direction === "buy" ? exit - entry : entry - exit;
    const profit = priceDiff * profile.contractSize * lots;
    balance += profit;
    equity = balance;
    peak = Math.max(peak, equity);
    const dd = ((peak - equity) / peak) * 100;
    maxDD = Math.max(maxDD, dd);
    if (profit > 0) {
      wins++;
      totalWins += profit;
    } else if (profit < 0) {
      losses++;
      totalLosses += Math.abs(profit);
    }
    totalTrades++;
    if (totalTrades > 1) {
      dailyReturns.push(profit / initialBalance);
    }
    tradeLog.push({
      entry: entry.toFixed(5),
      exit: exit.toFixed(5),
      lots: lots.toFixed(2),
      profit: profit.toFixed(2),
      hit,
      score: analysis.score,
      quality: analysis.quality,
    });
  }
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;
  const profitFactor = totalLosses > 0 ? totalWins / totalLosses : totalWins > 0 ? 99 : 0;
  // Sharpe approximation
  const avgReturn = dailyReturns.length > 0 ? dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length : 0;
  const stdReturn =
    dailyReturns.length > 0
      ? Math.sqrt(dailyReturns.reduce((a, b) => a + (b - avgReturn) ** 2, 0) / dailyReturns.length)
      : 1;
  const sharpe = stdReturn > 0 ? (avgReturn / stdReturn) * Math.sqrt(252) : 0;
  const avgRR = 2.0; // target RR
  let rating = "C";
  if (winRate >= 60 && profitFactor >= 1.8 && maxDD < 15) rating = "A+";
  else if (winRate >= 55 && profitFactor >= 1.5 && maxDD < 20) rating = "A";
  else if (winRate >= 50 && profitFactor >= 1.2) rating = "B";
  const [saved] = await db
    .insert(backtests)
    .values({
      name: body.name || `${symbol} ${timeframe} backtest`,
      symbol,
      timeframe,
      startDate: new Date(candles[0].openTime),
      endDate: new Date(candles[candles.length - 1].openTime),
      initialBalance: String(initialBalance),
      finalBalance: String(balance),
      totalTrades,
      winningTrades: wins,
      losingTrades: losses,
      winRate: String(winRate.toFixed(2)),
      profitFactor: String(profitFactor.toFixed(2)),
      maxDrawdown: String(maxDD.toFixed(2)),
      sharpeRatio: String(sharpe.toFixed(2)),
      averageRR: String(avgRR.toFixed(2)),
      strategyRating: rating,
      results: { tradeLog: tradeLog.slice(-30), balance, equity },
    })
    .returning();
  return NextResponse.json({ backtest: saved });
}
