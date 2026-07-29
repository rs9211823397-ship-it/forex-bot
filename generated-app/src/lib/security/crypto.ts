// Credential encryption — AES-256-GCM (Feature 4)
// Ciphertext format: enc:v1:<ivHex>:<tagHex>:<cipherHex>
// Key source: process.env.CREDENTIALS_ENCRYPTION_KEY (32-byte hex or any string, hashed to 32 bytes)
import { createHash, randomBytes, createCipheriv, createDecipheriv } from "node:crypto";

const PREFIX = "enc:v1:";
let warned = false;

function getKey(): Buffer {
  const raw = process.env.CREDENTIALS_ENCRYPTION_KEY;
  if (!raw && !warned) {
    warned = true;
    console.warn("[security] CREDENTIALS_ENCRYPTION_KEY not set — using development fallback key. Set it in production.");
  }
  const material = raw || "aaqts-dev-only-credential-key-do-not-use-in-prod";
  return createHash("sha256").update(material).digest();
}

export function isEncrypted(value: string | null | undefined): boolean {
  return !!value && value.startsWith(PREFIX);
}

export function encryptCredential(plaintext: string): string {
  const key = getKey();
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const enc = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${PREFIX}${iv.toString("hex")}:${tag.toString("hex")}:${enc.toString("hex")}`;
}

export function decryptCredential(ciphertext: string): string {
  if (!isEncrypted(ciphertext)) return ciphertext; // legacy plaintext passthrough
  const rest = ciphertext.slice(PREFIX.length);
  const [ivHex, tagHex, encHex] = rest.split(":");
  const key = getKey();
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(ivHex, "hex"));
  decipher.setAuthTag(Buffer.from(tagHex, "hex"));
  const dec = Buffer.concat([decipher.update(Buffer.from(encHex, "hex")), decipher.final()]);
  return dec.toString("utf8");
}

export function maskCredential(value: string | null | undefined): string {
  if (!value) return "";
  if (value.length <= 4) return "****";
  return `${"*".repeat(Math.max(4, value.length - 4))}${value.slice(-4)}`;
}
