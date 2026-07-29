import {
  pgTable,
  serial,
  text,
  integer,
  numeric,
  boolean,
  timestamp,
  jsonb,
  pgEnum,
  index,
} from "drizzle-orm/pg-core";
import { relations } from "drizzle-orm";

// =============== Enums ===============
export const accountStatusEnum = pgEnum("account_status", [
  "active",
  "paused",
  "stopped",
  "error",
]);

export const brokerEnum = pgEnum("broker", [
  "exness",
  "ic_markets",
  "pepperstone",
  "mt5_demo",
  "other",
]);

export const accountTypeEnum = pgEnum("account_type", [
  "standard",
  "raw_spread",
  "pro",
  "demo",
]);

export const tradeDirectionEnum = pgEnum("trade_direction", [
  "buy",
  "sell",
]);

export const tradeStatusEnum = pgEnum("trade_status", [
  "open",
  "closed",
  "cancelled",
]);

export const tradeModeEnum = pgEnum("trade_mode", [
  "paper",
  "live",
  "backtest",
]);

export const marketRegimeEnum = pgEnum("market_regime", [
  "trending",
  "ranging",
  "volatile",
  "low_volatility",
]);

export const signalActionEnum = pgEnum("signal_action", [
  "buy",
  "sell",
  "hold",
]);

export const signalQualityEnum = pgEnum("signal_quality", [
  "A+",
  "A",
  "B",
  "C",
  "reject",
]);

export const volatilityEnum = pgEnum("volatility", [
  "low",
  "normal",
  "high",
]);

export const botStatusEnum = pgEnum("bot_status", [
  "STOPPED",
  "RUNNING",
  "PAUSED",
  "EMERGENCY_STOP",
]);

export const botModeEnum = pgEnum("bot_mode", ["paper", "live"]);

export const connectionStatusEnum = pgEnum("connection_status", [
  "not_configured",
  "disconnected",
  "connected",
  "auth_failed",
]);

// =============== Users & Sessions (Feature 4/6) ===============
export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  username: text("username").notNull().unique(),
  passwordHash: text("password_hash").notNull(),
  role: text("role").notNull().default("admin"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  lastLoginAt: timestamp("last_login_at", { withTimezone: true }),
});

export const sessions = pgTable(
  "sessions",
  {
    id: serial("id").primaryKey(),
    tokenHash: text("token_hash").notNull().unique(),
    userId: integer("user_id").notNull(),
    userAgent: text("user_agent"),
    ip: text("ip"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
  },
  (t) => ({
    userIdx: index("sessions_user_idx").on(t.userId),
  }),
);

// =============== Bot State & Settings (Feature 1) ===============
export const botState = pgTable("bot_state", {
  id: serial("id").primaryKey(),
  status: botStatusEnum("status").notNull().default("STOPPED"),
  mode: botModeEnum("mode").notNull().default("paper"),
  closeAllOnEmergency: boolean("close_all_on_emergency").notNull().default(true),
  updatedBy: text("updated_by"),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const botSettings = pgTable("bot_settings", {
  id: serial("id").primaryKey(),
  defaultRiskPercent: numeric("default_risk_percent", { precision: 5, scale: 2 }).notNull().default("1"),
  maxDailyLossPercent: numeric("max_daily_loss_percent", { precision: 5, scale: 2 }).notNull().default("3"),
  maxWeeklyLossPercent: numeric("max_weekly_loss_percent", { precision: 5, scale: 2 }).notNull().default("8"),
  maxConsecutiveLosses: integer("max_consecutive_losses").notNull().default(3),
  correlationFilter: boolean("correlation_filter").notNull().default(true),
  newsBlackout: boolean("news_blackout").notNull().default(true),
  emaFast: integer("ema_fast").notNull().default(20),
  emaMid: integer("ema_mid").notNull().default(50),
  emaSlow: integer("ema_slow").notNull().default(200),
  rsiPeriod: integer("rsi_period").notNull().default(14),
  atrMultiplier: numeric("atr_multiplier", { precision: 5, scale: 2 }).notNull().default("1.5"),
  rrTarget: numeric("rr_target", { precision: 5, scale: 2 }).notNull().default("2"),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

// =============== Trading Accounts (Feature 2/3) ===============
export const tradingAccounts = pgTable("trading_accounts", {
  id: serial("id").primaryKey(),
  userId: integer("user_id"),
  name: text("name").notNull(),
  accountNumber: text("account_number").notNull(),
  password: text("password").notNull(), // enc:v1 AES-256-GCM ciphertext
  server: text("server").notNull(),
  broker: brokerEnum("broker").notNull().default("exness"),
  accountType: accountTypeEnum("account_type").notNull().default("standard"),
  status: accountStatusEnum("status").notNull().default("active"),
  tradingEnabled: boolean("trading_enabled").notNull().default(true),
  connectionStatus: connectionStatusEnum("connection_status").notNull().default("not_configured"),
  sessionToken: text("session_token"),
  lastConnectedAt: timestamp("last_connected_at", { withTimezone: true }),
  balance: numeric("balance", { precision: 18, scale: 2 }).notNull().default("10000"),
  equity: numeric("equity", { precision: 18, scale: 2 }).notNull().default("10000"),
  margin: numeric("margin", { precision: 18, scale: 2 }).notNull().default("0"),
  freeMargin: numeric("free_margin", { precision: 18, scale: 2 }).notNull().default("10000"),
  riskPercent: numeric("risk_percent", { precision: 5, scale: 2 }).notNull().default("1.0"),
  maxDailyLoss: numeric("max_daily_loss", { precision: 5, scale: 2 }).notNull().default("3.0"),
  maxWeeklyLoss: numeric("max_weekly_loss", { precision: 5, scale: 2 }).notNull().default("8.0"),
  maxConsecutiveLosses: integer("max_consecutive_losses").notNull().default(3),
  isMaster: boolean("is_master").notNull().default(false),
  lastSyncAt: timestamp("last_sync_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

// =============== Symbols (Market catalog) ===============
export const symbols = pgTable("symbols", {
  id: serial("id").primaryKey(),
  ticker: text("ticker").notNull().unique(),
  name: text("name").notNull(),
  category: text("category").notNull(),
  pipValue: numeric("pip_value", { precision: 10, scale: 6 }).notNull().default("0.0001"),
  contractSize: numeric("contract_size", { precision: 18, scale: 4 }).notNull().default("100000"),
  minLot: numeric("min_lot", { precision: 10, scale: 4 }).notNull().default("0.01"),
  maxLot: numeric("max_lot", { precision: 10, scale: 4 }).notNull().default("100"),
  enabled: boolean("enabled").notNull().default(true),
});

// =============== Candles / Market Data ===============
export const candles = pgTable(
  "candles",
  {
    id: serial("id").primaryKey(),
    symbol: text("symbol").notNull(),
    timeframe: text("timeframe").notNull(),
    openTime: timestamp("open_time", { withTimezone: true }).notNull(),
    open: numeric("open", { precision: 18, scale: 8 }).notNull(),
    high: numeric("high", { precision: 18, scale: 8 }).notNull(),
    low: numeric("low", { precision: 18, scale: 8 }).notNull(),
    close: numeric("close", { precision: 18, scale: 8 }).notNull(),
    volume: numeric("volume", { precision: 18, scale: 2 }).notNull().default("0"),
  },
  (t) => ({
    symTfTimeIdx: index("candles_sym_tf_time_idx").on(t.symbol, t.timeframe, t.openTime),
  }),
);

// =============== Signals ===============
export const signals = pgTable(
  "signals",
  {
    id: serial("id").primaryKey(),
    symbol: text("symbol").notNull(),
    timeframe: text("timeframe").notNull(),
    action: signalActionEnum("action").notNull(),
    quality: signalQualityEnum("quality").notNull().default("B"),
    confidence: numeric("confidence", { precision: 5, scale: 2 }).notNull(),
    score: integer("score").notNull(),
    entryPrice: numeric("entry_price", { precision: 18, scale: 8 }),
    stopLoss: numeric("stop_loss", { precision: 18, scale: 8 }),
    takeProfit: numeric("take_profit", { precision: 18, scale: 8 }),
    riskReward: numeric("risk_reward", { precision: 5, scale: 2 }).notNull().default("2"),
    regime: marketRegimeEnum("regime"),
    volatility: volatilityEnum("volatility"),
    reasons: jsonb("reasons").$type<string[]>().notNull().default([]),
    indicators: jsonb("indicators").$type<Record<string, number>>().notNull().default({}),
    executed: boolean("executed").notNull().default(false),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => ({
    symCreatedIdx: index("signals_sym_created_idx").on(t.symbol, t.createdAt),
  }),
);

// =============== Trades ===============
export const trades = pgTable(
  "trades",
  {
    id: serial("id").primaryKey(),
    accountId: integer("account_id").notNull(),
    signalId: integer("signal_id"),
    mt5Ticket: text("mt5_ticket"),
    symbol: text("symbol").notNull(),
    direction: tradeDirectionEnum("direction").notNull(),
    mode: tradeModeEnum("mode").notNull().default("paper"),
    status: tradeStatusEnum("status").notNull().default("open"),
    lots: numeric("lots", { precision: 10, scale: 4 }).notNull(),
    entryPrice: numeric("entry_price", { precision: 18, scale: 8 }).notNull(),
    stopLoss: numeric("stop_loss", { precision: 18, scale: 8 }),
    takeProfit: numeric("take_profit", { precision: 18, scale: 8 }),
    exitPrice: numeric("exit_price", { precision: 18, scale: 8 }),
    profit: numeric("profit", { precision: 18, scale: 2 }).notNull().default("0"),
    pips: numeric("pips", { precision: 10, scale: 2 }).notNull().default("0"),
    confidence: numeric("confidence", { precision: 5, scale: 2 }),
    quality: text("quality"),
    reason: text("reason"),
    openedAt: timestamp("opened_at", { withTimezone: true }).notNull().defaultNow(),
    closedAt: timestamp("closed_at", { withTimezone: true }),
  },
  (t) => ({
    accountIdx: index("trades_account_idx").on(t.accountId),
    statusIdx: index("trades_status_idx").on(t.status),
    openedIdx: index("trades_opened_idx").on(t.openedAt),
  }),
);

// =============== Market Regime Snapshots ===============
export const regimeSnapshots = pgTable(
  "regime_snapshots",
  {
    id: serial("id").primaryKey(),
    symbol: text("symbol").notNull(),
    timeframe: text("timeframe").notNull(),
    regime: marketRegimeEnum("regime").notNull(),
    volatility: volatilityEnum("volatility").notNull(),
    adx: numeric("adx", { precision: 8, scale: 2 }),
    atr: numeric("atr", { precision: 18, scale: 8 }),
    ema20: numeric("ema20", { precision: 18, scale: 8 }),
    ema50: numeric("ema50", { precision: 18, scale: 8 }),
    ema200: numeric("ema200", { precision: 18, scale: 8 }),
    rsi: numeric("rsi", { precision: 8, scale: 2 }),
    recommendation: text("recommendation").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => ({
    symCreatedIdx: index("regime_sym_created_idx").on(t.symbol, t.createdAt),
  }),
);

// =============== Backtests ===============
export const backtests = pgTable("backtests", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  symbol: text("symbol").notNull(),
  timeframe: text("timeframe").notNull(),
  startDate: timestamp("start_date", { withTimezone: true }).notNull(),
  endDate: timestamp("end_date", { withTimezone: true }).notNull(),
  initialBalance: numeric("initial_balance", { precision: 18, scale: 2 }).notNull(),
  finalBalance: numeric("final_balance", { precision: 18, scale: 2 }).notNull(),
  totalTrades: integer("total_trades").notNull().default(0),
  winningTrades: integer("winning_trades").notNull().default(0),
  losingTrades: integer("losing_trades").notNull().default(0),
  winRate: numeric("win_rate", { precision: 5, scale: 2 }).notNull().default("0"),
  profitFactor: numeric("profit_factor", { precision: 8, scale: 2 }).notNull().default("0"),
  maxDrawdown: numeric("max_drawdown", { precision: 5, scale: 2 }).notNull().default("0"),
  sharpeRatio: numeric("sharpe_ratio", { precision: 8, scale: 2 }).notNull().default("0"),
  averageRR: numeric("average_rr", { precision: 5, scale: 2 }).notNull().default("0"),
  strategyRating: text("strategy_rating").notNull().default("C"),
  results: jsonb("results").$type<Record<string, unknown>>().notNull().default({}),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

// =============== AI Learning ===============
export const aiDecisions = pgTable(
  "ai_decisions",
  {
    id: serial("id").primaryKey(),
    signalId: integer("signal_id"),
    symbol: text("symbol").notNull(),
    action: text("action").notNull(),
    quality: text("quality").notNull(),
    confidence: numeric("confidence", { precision: 5, scale: 2 }).notNull(),
    regime: text("regime"),
    outcome: text("outcome"),
    reward: numeric("reward", { precision: 8, scale: 4 }),
    features: jsonb("features").$type<Record<string, number>>().notNull().default({}),
    notes: text("notes"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => ({
    createdIdx: index("ai_decisions_created_idx").on(t.createdAt),
  }),
);

// =============== MT5 Connection Events (Feature 3) ===============
export const mt5Events = pgTable(
  "mt5_events",
  {
    id: serial("id").primaryKey(),
    accountId: integer("account_id"),
    event: text("event").notNull(), // CONNECT / DISCONNECT / AUTH_FAILED / ORDER_OPEN / ORDER_MODIFY / ORDER_CLOSE / BOT_*
    detail: jsonb("detail").$type<Record<string, unknown>>().notNull().default({}),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => ({
    accountIdx: index("mt5_events_account_idx").on(t.accountId),
  }),
);

// =============== Execution Audit Log (Feature 6) ===============
export const executionEvents = pgTable(
  "execution_events",
  {
    id: serial("id").primaryKey(),
    accountId: integer("account_id"),
    tradeId: integer("trade_id"),
    action: text("action").notNull(),
    latencyMs: integer("latency_ms"),
    detail: jsonb("detail").$type<Record<string, unknown>>().notNull().default({}),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => ({
    accountIdx: index("exec_events_account_idx").on(t.accountId),
  }),
);

// =============== System State ===============
export const systemState = pgTable("system_state", {
  id: serial("id").primaryKey(),
  key: text("key").notNull().unique(),
  value: jsonb("value").$type<unknown>().notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

// =============== Relations ===============
export const tradingAccountsRelations = relations(tradingAccounts, ({ many }) => ({
  trades: many(trades),
}));

export const tradesRelations = relations(trades, ({ one }) => ({
  account: one(tradingAccounts, {
    fields: [trades.accountId],
    references: [tradingAccounts.id],
  }),
}));

export type TradingAccount = typeof tradingAccounts.$inferSelect;
export type NewTradingAccount = typeof tradingAccounts.$inferInsert;
export type Symbol = typeof symbols.$inferSelect;
export type Candle = typeof candles.$inferSelect;
export type Signal = typeof signals.$inferSelect;
export type NewSignal = typeof signals.$inferInsert;
export type Trade = typeof trades.$inferSelect;
export type NewTrade = typeof trades.$inferInsert;
export type RegimeSnapshot = typeof regimeSnapshots.$inferSelect;
export type Backtest = typeof backtests.$inferSelect;
export type AiDecision = typeof aiDecisions.$inferSelect;
export type User = typeof users.$inferSelect;
export type BotState = typeof botState.$inferSelect;
export type BotSettings = typeof botSettings.$inferSelect;
export type Mt5Event = typeof mt5Events.$inferSelect;
export type ExecutionEvent = typeof executionEvents.$inferSelect;
