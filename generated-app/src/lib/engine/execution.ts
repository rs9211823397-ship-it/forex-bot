// Execution manager — distributes a master signal across multiple accounts with per-account risk scaling
// Used by both paper and live mode (live would integrate with MetaTrader5 Python API)

import { TradingAccount, NewTrade, Signal } from "@/db/schema";
import { calcPositionSize, isCorrelated, checkRiskLimits } from "./risk";
import { getProfile } from "./marketData";

export interface ExecutionPlan {
  accountId: number;
  accountName: string;
  allowed: boolean;
  blockedReason?: string;
  lots: number;
  riskAmount: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  mode: "paper" | "live";
}

export interface AccountRuntime {
  account: TradingAccount;
  openSymbols: string[];
  dailyPnL: number;
  weeklyPnL: number;
  consecutiveLosses: number;
}

export function buildExecutionPlan(
  signal: Pick<Signal, "action" | "entryPrice" | "stopLoss" | "takeProfit" | "symbol">,
  accountRuntimes: AccountRuntime[],
  mode: "paper" | "live" = "paper"
): ExecutionPlan[] {
  const plans: ExecutionPlan[] = [];
  for (const rt of accountRuntimes) {
    const a = rt.account;
    if (a.status !== "active") {
      plans.push({
        accountId: a.id,
        accountName: a.name,
        allowed: false,
        blockedReason: `Account status: ${a.status}`,
        lots: 0,
        riskAmount: 0,
        entryPrice: 0,
        stopLoss: 0,
        takeProfit: 0,
        mode,
      });
      continue;
    }
    // Correlation check
    const correlated = rt.openSymbols.find((s) => isCorrelated(s, signal.symbol, signal.action as "buy" | "sell"));
    if (correlated) {
      plans.push({
        accountId: a.id,
        accountName: a.name,
        allowed: false,
        blockedReason: `Correlated open: ${correlated}`,
        lots: 0,
        riskAmount: 0,
        entryPrice: 0,
        stopLoss: 0,
        takeProfit: 0,
        mode,
      });
      continue;
    }
    // Risk limits
    const balance = Number(a.balance);
    const dailyPnL = rt.dailyPnL;
    const weeklyPnL = rt.weeklyPnL;
    const risk = checkRiskLimits({
      balance,
      equity: Number(a.equity),
      riskPercent: Number(a.riskPercent),
      maxDailyLoss: Number(a.maxDailyLoss),
      maxWeeklyLoss: Number(a.maxWeeklyLoss),
      maxConsecutiveLosses: a.maxConsecutiveLosses,
      dailyPnL,
      weeklyPnL,
      consecutiveLosses: rt.consecutiveLosses,
    });
    if (!risk.allowed) {
      plans.push({
        accountId: a.id,
        accountName: a.name,
        allowed: false,
        blockedReason: risk.reason,
        lots: 0,
        riskAmount: 0,
        entryPrice: 0,
        stopLoss: 0,
        takeProfit: 0,
        mode,
      });
      continue;
    }
    // Compute position size
    const profile = getProfile(signal.symbol);
    const lots = calcPositionSize({
      balance,
      riskPercent: Number(a.riskPercent),
      entryPrice: Number(signal.entryPrice ?? 0),
      stopLoss: Number(signal.stopLoss ?? 0),
      pipValue: profile.pip,
      contractSize: Number(profile.contractSize),
      minLot: 0.01,
      maxLot: 100,
    });
    const riskAmount = (balance * Number(a.riskPercent)) / 100;
    plans.push({
      accountId: a.id,
      accountName: a.name,
      allowed: true,
      lots,
      riskAmount: Math.round(riskAmount * 100) / 100,
      entryPrice: Number(signal.entryPrice ?? 0),
      stopLoss: Number(signal.stopLoss ?? 0),
      takeProfit: Number(signal.takeProfit ?? 0),
      mode,
    });
  }
  return plans;
}

export function buildTradeFromPlan(plan: ExecutionPlan, signalId: number, symbol: string, direction: "buy" | "sell"): NewTrade {
  return {
    accountId: plan.accountId,
    signalId,
    symbol,
    direction,
    mode: plan.mode,
    status: "open",
    lots: String(plan.lots),
    entryPrice: String(plan.entryPrice),
    stopLoss: plan.stopLoss ? String(plan.stopLoss) : null,
    takeProfit: plan.takeProfit ? String(plan.takeProfit) : null,
    profit: "0",
    pips: "0",
    openedAt: new Date(),
  };
}
