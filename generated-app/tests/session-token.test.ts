import { describe, it, expect } from "vitest";

process.env.SESSION_SECRET = process.env.SESSION_SECRET || "test-session-secret";
const { signSessionToken, verifySessionToken, sha256Hex } = await import("@/lib/security/token");

describe("session tokens (HMAC-SHA256)", () => {
  it("signs and verifies mobile/API tokens", async () => {
    const { token } = await signSessionToken({ uid: 1, u: "admin", role: "admin" });
    const payload = await verifySessionToken(token);
    expect(payload).not.toBeNull();
    expect(payload!.uid).toBe(1);
    expect(payload!.u).toBe("admin");
  });

  it("rejects tampered tokens", async () => {
    const { token } = await signSessionToken({ uid: 1, u: "admin", role: "admin" });
    const [body, sig] = token.split(".");
    expect(await verifySessionToken(`${body}.${sig.split("").reverse().join("")}`)).toBeNull();
    const forged = `${Buffer.from(JSON.stringify({ uid: 99, u: "hacker", role: "admin", exp: Date.now() + 99999 })).toString("base64")}.${sig}`;
    expect(await verifySessionToken(forged)).toBeNull();
  });

  it("rejects expired tokens", async () => {
    const { token } = await signSessionToken({ uid: 1, u: "admin", role: "admin" }, -1000);
    expect(await verifySessionToken(token)).toBeNull();
  });

  it("hashes tokens deterministically for DB reconciliation", async () => {
    expect(await sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});
