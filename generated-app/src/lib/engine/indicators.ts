// Technical Indicators Library
// Pure functions that operate on numeric arrays

export function ema(values: number[], period: number): number[] {
  if (values.length === 0) return [];
  const k = 2 / (period + 1);
  const out: number[] = [];
  let prev = values[0];
  out.push(prev);
  for (let i = 1; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

export function sma(values: number[], period: number): number[] {
  if (values.length < period) return [];
  const out: number[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out.push(sum / period);
  }
  return out;
}

export function rsi(values: number[], period = 14): number[] {
  if (values.length < period + 1) return [];
  const out: number[] = new Array(values.length).fill(NaN);
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const diff = values[i] - values[i - 1];
    if (diff > 0) gain += diff;
    else loss -= diff;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  out[period] = 100 - 100 / (1 + (avgLoss === 0 ? 100 : avgGain / avgLoss));
  for (let i = period + 1; i < values.length; i++) {
    const diff = values[i] - values[i - 1];
    const g = diff > 0 ? diff : 0;
    const l = diff < 0 ? -diff : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    out[i] = 100 - 100 / (1 + rs);
  }
  return out;
}

export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signal = 9
): { macd: number[]; signal: number[]; histogram: number[] } {
  const fastEma = ema(values, fast);
  const slowEma = ema(values, slow);
  const macdLine = values.map((_, i) => fastEma[i] - slowEma[i]);
  const signalLine = ema(macdLine, signal);
  const histogram = macdLine.map((v, i) => v - signalLine[i]);
  return { macd: macdLine, signal: signalLine, histogram };
}

export function atr(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14
): number[] {
  if (highs.length < period + 1) return [];
  const trs: number[] = [];
  for (let i = 1; i < highs.length; i++) {
    const tr = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
    trs.push(tr);
  }
  const out: number[] = new Array(closes.length).fill(NaN);
  // First ATR = SMA
  let sum = 0;
  for (let i = 0; i < period; i++) sum += trs[i];
  out[period] = sum / period;
  for (let i = period; i < trs.length; i++) {
    out[i + 1] = (out[i] * (period - 1) + trs[i]) / period;
  }
  return out;
}

export function adx(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14
): number[] {
  if (highs.length < period * 2) return [];
  const plusDM: number[] = [];
  const minusDM: number[] = [];
  const trs: number[] = [];
  for (let i = 1; i < highs.length; i++) {
    const up = highs[i] - highs[i - 1];
    const down = lows[i - 1] - lows[i];
    plusDM.push(up > down && up > 0 ? up : 0);
    minusDM.push(down > up && down > 0 ? down : 0);
    const tr = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1])
    );
    trs.push(tr);
  }
  const out: number[] = new Array(closes.length).fill(NaN);
  // Smooth with Wilder
  let sTR = trs.slice(0, period).reduce((a, b) => a + b, 0);
  let sPlus = plusDM.slice(0, period).reduce((a, b) => a + b, 0);
  let sMinus = minusDM.slice(0, period).reduce((a, b) => a + b, 0);
  for (let i = period; i < trs.length; i++) {
    sTR = sTR - sTR / period + trs[i];
    sPlus = sPlus - sPlus / period + plusDM[i];
    sMinus = sMinus - sMinus / period + minusDM[i];
    const plusDI = (sPlus / sTR) * 100;
    const minusDI = (sMinus / sTR) * 100;
    const dx = (Math.abs(plusDI - minusDI) / (plusDI + minusDI)) * 100;
    if (i === period) out[i + 1] = dx;
    else out[i + 1] = (out[i] * (period - 1) + dx) / period;
  }
  return out;
}

export function bollingerBands(
  values: number[],
  period = 20,
  stdDev = 2
): { upper: number[]; middle: number[]; lower: number[] } {
  const smaValues = sma(values, period); // length = values.length - period + 1
  // Pad middle to full length so callers can index by original position
  const middle: number[] = new Array(values.length).fill(NaN);
  for (let k = 0; k < smaValues.length; k++) middle[period - 1 + k] = smaValues[k];
  const upper: number[] = [];
  const lower: number[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      upper.push(NaN);
      lower.push(NaN);
    } else {
      const mean = middle[i];
      const slice = values.slice(i - period + 1, i + 1);
      const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
      const std = Math.sqrt(variance);
      upper.push(mean + stdDev * std);
      lower.push(mean - stdDev * std);
    }
  }
  return { upper, middle, lower };
}

export function stochasticRsi(
  values: number[],
  rsiPeriod = 14,
  stochPeriod = 14,
  smoothK = 3,
  smoothD = 3
): { k: number[]; d: number[] } {
  const r = rsi(values, rsiPeriod);
  const kRaw: number[] = new Array(values.length).fill(NaN);
  for (let i = stochPeriod - 1; i < r.length; i++) {
    if (isNaN(r[i])) continue;
    const slice = r.slice(i - stochPeriod + 1, i + 1).filter((v) => !isNaN(v));
    if (slice.length === 0) continue;
    const min = Math.min(...slice);
    const max = Math.max(...slice);
    if (max - min === 0) kRaw[i] = 50;
    else kRaw[i] = ((r[i] - min) / (max - min)) * 100;
  }
  const k = sma(kRaw.map((v) => (isNaN(v) ? 0 : v)), smoothK);
  const d = sma(k.map((v) => (isNaN(v) ? 0 : v)), smoothD);
  return { k, d };
}

export function obv(closes: number[], volumes: number[]): number[] {
  const out: number[] = [0];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i] > closes[i - 1]) out.push(out[i - 1] + volumes[i]);
    else if (closes[i] < closes[i - 1]) out.push(out[i - 1] - volumes[i]);
    else out.push(out[i - 1]);
  }
  return out;
}

export function supertrend(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 10,
  multiplier = 3
): { trend: number[]; direction: ("up" | "down")[] } {
  const atrVals = atr(highs, lows, closes, period);
  const trend: number[] = new Array(closes.length).fill(NaN);
  const direction: ("up" | "down")[] = new Array(closes.length).fill("up");
  let prevTrend = NaN;
  for (let i = period; i < closes.length; i++) {
    const hl2 = (highs[i] + lows[i]) / 2;
    const upper = hl2 + multiplier * atrVals[i];
    const lower = hl2 - multiplier * atrVals[i];
    if (i === period) {
      trend[i] = closes[i] > hl2 ? lower : upper;
      direction[i] = closes[i] > hl2 ? "up" : "down";
    } else {
      const finalLower = lower > trend[i - 1] || closes[i - 1] < trend[i - 1] ? lower : trend[i - 1];
      const finalUpper = upper < trend[i - 1] || closes[i - 1] > trend[i - 1] ? upper : trend[i - 1];
      if (closes[i] > finalUpper) {
        trend[i] = finalLower;
        direction[i] = "up";
      } else if (closes[i] < finalLower) {
        trend[i] = finalUpper;
        direction[i] = "down";
      } else {
        trend[i] = prevTrend;
        direction[i] = direction[i - 1];
      }
    }
    prevTrend = trend[i];
  }
  return { trend, direction };
}

// Market structure helpers
export function detectStructure(
  highs: number[],
  lows: number[]
): { hh: boolean; hl: boolean; lh: boolean; ll: boolean } {
  const lookback = Math.min(20, Math.floor(highs.length / 4));
  const recentHighs = highs.slice(-lookback);
  const recentLows = lows.slice(-lookback);
  if (recentHighs.length < 4) {
    return { hh: false, hl: false, lh: false, ll: false };
  }
  const h1 = Math.max(...recentHighs.slice(0, Math.floor(recentHighs.length / 2)));
  const h2 = Math.max(...recentHighs.slice(Math.floor(recentHighs.length / 2)));
  const l1 = Math.min(...recentLows.slice(0, Math.floor(recentLows.length / 2)));
  const l2 = Math.min(...recentLows.slice(Math.floor(recentLows.length / 2)));
  return {
    hh: h2 > h1,
    hl: l2 > l1 && h2 > h1,
    lh: h2 < h1,
    ll: l2 < l1,
  };
}

// Detect Break of Structure
export function detectBOS(
  highs: number[],
  lows: number[]
): "bullish" | "bearish" | null {
  if (highs.length < 5) return null;
  const prevHigh = Math.max(...highs.slice(-10, -2));
  const prevLow = Math.min(...lows.slice(-10, -2));
  const last = highs[highs.length - 1];
  const lastL = lows[lows.length - 1];
  if (last > prevHigh) return "bullish";
  if (lastL < prevLow) return "bearish";
  return null;
}

// Change of Character
export function detectCHoCH(
  highs: number[],
  lows: number[]
): "bullish" | "bearish" | null {
  if (highs.length < 10) return null;
  const look = Math.min(20, Math.floor(highs.length / 2));
  const firstHigh = Math.max(...highs.slice(0, look));
  const secondHigh = Math.max(...highs.slice(look));
  const firstLow = Math.min(...lows.slice(0, look));
  const secondLow = Math.min(...lows.slice(look));
  // Was making higher highs/lows, now lower
  if (firstHigh > secondHigh && firstLow > secondLow) return "bearish";
  if (firstHigh < secondHigh && firstLow < secondLow) return "bullish";
  return null;
}

// Candle patterns
export function detectCandlePattern(
  opens: number[],
  highs: number[],
  lows: number[],
  closes: number[]
): string | null {
  const n = closes.length;
  if (n < 3) return null;
  const o = opens[n - 1];
  const h = highs[n - 1];
  const l = lows[n - 1];
  const c = closes[n - 1];
  const po = opens[n - 2];
  const pc = closes[n - 2];
  const body = Math.abs(c - o);
  const range = h - l || 0.00001;
  const upperWick = h - Math.max(o, c);
  const lowerWick = Math.min(o, c) - l;
  // Bullish engulfing
  if (pc < po && c > o && c > po && o < pc) return "bullish_engulfing";
  // Bearish engulfing
  if (pc > po && c < o && c < po && o > pc) return "bearish_engulfing";
  // Hammer
  if (lowerWick > body * 2 && upperWick < body * 0.5 && c > o) return "hammer";
  // Shooting star
  if (upperWick > body * 2 && lowerWick < body * 0.5 && c < o) return "shooting_star";
  // Morning star (3-candle)
  if (n >= 3) {
    const ppClose = closes[n - 3];
    const ppOpen = opens[n - 3];
    const midClose = closes[n - 2];
    const midOpen = opens[n - 2];
    if (ppClose < ppOpen && Math.abs(midClose - midOpen) < Math.abs(ppClose - ppOpen) * 0.3 && c > o && c > (ppOpen + ppClose) / 2) {
      return "morning_star";
    }
  }
  return null;
}
