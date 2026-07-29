import { describe, it, expect, beforeAll } from "vitest";

process.env.MT5_BRIDGE_MODE = "simulated";

let bridge: import("@/lib/mt5/bridge").IMt5Bridge;
beforeAll(async () => {
  const mod = await import("@/lib/mt5/bridge");
  bridge = mod.createMt5Bridge();
});

describe("MT5 bridge — Exness connectivity (Feature 3)", () => {
  it("simulated connect reports latency + company metadata", async () => {
    const r = await bridge.connect({ login: "21184723", password: "secure-pass-1", server: "Exness-MT5Trial6" });
    expect(r.connected).toBe(true);
    expect(r.sessionToken).toBeTruthy();
    expect(r.latencyMs!).toBeGreaterThan(0);
    expect(r.company).toMatch(/Exness/);
  });

  it("rejects bad passwords as AUTH_FAILED (connection monitoring)", async () => {
    const r = await bridge.connect({ login: "21184723", password: "x", server: "Exness-MT5Trial6" });
    expect(r.connected).toBe(false);
    expect(r.error).toBe("AUTH_FAILED");
  });

  it("rejects malformed login ids", async () => {
    const r = await bridge.connect({ login: "notanumber", password: "secure-pass-1", server: "Exness-MT5Trial6" });
    expect(r.connected).toBe(false);
  });
});

describe("MT5 bridge — order lifecycle", () => {
  it("BUY order fills with ticket + entry; STOP LOSS / TAKE PROFIT stored", async () => {
    const r = await bridge.placeOrder({
      symbol: "EURUSD", direction: "buy", lots: 0.5, entryPrice: 1.0850, stopLoss: 1.0800, takeProfit: 1.0950,
    });
    expect(r.success).toBe(true);
    expect(r.ticket).toBeTruthy();
    expect(r.fillPrice).toBeGreaterThan(0);
    const positions = await bridge.getPositions();
    const pos = positions.find((p) => p.ticket === r.ticket);
    expect(pos).toBeDefined();
    expect(pos!.stopLoss).toBe(1.0800);
    expect(pos!.takeProfit).toBe(1.0950);
  });

  it("SELL order works", async () => {
    const r = await bridge.placeOrder({ symbol: "XAUUSD", direction: "sell", lots: 0.1 });
    expect(r.success).toBe(true);
  });

  it("rejects invalid lots", async () => {
    const r = await bridge.placeOrder({ symbol: "EURUSD", direction: "buy", lots: -1 });
    expect(r.success).toBe(false);
  });

  it("modifyOrder updates SL/TP on open position", async () => {
    const open = await bridge.placeOrder({ symbol: "EURUSD", direction: "buy", lots: 0.1 });
    const mod = await bridge.modifyOrder(open.ticket!, 1.0500, 1.1500);
    expect(mod.success).toBe(true);
    const positions = await bridge.getPositions();
    const pos = positions.find((p) => p.ticket === open.ticket);
    expect(pos?.stopLoss).toBe(1.0500);
    expect(pos?.takeProfit).toBe(1.1500);
  });

  it("closeOrder realizes PnL and moves position to history", async () => {
    const open = await bridge.placeOrder({ symbol: "EURUSD", direction: "buy", lots: 0.2, entryPrice: 1.0850 });
    const close = await bridge.closeOrder(open.ticket!, 100);
    expect(close.success).toBe(true);
    expect(typeof close.profit).toBe("number");
    const positions = await bridge.getPositions();
    expect(positions.find((p) => p.ticket === open.ticket)).toBeUndefined();
    const history = await bridge.getHistory();
    expect(history.some((p) => p.ticket === open.ticket)).toBe(true);
  });

  it("partial close keeps remaining position open", async () => {
    const open = await bridge.placeOrder({ symbol: "EURUSD", direction: "buy", lots: 1.0, entryPrice: 1.0850 });
    const close = await bridge.closeOrder(open.ticket!, 50);
    expect(close.success).toBe(true);
    const positions = await bridge.getPositions();
    const pos = positions.find((p) => p.ticket === open.ticket);
    expect(pos).toBeDefined();
    expect(pos!.lots).toBeLessThan(1.0);
    expect(pos!.lots).toBeGreaterThan(0);
  });

  it("positions report live unrealized PnL", async () => {
    const open = await bridge.placeOrder({ symbol: "EURUSD", direction: "buy", lots: 0.5, entryPrice: 1.0850 });
    await bridge.modifyOrder(open.ticket!, 0, 0);
    const positions = await bridge.getPositions();
    const pos = positions.find((p) => p.ticket === open.ticket);
    expect(typeof pos!.unrealizedPnl).toBe("number");
  });
});
