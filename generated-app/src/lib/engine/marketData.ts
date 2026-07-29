// Market data simulator — generates realistic OHLCV candles for paper trading / backtesting
// We use a deterministic random walk seeded by symbol/timeframe so the dashboard
// shows stable, reproducible data.

import { Candle } from "@/db/schema";

function hashString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h) % 1_000_000;
}

function mulberry32(a: number) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface SymbolProfile {
  basePrice: number;
  volatility: number; // % daily
  drift: number; // % per day
  pip: number;
  contractSize: number;
  category: "forex" | "commodity" | "crypto";
}

const PROFILES: Record<string, SymbolProfile> = {
  EURUSD: { basePrice: 1.085, volatility: 0.5, drift: 0.001, pip: 0.0001, contractSize: 100000, category: "forex" },
  GBPUSD: { basePrice: 1.265, volatility: 0.6, drift: 0.0005, pip: 0.0001, contractSize: 100000, category: "forex" },
  USDJPY: { basePrice: 155.4, volatility: 0.55, drift: 0.002, pip: 0.01, contractSize: 100000, category: "forex" },
  AUDUSD: { basePrice: 0.658, volatility: 0.6, drift: 0.0, pip: 0.0001, contractSize: 100000, category: "forex" },
  USDCAD: { basePrice: 1.365, volatility: 0.4, drift: 0.0, pip: 0.0001, contractSize: 100000, category: "forex" },
  USDCHF: { basePrice: 0.892, volatility: 0.45, drift: -0.001, pip: 0.0001, contractSize: 100000, category: "forex" },
  NZDUSD: { basePrice: 0.598, volatility: 0.55, drift: 0.0, pip: 0.0001, contractSize: 100000, category: "forex" },
  XAUUSD: { basePrice: 2340.0, volatility: 1.2, drift: 0.05, pip: 0.01, contractSize: 100, category: "commodity" },
  XAGUSD: { basePrice: 27.5, volatility: 1.8, drift: 0.01, pip: 0.01, contractSize: 5000, category: "commodity" },
  BTCUSD: { basePrice: 62500, volatility: 3.5, drift: 0.1, pip: 0.01, contractSize: 1, category: "crypto" },
  ETHUSD: { basePrice: 3300, volatility: 4.0, drift: 0.05, pip: 0.01, contractSize: 1, category: "crypto" },
  SOLUSD: { basePrice: 145, volatility: 5.5, drift: 0.08, pip: 0.01, contractSize: 1, category: "crypto" },
};

export function getProfile(symbol: string): SymbolProfile {
  return (
    PROFILES[symbol] || {
      basePrice: 100,
      volatility: 1.0,
      drift: 0,
      pip: 0.0001,
      contractSize: 100000,
      category: "forex",
    }
  );
}

export const SUPPORTED_SYMBOLS = Object.keys(PROFILES);

export function timeframeMinutes(tf: string): number {
  switch (tf) {
    case "M1":
      return 1;
    case "M5":
      return 5;
    case "M15":
      return 15;
    case "M30":
      return 30;
    case "H1":
      return 60;
    case "H4":
      return 240;
    case "D1":
      return 1440;
    default:
      return 60;
  }
}

export function generateCandles(
  symbol: string,
  timeframe: string,
  count: number,
  endTime: Date = new Date()
): Candle[] {
  const profile = getProfile(symbol);
  const seed = hashString(`${symbol}-${timeframe}`);
  const rand = mulberry32(seed);
  const tfMin = timeframeMinutes(timeframe);
  // Number of candles per day
  const candlesPerDay = (24 * 60) / tfMin;
  // Total span in days
  const totalDays = Math.max(1, Math.ceil(count / candlesPerDay));
  const driftPerCandle = profile.drift / 100 / candlesPerDay;
  const volPerCandle = profile.volatility / 100 / Math.sqrt(candlesPerDay);
  let price = profile.basePrice;
  // Work backwards from basePrice adding reverse drift
  // But we want a realistic walk — generate forward from past
  const start = new Date(endTime.getTime() - totalDays * 24 * 60 * 60 * 1000);
  const candles: Candle[] = [];
  let t = new Date(start);
  // Align to timeframe
  const alignMin = Math.floor(t.getMinutes() / tfMin) * tfMin;
  t.setMinutes(alignMin, 0, 0);
  for (let i = 0; i < count; i++) {
    const open = price;
    // Generate close with some mean reversion and drift
    const shock = (rand() - 0.5) * 2 * volPerCandle * price;
    const meanRev = (profile.basePrice - price) * 0.0005;
    const drift = driftPerCandle * price;
    const close = Math.max(0.0001, open + shock + drift + meanRev);
    const range = Math.abs(close - open) + volPerCandle * price * (0.3 + rand());
    const high = Math.max(open, close) + range * rand() * 0.5;
    const low = Math.min(open, close) - range * rand() * 0.5;
    // Volume roughly proportional to volatility
    const volume = Math.round(1000 + Math.abs(close - open) * 100000 * rand());
    candles.push({
      id: 0,
      symbol,
      timeframe,
      openTime: new Date(t),
      open: String(open),
      high: String(high),
      low: String(low),
      close: String(close),
      volume: String(volume),
    });
    price = close;
    t = new Date(t.getTime() + tfMin * 60 * 1000);
  }
  return candles;
}

export function generateTick(symbol: string, lastPrice?: number): number {
  const profile = getProfile(symbol);
  const seed = hashString(`${symbol}-tick`);
  const rand = mulberry32((seed + Date.now() / 1000) | 0);
  const base = lastPrice ?? profile.basePrice;
  const change = (rand() - 0.5) * 2 * (profile.volatility / 100) * base * 0.001;
  return base + change;
}
