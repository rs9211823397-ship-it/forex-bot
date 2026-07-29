// Pure bot state machine (Feature 1) — unit-testable without DB

export type BotStatus = "STOPPED" | "RUNNING" | "PAUSED" | "EMERGENCY_STOP";
export type BotMode = "paper" | "live";
export type BotCommand = "start" | "pause" | "resume" | "stop" | "emergency" | "reset";

export interface TransitionResult {
  ok: boolean;
  from: BotStatus;
  next: BotStatus;
  reason?: string;
  activity: {
    signalGeneration: boolean;
    orderExecution: boolean;
    positionMonitoring: boolean;
  };
}

const ACTIVITY: Record<BotStatus, TransitionResult["activity"]> = {
  RUNNING: { signalGeneration: true, orderExecution: true, positionMonitoring: true },
  PAUSED: { signalGeneration: true, orderExecution: false, positionMonitoring: true },
  STOPPED: { signalGeneration: false, orderExecution: false, positionMonitoring: true },
  EMERGENCY_STOP: { signalGeneration: false, orderExecution: false, positionMonitoring: true },
};

export function statusActivity(status: BotStatus) {
  return ACTIVITY[status];
}

export function transition(status: BotStatus, command: BotCommand): TransitionResult {
  const fail = (reason: string): TransitionResult => ({
    ok: false, from: status, next: status, reason, activity: ACTIVITY[status],
  });
  const ok = (next: BotStatus, reason?: string): TransitionResult => ({
    ok: true, from: status, next, reason, activity: ACTIVITY[next],
  });
  switch (command) {
    case "start":
      if (status === "STOPPED") return ok("RUNNING", "Engine started");
      if (status === "PAUSED") return ok("RUNNING", "Resumed from pause");
      if (status === "EMERGENCY_STOP") return fail("Emergency stop active — issue RESET first");
      return fail("Already running");
    case "resume":
      if (status === "PAUSED") return ok("RUNNING", "Resumed");
      return fail("Not paused");
    case "pause":
      if (status === "RUNNING") return ok("PAUSED", "Paused — monitoring continues, new trades blocked");
      return fail("Pause requires RUNNING state");
    case "stop":
      if (status === "RUNNING" || status === "PAUSED") return ok("STOPPED", "Stopped — open positions keep monitoring");
      if (status === "EMERGENCY_STOP") return fail("Emergency stop active — issue RESET first");
      return fail("Already stopped");
    case "emergency":
      return ok("EMERGENCY_STOP", "EMERGENCY — all trading activity halted");
    case "reset":
      if (status === "EMERGENCY_STOP") return ok("STOPPED", "Emergency state reset");
      return fail("Reset applies only to EMERGENCY_STOP");
    default:
      return fail("Unknown command");
  }
}

// Whether an order may be opened in this state
export function canOpenOrder(status: BotStatus, opts: { manualOperatorTrade?: boolean } = {}): { allowed: boolean; reason?: string } {
  if (status === "RUNNING") return { allowed: true };
  if (status === "PAUSED" && opts.manualOperatorTrade) return { allowed: false, reason: "Bot paused — new trade execution blocked" };
  if (status === "PAUSED") return { allowed: false, reason: "Bot paused" };
  if (status === "EMERGENCY_STOP") return { allowed: false, reason: "EMERGENCY_STOP active — all trading blocked until RESET" };
  return { allowed: false, reason: "Bot stopped" };
}
