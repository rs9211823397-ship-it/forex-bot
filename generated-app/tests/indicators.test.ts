import { describe, it, expect } from "vitest";
import { bollingerBands, ema, rsi, macd, atr, adx, supertrend, stochasticRsi } from "@/lib/engine/indicators";
import { generateCandles } from "@/lib/engine/marketData";
import { analyzeMarket } from "@/lib/engine/signalEngine";

function pri(n: number) {
  // random-walk series
  const out: number[] = [];
  let p = 100;
  for (let i = 0; i < n; i++) {
    p += (Math.random() - 0.5) * p * 0.002;
    out.push(p);
  }
  return out;
}

describe("indicator engines (regression — full-length outputs)", () => {
  const series = pri(250);

  it("bollingerBands returns 3 full-length arrays with NaN warmup", () => {
    const { upper, middle, lower } = bollingerBands(series, 20, 2);
    expect(upper.length).toBe(series.length);
    expect(middle.length).toBe(series.length);
    expect(lower.length).toBe(series.length);
    expect(Number.isNaN(middle[0])).toBe(true);
    expect(Number.isFinite(middle[series.length - 1])).toBe(true);
    expect(Number.isFinite(upper[series.length - 1])).toBe(true);
  });

  it("other indicators return full-length arrays", () => {
    expect(ema(series, 20).length).toBe(series.length);
    expect(rsi(series).length).toBe(series.length);
    expect(macd(series).macd.length).toBe(series.length);
    expect(atr(series.map((x) => x + 0.5), series.map((x) => x - 0.5), series).length).toBe(series.length);
    expect(adx(series.map((x) => x + 0.5), series.map((x) => x - 0.5), series).length).toBe(series.length);
    expect(supertrend(series.map((x) => x + 0.5), series.map((x) => x - 0.5), series).trend.length).toBe(series.length);
    expect(stochasticRsi(series).k.length).toBeGreaterThan(0);
  });

  it("analyzeMarket never throws and returns a decision the API can persist", () => {
    for (const sym of ["EURUSD", "XAUUSD", "BTCUSD", "USDJPY"]) {
      for (const tf of ["M15", "H1", "H4"]) {
        const candles = generateCandles(sym, tf, 250);
        const r = analyzeMarket(candles, sym);
        expect(["buy", "sell", "hold"]).toContain(r.action);
        expect(["A+", "A", "B", "C", "reject"]).toContain(r.quality);
        expect(r.indicators.price).toBeGreaterThan(0);
        // persisted fields must be finite
        for (const k of ["adx", "atr", "ema20", "ema50", "ema200", "rsi"]) {
          const v = r.indicators[k];
          expect(Number.isFinite(typeof v === "string" ? Number(v) : v)).toBe(true);
        }
      }
    }
  });
});
