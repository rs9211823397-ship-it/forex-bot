import { describe, it, expect } from "vitest";
import { hashPassword, verifyPassword } from "@/lib/security/passwords";

describe("operator password hashing (scrypt)", () => {
  it("verifies correct passwords", async () => {
    const hash = await hashPassword("super-secure-pass");
    expect(hash.startsWith("scrypt$")).toBe(true);
    expect(await verifyPassword("super-secure-pass", hash)).toBe(true);
  });

  it("rejects wrong passwords", async () => {
    const hash = await hashPassword("right");
    expect(await verifyPassword("wrong", hash)).toBe(false);
    expect(await verifyPassword("Right", hash)).toBe(false);
    expect(await verifyPassword("", hash)).toBe(false);
  });

  it("uses random salt — same password hashes differ", async () => {
    const a = await hashPassword("same");
    const b = await hashPassword("same");
    expect(a).not.toBe(b);
    expect(await verifyPassword("same", a)).toBe(true);
    expect(await verifyPassword("same", b)).toBe(true);
  });

  it("handles malformed records safely", async () => {
    expect(await verifyPassword("x", "not-a-hash")).toBe(false);
    expect(await verifyPassword("x", "bcrypt$abc$def")).toBe(false);
  });
});
