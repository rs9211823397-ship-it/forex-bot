// Signal Engine — produces BUY / SELL / HOLD with confidence, score, reasons
// Combines EMA, Supertrend, ADX, RSI, MACD, StochRSI, OBV, ATR, structure, candle patterns

import {
  ema,
  rsi,
  macd,
  atr,
  adx,
  stochasticRsi,
  obv,
  supertrend,
  detectStructure,
  detectBOS,
  detectCHoCH,
  detectCandlePattern,
  bollingerBands,
} from "./indicators";
import { Candle } from "@/db/schema";

export interface SignalResult {
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
  structure?: {
    bos: "bullish" | "bearish" | null;
    choch: "bullish" | "bearish" | null;
    pattern: string | null;
    marketStructure: { hh: boolean; hl: boolean; lh: boolean; ll: boolean };
  };
}

export interface AnalysisResult extends SignalResult {
  candles: number;
}

function toNums(c: Candle[], key: "open" | "high" | "low" | "close" | "volume"): number[] {
  return c.map((x) => Number(x[key]));
}

export function analyzeMarket(
  candles: Candle[],
  symbol: string
): AnalysisResult {
  if (candles.length < 60) {
    return {
      action: "hold",
      quality: "reject",
      confidence: 0,
      score: 0,
      reasons: ["Insufficient data (need 60+ candles)"],
      indicators: {},
      regime: "ranging",
      volatility: "low",
      recommendation: "WAIT",
      riskReward: 0,
      candles: candles.length,
    };
  }

  const opens = toNums(candles, "open");
  const highs = toNums(candles, "high");
  const lows = toNums(candles, "low");
  const closes = toNums(candles, "close");
  const volumes = toNums(candles, "volume");

  const i = closes.length - 1;
  const price = closes[i];

  // Compute indicators
  const ema20 = ema(closes, 20);
  const ema50 = ema(closes, 50);
  const ema200 = ema(closes, 200);
  const rsiArr = rsi(closes, 14);
  const macdRes = macd(closes, 12, 26, 9);
  const stoch = stochasticRsi(closes);
  const adxArr = adx(highs, lows, closes, 14);
  const atrArr = atr(highs, lows, closes, 14);
  const obvArr = obv(closes, volumes);
  const superRes = supertrend(highs, lows, closes, 10, 3);
  const bb = bollingerBands(closes, 20, 2);
  const structure = detectStructure(highs, lows);
  const bos = detectBOS(highs, lows);
  const choch = detectCHoCH(highs, lows);
  const pattern = detectCandlePattern(opens, highs, lows, closes);

  const lastOf = (arr: number[] | undefined, fallback = NaN): number => {
    if (!arr || arr.length === 0) return fallback;
    for (let k = arr.length - 1; k >= 0; k--) {
      if (Number.isFinite(arr[k])) return arr[k];
    }
    return fallback;
  };
  const lastEma20 = lastOf(ema20, closes[i]);
  const lastEma50 = lastOf(ema50, closes[i]);
  const lastEma200 = lastOf(ema200, lastEma50);
  const lastRsi = lastOf(rsiArr, 50);
  const lastMacd = lastOf(macdRes.macd, 0);
  const lastMacdSig = lastOf(macdRes.signal, 0);
  const lastHist = lastOf(macdRes.histogram, 0);
  const prevHist = macdRes.histogram.length > 1 ? macdRes.histogram[macdRes.histogram.length - 2] || 0 : 0;
  // stochK/D arrays are SMA-shortened — take their tail
  const lastK = lastOf(stoch.k, 50);
  const lastD = lastOf(stoch.d, 50);
  const lastAdx = adxArr[i];
  const lastAtr = atrArr[i];
  const lastSuperDir = superRes.direction[i];
  const lastObv = obvArr[i];
  const prevObv = obvArr[i - 5] || 0;
  const lastBBUpper = bb.upper[i];
  const lastBBLower = bb.lower[i];
  const lastBBMid = bb.middle[i];

  const indicators: Record<string, number> = {
    ema20: Number(lastEma20.toFixed(5)),
    ema50: Number(lastEma50.toFixed(5)),
    ema200: Number(lastEma200.toFixed(5)),
    rsi: Number(lastRsi.toFixed(2)),
    macd: Number(lastMacd.toFixed(5)),
    macdSignal: Number(lastMacdSig.toFixed(5)),
    macdHist: Number(lastHist.toFixed(5)),
    stochK: Number(lastK.toFixed(2)),
    stochD: Number(lastD.toFixed(2)),
    adx: Number((lastAdx || 0).toFixed(2)),
    atr: Number(lastAtr.toFixed(5)),
    supertrend: lastSuperDir === "up" ? 1 : -1,
    obv: Number(lastObv.toFixed(0)),
    obvSlope: Number((lastObv - prevObv).toFixed(0)),
    bbUpper: Number(lastBBUpper.toFixed(5)),
    bbLower: Number(lastBBLower.toFixed(5)),
    price: Number(price.toFixed(5)),
  };

  // --- Market Regime (Phase 4) ---
  let regime: "trending" | "ranging" | "volatile" | "low_volatility" = "ranging";
  let volatility: "low" | "normal" | "high" = "normal";
  if ((lastAdx || 0) > 25) regime = "trending";
  else regime = "ranging";
  // Volatility based on ATR relative to price
  const atrPct = (lastAtr / price) * 100;
  if (atrPct > 1.2) volatility = "high";
  else if (atrPct < 0.3) volatility = "low";
  else volatility = "normal";
  if (volatility === "high" && regime === "ranging") regime = "volatile";
  if (volatility === "low" && regime === "ranging") regime = "low_volatility";

  // --- Scoring ---
  const reasons: string[] = [];
  let bullScore = 0;
  let bearScore = 0;
  const maxScore = 100;

  // Trend
  if (lastEma20 > lastEma50 && lastEma50 > lastEma200) {
    bullScore += 15;
    reasons.push("✓ EMA alignment bullish (20>50>200)");
  } else if (lastEma20 < lastEma50 && lastEma50 < lastEma200) {
    bearScore += 15;
    reasons.push("✗ EMA alignment bearish (20<50<200)");
  } else {
    reasons.push("• EMA alignment mixed");
  }

  // Supertrend
  if (lastSuperDir === "up") {
    bullScore += 12;
    reasons.push("✓ Supertrend green (uptrend)");
  } else {
    bearScore += 12;
    reasons.push("✗ Supertrend red (downtrend)");
  }

  // ADX strength
  if ((lastAdx || 0) > 25) {
    if (lastSuperDir === "up") {
      bullScore += 8;
      reasons.push(`✓ Strong trend (ADX ${(lastAdx || 0).toFixed(1)})`);
    } else {
      bearScore += 8;
      reasons.push(`✗ Strong trend (ADX ${(lastAdx || 0).toFixed(1)})`);
    }
  } else {
    reasons.push(`• Weak trend (ADX ${(lastAdx || 0).toFixed(1)})`);
  }

  // RSI
  if (lastRsi >= 55 && lastRsi <= 70) {
    bullScore += 10;
    reasons.push(`✓ RSI momentum (${lastRsi.toFixed(1)})`);
  } else if (lastRsi < 30) {
    bearScore += 8;
    reasons.push(`✗ RSI oversold (${lastRsi.toFixed(1)})`);
  } else if (lastRsi > 70) {
    bearScore += 6;
    reasons.push(`• RSI overbought (${lastRsi.toFixed(1)})`);
  } else if (lastRsi <= 45 && lastRsi >= 30) {
    bearScore += 10;
    reasons.push(`✗ RSI momentum (${lastRsi.toFixed(1)})`);
  } else {
    reasons.push(`• RSI neutral (${lastRsi.toFixed(1)})`);
  }

  // MACD
  if (lastMacd > lastMacdSig && lastHist > prevHist) {
    bullScore += 10;
    reasons.push("✓ MACD bullish crossover + rising");
  } else if (lastMacd < lastMacdSig && lastHist < prevHist) {
    bearScore += 10;
    reasons.push("✗ MACD bearish crossover + falling");
  } else {
    reasons.push("• MACD neutral");
  }

  // StochRSI
  if (lastK > lastD && lastK < 80 && lastK > 20) {
    bullScore += 6;
    reasons.push(`✓ StochRSI bullish cross (K ${lastK.toFixed(0)})`);
  } else if (lastK < lastD && lastK > 20 && lastK < 80) {
    bearScore += 6;
    reasons.push(`✗ StochRSI bearish cross (K ${lastK.toFixed(0)})`);
  }

  // OBV
  if (lastObv > prevObv) {
    bullScore += 6;
    reasons.push("✓ OBV rising (accumulation)");
  } else if (lastObv < prevObv) {
    bearScore += 6;
    reasons.push("✗ OBV falling (distribution)");
  }

  // Volume
  const volSmaSlice = volumes.slice(-20);
  const volSma = volSmaSlice.reduce((a, b) => a + b, 0) / volSmaSlice.length;
  if (volumes[i] > volSma) {
    if (bullScore > bearScore) bullScore += 4;
    else bearScore += 4;
    reasons.push("✓ Above-average volume");
  }

  // Market structure
  if (structure.hh && structure.hl) {
    bullScore += 8;
    reasons.push("✓ Structure: Higher Highs + Higher Lows");
  } else if (structure.lh && structure.ll) {
    bearScore += 8;
    reasons.push("✗ Structure: Lower Highs + Lower Lows");
  }

  // BOS
  if (bos === "bullish") {
    bullScore += 6;
    reasons.push("✓ Bullish Break of Structure");
  } else if (bos === "bearish") {
    bearScore += 6;
    reasons.push("✗ Bearish Break of Structure");
  }

  // CHoCH
  if (choch === "bullish") {
    bullScore += 5;
    reasons.push("✓ Bullish Change of Character");
  } else if (choch === "bearish") {
    bearScore += 5;
    reasons.push("✗ Bearish Change of Character");
  }

  // Candle pattern
  if (pattern === "bullish_engulfing" || pattern === "hammer" || pattern === "morning_star") {
    bullScore += 5;
    reasons.push(`✓ Bullish candle pattern: ${pattern.replace("_", " ")}`);
  } else if (pattern === "bearish_engulfing" || pattern === "shooting_star") {
    bearScore += 5;
    reasons.push(`✗ Bearish candle pattern: ${pattern.replace("_", " ")}`);
  }

  // Bollinger squeeze / breakout
  const bbWidth = lastBBUpper - lastBBLower;
  const bbMidToPrice = Math.abs(price - lastBBMid) / lastBBMid;
  if (bbMidToPrice > 0.005 && price > lastBBMid) {
    bullScore += 3;
    reasons.push("✓ Price above BB middle");
  } else if (bbMidToPrice > 0.005 && price < lastBBMid) {
    bearScore += 3;
    reasons.push("✗ Price below BB middle");
  }

  // --- Final decision ---
  let action: "buy" | "sell" | "hold" = "hold";
  let score = Math.max(bullScore, bearScore);
  if (bullScore >= 50 && bullScore > bearScore + 8) action = "buy";
  else if (bearScore >= 50 && bearScore > bullScore + 8) action = "sell";

  // AI Quality filter (Phase 7)
  let quality: "A+" | "A" | "B" | "C" | "reject" = "reject";
  if (action === "hold") {
    quality = "reject";
  } else if (score >= 75) {
    quality = "A+";
  } else if (score >= 60) {
    quality = "A";
  } else if (score >= 50) {
    quality = "B";
  } else if (score >= 40) {
    quality = "C";
  } else {
    quality = "reject";
  }

  // AI confidence
  let confidence = Math.min(100, Math.max(0, score));
  // Boost if structure + trend agree
  if (
    (action === "buy" && structure.hh && structure.hl && bos === "bullish") ||
    (action === "sell" && structure.lh && structure.ll && bos === "bearish")
  ) {
    confidence = Math.min(100, confidence + 8);
    reasons.push("✓ AI: Confluence across multiple timeframes");
  }
  // Penalize if regime mismatch
  if (regime === "ranging" && action !== "hold") {
    confidence = Math.max(0, confidence - 15);
    reasons.push("⚠ AI: Ranging market — reduce confidence");
  }
  if (regime === "low_volatility") {
    confidence = Math.max(0, confidence - 20);
    reasons.push("⚠ AI: Low volatility — avoid trading");
  }
  if (quality === "reject") {
    action = "hold";
  }

  // Recommendation
  let recommendation = "WAIT";
  if (action === "buy" && (quality === "A+" || quality === "A")) recommendation = "STRONG BUY";
  else if (action === "buy") recommendation = "BUY";
  else if (action === "sell" && (quality === "A+" || quality === "A")) recommendation = "STRONG SELL";
  else if (action === "sell") recommendation = "SELL";

  // SL / TP based on ATR
  const atrMult = 1.5;
  const tpMult = 3.0; // 1:2 RR
  let entryPrice: number | undefined;
  let stopLoss: number | undefined;
  let takeProfit: number | undefined;
  const riskReward = 2.0;
  if (action === "buy") {
    entryPrice = price;
    stopLoss = price - lastAtr * atrMult;
    takeProfit = price + lastAtr * tpMult;
  } else if (action === "sell") {
    entryPrice = price;
    stopLoss = price + lastAtr * atrMult;
    takeProfit = price - lastAtr * tpMult;
  }

  return {
    action,
    quality,
    confidence: Math.round(confidence * 100) / 100,
    score: Math.round(score),
    reasons,
    indicators,
    regime,
    volatility,
    recommendation,
    entryPrice,
    stopLoss,
    takeProfit,
    riskReward,
    structure: { bos, choch, pattern, marketStructure: structure },
    candles: candles.length,
  };
}
