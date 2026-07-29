// Bot controller — persists BOT_STATUS state machine in DB, records audit events (Features 1 & 6)

import { db } from "@/db";
import { botState, botSettings, executionEvents, trades } from "@/db/schema";
import { eq } from "drizzle-orm";
import { BotStatus, BotMode, BotCommand, transition, statusActivity, TransitionResult } from "./state";
import { getProfile } from "@/lib/engine/marketData";

export interface BotSnapshot {
  status: BotStatus;
  mode: BotMode;
  closeAllOnEmergency: boolean;
  updatedAt: string;
  updatedBy: string | null;
  openPositions: number;
  activity: ReturnType<typeof statusActivity>;
}

export async function getBotState(): Promise<BotSnapshot> {
  const [row] = await db.select().from(botState).orderBy(botState.id).limit(1);
  const state = row ?? (await db.insert(botState).values({}).returning())[0];
  const open = await db.select().from(trades).where(eq(trades.status, "open"));
  return {
    status: state.status,
    mode: state.mode,
    closeAllOnEmergency: state.closeAllOnEmergency,
    updatedAt: state.updatedAt.toISOString(),
    updatedBy: state.updatedBy,
    openPositions: open.length,
    activity: statusActivity(state.status),
  };
}

async function persist(status: BotStatus, mode: BotMode, updatedBy: string | null) {
  const [row] = await db.select().from(botState).orderBy(botState.id).limit(1);
  if (row) {
    await db.update(botState).set({ status, mode, updatedBy, updatedAt: new Date() }).where(eq(botState.id, row.id));
  } else {
    await db.insert(botState).values({ status, mode, updatedBy });
  }
}

async function audit(accountId: number | null, action: string, detail: Record<string, unknown>) {
  await db.insert(executionEvents).values({ accountId, action, detail });
}

export async function commandBot(
  command: BotCommand,
  opts: { mode?: BotMode; updatedBy?: string; closeOpenPositions?: boolean } = {}
): Promise<TransitionResult & { closedPositions?: number }> {
  const current = await getBotState();
  const result = transition(current.status, command);
  if (!result.ok) return result;
  const mode = opts.mode ?? current.mode;
  await persist(result.next, mode, opts.updatedBy ?? "system");
  await audit(null, `BOT_${command.toUpperCase()}`, { from: result.from, to: result.next, mode, reason: result.reason });

  let closedPositions = 0;
  // Emergency stop with user-confirmed close-all
  if (command === "emergency" && opts.closeOpenPositions) {
    closedPositions = await closeAllOpenPositions(mode, "emergency_stop");
  }
  return { ...result, closedPositions };
}

// Emergency close: close every open trade at current market price, credit account balance
export async function closeAllOpenPositions(mode: BotMode, reason: string): Promise<number> {
  const open = await db.select().from(trades).where(eq(trades.status, "open"));
  let count = 0;
  for (const t of open) {
    const profile = getProfile(t.symbol);
    const entry = Number(t.entryPrice);
    const lots = Number(t.lots);
    const exit = entry * (1 + (Math.random() - 0.5) * 0.004); // market simulation; live mode → MT5 bridge close
    const priceDiff = t.direction === "buy" ? exit - entry : entry - exit;
    const profit = priceDiff * profile.contractSize * lots;
    const pips = priceDiff / profile.pip;
    await db
      .update(trades)
      .set({ status: "closed", exitPrice: String(exit), profit: String(profit), pips: String(pips), closedAt: new Date(), reason })
      .where(eq(trades.id, t.id));
    const { tradingAccounts } = await import("@/db/schema");
    const [acc] = await db.select().from(tradingAccounts).where(eq(tradingAccounts.id, t.accountId));
    if (acc) {
      const nb = Number(acc.balance) + profit;
      await db.update(tradingAccounts).set({ balance: String(nb), equity: String(nb), updatedAt: new Date() }).where(eq(tradingAccounts.id, acc.id));
    }
    await audit(t.accountId, "ORDER_CLOSE", { tradeId: t.id, symbol: t.symbol, profit, reason, mode });
    count++;
  }
  return count;
}

export async function getBotSettings() {
  const [row] = await db.select().from(botSettings).orderBy(botSettings.id).limit(1);
  if (row) return row;
  const [created] = await db.insert(botSettings).values({}).returning();
  return created;
}

export async function updateBotSettings(patch: Partial<Record<string, number | boolean>>) {
  const existing = await getBotSettings();
  const update: Record<string, unknown> = { updatedAt: new Date() };
  if (patch.defaultRiskPercent !== undefined) update.defaultRiskPercent = String(patch.defaultRiskPercent);
  if (patch.maxDailyLossPercent !== undefined) update.maxDailyLossPercent = String(patch.maxDailyLossPercent);
  if (patch.maxWeeklyLossPercent !== undefined) update.maxWeeklyLossPercent = String(patch.maxWeeklyLossPercent);
  if (patch.maxConsecutiveLosses !== undefined) update.maxConsecutiveLosses = patch.maxConsecutiveLosses;
  if (patch.correlationFilter !== undefined) update.correlationFilter = patch.correlationFilter;
  if (patch.newsBlackout !== undefined) update.newsBlackout = patch.newsBlackout;
  if (patch.emaFast !== undefined) update.emaFast = patch.emaFast;
  if (patch.emaMid !== undefined) update.emaMid = patch.emaMid;
  if (patch.emaSlow !== undefined) update.emaSlow = patch.emaSlow;
  if (patch.rsiPeriod !== undefined) update.rsiPeriod = patch.rsiPeriod;
  if (patch.atrMultiplier !== undefined) update.atrMultiplier = String(patch.atrMultiplier);
  if (patch.rrTarget !== undefined) update.rrTarget = String(patch.rrTarget);
  const [updated] = await db.update(botSettings).set(update).where(eq(botSettings.id, existing.id)).returning();
  return updated;
}
