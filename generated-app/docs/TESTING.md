# AAQTS v2.0 — Testing Report

```
Test Files  8 passed (8)
     Tests  46 passed (46)
  Duration  ~1.4s
        (vitest run, node environment — see vitest.config.ts)
```

Run again: `npx vitest run`

## Coverage matrix (Feature 8 requirements)

| Requirement | Test file | Verified behaviors |
|---|---|---|
| MT5 connection | `tests/mt5-bridge.test.ts` | simulated connect returns company + latency; range-checked |
| Exness login | `tests/mt5-bridge.test.ts` | valid Exness credential accepted; short password → `AUTH_FAILED`; malformed login id rejected |
| Multiple accounts | `tests/execution.test.ts` | plan fan-out over 3 accounts — one blocked (paused), others executed |
| Start/stop functionality | `tests/bot-state.test.ts` | START from STOPPED/PAUSED; STOP keeps position monitoring; emergency halts everything; explicit RESET required |
| Order execution | `tests/mt5-bridge.test.ts` | BUY/SELL fill, invalid lots rejected, modify SL/TP, close, partial close keeps remainder, history records |
| Risk separation | `tests/execution.test.ts` + `tests/risk.test.ts` | same signal → 2×/½× lots & risk amounts for 2%/0.5% accounts; daily-loss breach blocks only that account; correlation filter per account |
| Mobile authentication | `tests/session-token.test.ts` + `tests/passwords.test.ts` | Bearer token sign/verify, tamper + expiry rejection, scrypt hash/verify, wrong-password rejection |
| Bot manual/emergency gating | `tests/bot-state.test.ts` | `canOpenOrder` matrix across all four states |

## Test list

- `tests/crypto.test.ts`
  - round-trips arbitrary secrets (unicode, 512-byte)
  - random-IV unique ciphertexts
  - legacy plaintext passthrough + `isEncrypted` detection
  - tampered ciphertext rejected
- `tests/passwords.test.ts`
  - scrypt verify true/false, salt uniqueness, malformed records safe
- `tests/session-token.test.ts`
  - sign/verify, tampered signature rejected, forged payload rejected, expired rejected, deterministic SHA-256 hashing
- `tests/bot-state.test.ts`
  - full state machine transitions + invalid-transition rejection + order gating matrix
- `tests/risk.test.ts`
  - lot sizing scales with risk %, balance, bounds; daily/weekly/consecutive-loss limits; correlation groups
- `tests/execution.test.ts`
  - multi-account copy: risk-separated lots, blocked accounts, correlation gate, per-account daily loss
- `tests/mt5-bridge.test.ts`
  - Exness connect/auth failure, order lifecycle, modify, close, partial close, live unrealized PnL
- `tests/indicators.test.ts`
  - full-length indicator outputs (catches Bollinger middle-array alignment regression), `analyzeMarket` never throws and persists finite values across 4 symbols × 3 timeframes

## Notes for CI

- Tests never touch the network or the database — bridge and stores are deterministic/in-process.
- To also verify DB wiring in staging, log in, load demo data, then hit
  `GET /api/health`, `POST /api/bot/control {command:start}` and
  `POST /api/mt5/connect {accountId:1}` — all should 2xx with the seeded demo account.
