// Password hashing for application users — scrypt + per-user salt (Feature 4/7)
import { scrypt, randomBytes, timingSafeEqual } from "node:crypto";

export function hashPassword(password: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const salt = randomBytes(16).toString("hex");
    scrypt(password, salt, 64, (err, derived) => {
      if (err) return reject(err);
      resolve(`scrypt$${salt}$${derived.toString("hex")}`);
    });
  });
}

export function verifyPassword(password: string, stored: string): Promise<boolean> {
  return new Promise((resolve) => {
    const [algo, salt, hash] = stored.split("$");
    if (algo !== "scrypt" || !salt || !hash) return resolve(false);
    scrypt(password, salt, 64, (err, derived) => {
      if (err) return resolve(false);
      const a = Buffer.from(hash, "hex");
      if (a.length !== derived.length) return resolve(false);
      resolve(timingSafeEqual(a, derived));
    });
  });
}
