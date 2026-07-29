import { describe, it, expect } from "vitest";
import { buildExecutionPlan } from "@/lib/engine/execution";

function mkAccount(id: number, risk: string, opts: Partial<Record<string, unknown>> = {}) {
  return {
    id, name: `A${id}`, accountNumber: String(id), password: "x", server: "s",
    broker: "exness" as const, accountType: "standard" as const,
    status: "active" as const, tradingEnabled: true,
    connectionStatus: "connected" as const,
    balance: "10000", equity: "10000", margin: "0", freeMargin: "10000",
    riskPercent: risk, maxDailyLoss: "3", maxWeeklyLoss: "8", maxConsecutiveLosses: 3,
    isMaster: false, lastConnectedAt: null, lastSyncAt: null, sessionToken: null, userId: null,
    createdAt: new Date(), updatedAt: new Date(),
    ...opts,
  } as unknown as import("@/db/schema").TradingAccount;
}

const signal = {
  symbol: "EURUSD" as const,
  action: "buy" as const,
  entryPrice: "1.0850",
  stopLoss: "1.0800",
  takeProfit: "1.0950",
};

describe("multi-account execution (Feature 2) — risk separation", () => {
  it("same signal → different lot sizes per account risk %", () => {
    const plans = buildExecutionPlan(
      signal,
      [
        { account: mkAccount(1, "1.0"), openSymbols: [], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 },
        { account: mkAccount(2, "0.5"), openSymbols: [], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 },
        { account: mkAccount(3, "2.0"), openSymbols: [], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 },
      ],
      "paper",
    );
    const [a, b, c] = plans;
    expect(a.allowed).toBe(true);
    expect(b.allowed).toBe(true);
    expect(c.allowed).toBe(true);
    expect(b.lots).toBeCloseTo(a.lots / 2, 1);
    expect(c.lots).toBeCloseTo(a.lots * 2, 1);
    expect(b.riskAmount).toBeCloseTo(a.riskAmount / 2, 0); // $50 vs $100 at risk
    expect(c.riskAmount).toBeCloseTo(a.riskAmount * 2, 0);
  });

  it("blocks paused/error accounts while executing others", () => {
    const plans = buildExecutionPlan(
      signal,
      [
        { account: mkAccount(1, "1"), openSymbols: [], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 },
        { account: mkAccount(2, "1", { status: "paused" }), openSymbols: [], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 },
      ],
      "paper",
    );
    expect(plans[0].allowed).toBe(true);
    expect(plans[1].allowed).toBe(false);
    expect(plans[1].blockedReason).toMatch(/paused/i);
  });

  it("enforces correlation filter per account", () => {
    const plans = buildExecutionPlan(
      signal,
      [{ account: mkAccount(1, "1"), openSymbols: ["GBPUSD"], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 }],
      "paper",
    );
    expect(plans[0].allowed).toBe(false);
    expect(plans[0].blockedReason).toMatch(/GBPUSD/);
  });

  it("respects daily loss limit per account while leaving others free", () => {
    const plans = buildExecutionPlan(
      signal,
      [
        { account: mkAccount(1, "1"), openSymbols: [], dailyPnL: -400, weeklyPnL: -400, consecutiveLosses: 0 },
        { account: mkAccount(2, "1"), openSymbols: [], dailyPnL: 0, weeklyPnL: 0, consecutiveLosses: 0 },
      ],
      "paper",
    );
    expect(plans[0].allowed).toBe(false);
    expect(plans[1].allowed).toBe(true);
  });
});
