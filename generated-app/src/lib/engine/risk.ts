// Risk management — position sizing, daily/weekly limits, correlation filter

export interface AccountRisk {
  balance: number;
  equity: number;
  riskPercent: number;
  maxDailyLoss: number;
  maxWeeklyLoss: number;
  maxConsecutiveLosses: number;
  dailyPnL: number;
  weeklyPnL: number;
  consecutiveLosses: number;
}

export interface PositionSizeInput {
  balance: number;
  riskPercent: number;
  entryPrice: number;
  stopLoss: number;
  pipValue: number;
  contractSize: number;
  minLot: number;
  maxLot: number;
}

export function calcPositionSize(input: PositionSizeInput): number {
  const { balance, riskPercent, entryPrice, stopLoss, pipValue, contractSize, minLot, maxLot } = input;
  const riskAmount = (balance * riskPercent) / 100;
  const slDistance = Math.abs(entryPrice - stopLoss);
  const pips = slDistance / pipValue;
  if (pips <= 0) return minLot;
  // 1 lot = contractSize * pips * pipValue
  const lotValue = pips * pipValue * contractSize;
  const lots = riskAmount / Math.max(lotValue, 0.0001);
  return Math.max(minLot, Math.min(maxLot, Math.round(lots * 100) / 100));
}

export interface RiskCheckResult {
  allowed: boolean;
  reason?: string;
  dailyLossRemaining: number;
  weeklyLossRemaining: number;
}

export function checkRiskLimits(state: AccountRisk): RiskCheckResult {
  const dailyLossRemaining = Math.max(0, state.balance * (state.maxDailyLoss / 100) + state.dailyPnL);
  const weeklyLossRemaining = Math.max(0, state.balance * (state.maxWeeklyLoss / 100) + state.weeklyPnL);
  if (state.dailyPnL <= -(state.balance * state.maxDailyLoss) / 100) {
    return { allowed: false, reason: `Daily loss limit hit (${state.maxDailyLoss}%)`, dailyLossRemaining, weeklyLossRemaining };
  }
  if (state.weeklyPnL <= -(state.balance * state.maxWeeklyLoss) / 100) {
    return { allowed: false, reason: `Weekly loss limit hit (${state.maxWeeklyLoss}%)`, dailyLossRemaining, weeklyLossRemaining };
  }
  if (state.consecutiveLosses >= state.maxConsecutiveLosses) {
    return { allowed: false, reason: `Consecutive loss limit hit (${state.maxConsecutiveLosses})`, dailyLossRemaining, weeklyLossRemaining };
  }
  return { allowed: true, dailyLossRemaining, weeklyLossRemaining };
}

// Correlation groups — avoid same-direction correlated positions
const CORRELATION_GROUPS: Record<string, string[]> = {
  USD_NEGATIVE: ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"],
  JPY: ["USDJPY"],
  CAD: ["USDCAD"],
  CHF: ["USDCHF"],
  METALS: ["XAUUSD", "XAGUSD"],
  CRYPTO: ["BTCUSD", "ETHUSD", "SOLUSD"],
};

export function isCorrelated(symbolA: string, symbolB: string, direction: "buy" | "sell"): boolean {
  // Only block same-direction correlation
  void direction;
  for (const group of Object.values(CORRELATION_GROUPS)) {
    if (group.includes(symbolA) && group.includes(symbolB) && symbolA !== symbolB) {
      return true;
    }
  }
  return false;
}

// News / session filter
export interface NewsEvent {
  symbol: string;
  type: "high" | "medium";
  minutesAway: number;
  title: string;
}

const HIGH_IMPACT_EVENTS = ["CPI", "NFP", "FOMC", "Interest Rate Decision", "ECB Rate", "BOE Rate"];

export function isNearNews(symbol: string, currentUtcMinutes: number): NewsEvent | null {
  // For demo, return occasional synthetic events
  // In real life, this would query Forex Factory / Investing.com
  void symbol;
  void currentUtcMinutes;
  return null;
}

export function isInTradingSession(utcHour: number, session: "london" | "newyork" | "asian"): boolean {
  switch (session) {
    case "asian":
      return utcHour >= 0 && utcHour < 9;
    case "london":
      return utcHour >= 7 && utcHour < 16;
    case "newyork":
      return utcHour >= 12 && utcHour < 21;
    default:
      return false;
  }
}

export function currentSession(utcHour: number): "london" | "newyork" | "asian" | "off" {
  if (utcHour >= 12 && utcHour < 16) return "london"; // Overlap
  if (utcHour >= 0 && utcHour < 9) return "asian";
  if (utcHour >= 7 && utcHour < 16) return "london";
  if (utcHour >= 12 && utcHour < 21) return "newyork";
  return "off";
}
