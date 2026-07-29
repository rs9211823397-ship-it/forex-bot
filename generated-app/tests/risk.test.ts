import { describe, it, expect } from "vitest";
import { calcPositionSize, checkRiskLimits, isCorrelated } from "@/lib/engine/risk";

describe("position sizing (Phase 1.5 / Feature 2)", () => {
  const base = {
    balance: 10000,
    entryPrice: 1.0850,
    stopLoss: 1.0800,
    pipValue: 0.0001,
    contractSize: 100000,
    minLot: 0.01,
    maxLot: 100,
  };

  it("scales lots with account risk percent — different accounts, different size", () => {
    const one = calcPositionSize({ ...base, riskPercent: 1 });
    const half = calcPositionSize({ ...base, riskPercent: 0.5 });
    const two = calcPositionSize({ ...base, riskPercent: 2 });
    expect(two).toBeCloseTo(one * 2, 1);
    expect(half).toBeCloseTo(one / 2, 1);
  });

  it("scales lots with balance", () => {
    const small = calcPositionSize({ ...base, balance: 1000, riskPercent: 1 });
    const big = calcPositionSize({ ...base, balance: 10000, riskPercent: 1 });
    expect(big).toBeCloseTo(small * 10, 0);
  });

  it("respects min/max lot bounds", () => {
    expect(calcPositionSize({ ...base, riskPercent: 0.001 })).toBe(0.01);
    // 50% risk → $5000 / $500-lot-value = 10 lots (still below max)
    expect(calcPositionSize({ ...base, riskPercent: 50 })).toBe(10);
    // Astronomical risk clamps to maxLot
    expect(calcPositionSize({ ...base, balance: 100_000_000, riskPercent: 50 })).toBe(100);
  });
});

describe("risk limits (Feature 8)", () => {
  const state = {
    balance: 10000, equity: 10000, riskPercent: 1,
    maxDailyLoss: 3, maxWeeklyLoss: 8, maxConsecutiveLosses: 3,
    dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0,
  };

  it("allows trading with clean state", () => {
    expect(checkRiskLimits(state).allowed).toBe(true);
  });

  it("blocks after daily loss breach (-3%)", () => {
    const r = checkRiskLimits({ ...state, dailyPnL: -320 });
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/Daily/i);
  });

  it("blocks after weekly drawdown breach (-8%)", () => {
    const r = checkRiskLimits({ ...state, weeklyPnL: -900 });
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/Weekly/i);
  });

  it("blocks after consecutive losses (3)", () => {
    const r = checkRiskLimits({ ...state, consecutiveLosses: 3 });
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/Consecutive/i);
  });
});

describe("correlation filter", () => {
  it("flags USD-negative majors as correlated", () => {
    expect(isCorrelated("EURUSD", "GBPUSD", "buy")).toBe(true);
    expect(isCorrelated("EURUSD", "AUDUSD", "buy")).toBe(true);
    expect(isCorrelated("XAUUSD", "XAGUSD", "buy")).toBe(true);
    expect(isCorrelated("BTCUSD", "ETHUSD", "buy")).toBe(true);
  });
  it("does not flag uncorrelated pairs", () => {
    expect(isCorrelated("EURUSD", "USDJPY", "buy")).toBe(false);
    expect(isCorrelated("EURUSD", "BTCUSD", "buy")).toBe(false);
    expect(isCorrelated("EURUSD", "EURUSD", "buy")).toBe(false); // same symbol isn't a correlation clash
  });
});
