import { describe, it, expect } from "vitest";

process.env.CREDENTIALS_ENCRYPTION_KEY = process.env.CREDENTIALS_ENCRYPTION_KEY || "test-credential-key-32bytes-aaaaaaaa";
const { encryptCredential, decryptCredential, isEncrypted } = await import("@/lib/security/crypto");

describe("credential encryption (AES-256-GCM)", () => {
  it("round-trips arbitrary secrets", () => {
    const samples = ["password123", "❇ unicode πässword ❇", "a".repeat(512), "Exness#MT5!"] as const;
    for (const s of samples) {
      const enc = encryptCredential(s);
      expect(enc.startsWith("enc:v1:")).toBe(true);
      expect(enc).not.toContain(s);
      expect(decryptCredential(enc)).toBe(s);
    }
  });

  it("produces unique ciphertexts for the same plaintext (random IV)", () => {
    const a = encryptCredential("same");
    const b = encryptCredential("same");
    expect(a).not.toBe(b);
    expect(decryptCredential(a)).toBe("same");
    expect(decryptCredential(b)).toBe("same");
  });

  it("detects encrypted values and passes legacy plaintext through", () => {
    expect(isEncrypted(encryptCredential("x"))).toBe(true);
    expect(isEncrypted("plaintext")).toBe(false);
    expect(isEncrypted(null)).toBe(false);
    expect(decryptCredential("legacy-plain")).toBe("legacy-plain");
  });

  it("rejects tampered ciphertext", () => {
    const enc = encryptCredential("secret");
    const tampered = enc.slice(0, -2) + "ff";
    expect(() => decryptCredential(tampered)).toThrow();
  });
});
