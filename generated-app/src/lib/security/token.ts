// Session tokens — HMAC-SHA256 signed payloads (Web Crypto: works in Node 18+ and Edge middleware)
// Format: base64url(payload).base64url(sig)  payload = { uid, u, role, exp }
// Secret: process.env.SESSION_SECRET

export interface SessionPayload {
  uid: number;
  u: string;
  role: string;
  exp: number; // epoch ms
}

let warned = false;

function secret(): string {
  const s = process.env.SESSION_SECRET;
  if (!s && !warned) {
    warned = true;
    console.warn("[security] SESSION_SECRET not set — using development fallback secret. Set it in production.");
  }
  return s || "aaqts-dev-only-session-secret-change-me";
}

const encoder = new TextEncoder();

function b64url(bytes: Uint8Array | ArrayBuffer): string {
  const buf = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  let str = "";
  for (const b of buf) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function unb64url(s: string): Uint8Array {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function hmacKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", encoder.encode(secret()), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export const SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export async function signSessionToken(payload: Omit<SessionPayload, "exp">, ttlMs = SESSION_TTL_MS): Promise<{ token: string; payload: SessionPayload }> {
  const full: SessionPayload = { ...payload, exp: Date.now() + ttlMs };
  const body = b64url(encoder.encode(JSON.stringify(full)));
  const key = await hmacKey();
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  return { token: `${body}.${b64url(sig)}`, payload: full };
}

export async function verifySessionToken(token: string): Promise<SessionPayload | null> {
  const dot = token.lastIndexOf(".");
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  try {
    const key = await hmacKey();
    const ok = await crypto.subtle.verify("HMAC", key, unb64url(sig) as BufferSource, encoder.encode(body));
    if (!ok) return null;
    const payload = JSON.parse(new TextDecoder().decode(unb64url(body))) as SessionPayload;
    if (!payload.exp || payload.exp < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

export function sha256Hex(input: string): Promise<string> {
  return crypto.subtle.digest("SHA-256", encoder.encode(input)).then((d) => {
    const bytes = new Uint8Array(d);
    return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
  });
}
