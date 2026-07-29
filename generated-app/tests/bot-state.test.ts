import { describe, it, expect } from "vitest";
import { transition, canOpenOrder, BotStatus, BotCommand } from "@/lib/bot/state";

function run(status: BotStatus, cmd: BotCommand) {
  return transition(status, cmd);
}

describe("master bot state machine (Feature 1)", () => {
  it("START activates trading engine from STOPPED", () => {
    const r = run("STOPPED", "start");
    expect(r.ok).toBe(true);
    expect(r.next).toBe("RUNNING");
    expect(r.activity.signalGeneration).toBe(true);
    expect(r.activity.orderExecution).toBe(true);
    expect(r.activity.positionMonitoring).toBe(true);
  });

  it("STOP halts trading but keeps monitoring existing positions", () => {
    const r = run("RUNNING", "stop");
    expect(r.ok).toBe(true);
    expect(r.next).toBe("STOPPED");
    expect(r.activity.signalGeneration).toBe(false);
    expect(r.activity.orderExecution).toBe(false);
    expect(r.activity.positionMonitoring).toBe(true); // does NOT force-close
  });

  it("PAUSE blocks execution but keeps monitoring + signal generation", () => {
    const r = run("RUNNING", "pause");
    expect(r.ok).toBe(true);
    expect(r.next).toBe("PAUSED");
    expect(r.activity.signalGeneration).toBe(true); // continue monitoring markets
    expect(r.activity.orderExecution).toBe(false);   // pause execution
  });

  it("RESUME continues trading without restart", () => {
    expect(run("PAUSED", "resume").next).toBe("RUNNING");
    expect(run("PAUSED", "start").next).toBe("RUNNING");
  });

  it("EMERGENCY halts everything from any state", () => {
    for (const s of ["STOPPED", "RUNNING", "PAUSED", "EMERGENCY_STOP"] as BotStatus[]) {
      const r = run(s, "emergency");
      expect(r.ok).toBe(true);
      expect(r.next).toBe("EMERGENCY_STOP");
      expect(r.activity.orderExecution).toBe(false);
      expect(r.activity.signalGeneration).toBe(false);
    }
  });

  it("rejects invalid transitions", () => {
    expect(run("RUNNING", "start").ok).toBe(false);
    expect(run("STOPPED", "pause").ok).toBe(false);
    expect(run("STOPPED", "stop").ok).toBe(false);
    expect(run("PAUSED", "resume").ok).toBe(true);
    expect(run("EMERGENCY_STOP", "start").ok).toBe(false);
    expect(run("EMERGENCY_STOP", "resume").ok).toBe(false);
  });

  it("requires explicit RESET out of EMERGENCY_STOP", () => {
    const r = run("EMERGENCY_STOP", "reset");
    expect(r.ok).toBe(true);
    expect(r.next).toBe("STOPPED");
  });

  it("order gating matches state", () => {
    expect(canOpenOrder("RUNNING").allowed).toBe(true);
    expect(canOpenOrder("PAUSED").allowed).toBe(false);
    expect(canOpenOrder("STOPPED").allowed).toBe(false);
    const e = canOpenOrder("EMERGENCY_STOP");
    expect(e.allowed).toBe(false);
    expect(e.reason).toMatch(/EMERGENCY/);
  });
});
