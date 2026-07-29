# AAQTS v2.0 — Architecture

## Layered architecture

```
┌───────────────────────────────────────────────────────────┐
│ PRESENTATION                                              │
│  web dashboard (Next.js App Router, Tailwind)             │
│  AI Trading Manager (React Native / Expo — iOS+Android)   │
├───────────────────────────────────────────────────────────┤
│ EDGE GATE  (src/proxy.ts)                                 │
│  HMAC session verification, cookie & Bearer, page redirect│
│  401 for unsigned API calls                               │
├───────────────────────────────────────────────────────────┤
│ API SERVER  (route handlers)                              │
│  /api/auth  /api/bot  /api/mt5  /api/accounts             │
│  /api/trades  /api/signals  /api/backtest  /api/ai        │
│  mutation routes additionally call requireUser()          │
├───────────────────────────────────────────────────────────┤
│ DOMAIN SERVICES                                           │
│  lib/bot        master bot state machine + audit          │
│  lib/mt5        per-account sessions + order routing      │
│  lib/security   crypto / passwords / sessions             │
│  lib/engine     indicators, signal AI, risk, execution    │
├───────────────────────────────────────────────────────────┤
│ DATA  PostgreSQL via Drizzle ORM                          │
│  users sessions bot_state bot_settings trading_accounts   │
│  trades signals regime_snapshots backtests ai_decisions   │
│  mt5_events execution_events candles symbols system_state │
├───────────────────────────────────────────────────────────┤
│ EXTERNAL                                                  │
│  MetaTrader5 terminals (Exness …) via bridge/mt5_service  │
└───────────────────────────────────────────────────────────┘
```

## Design decisions

1. **Bot state machine is pure** (`lib/bot/state.ts`). Every transition —
   START / STOP / PAUSE / RESUME / EMERGENCY / RESET — is unit-testable; the
   controller only persists results and emits audit events.
   *PAUSED keeps signal generation ON and execution OFF (per PRD).*
   *EMERGENCY_STOP requires an explicit RESET; only emergency may close all
   positions (with user confirmation).*

2. **MT5 abstraction** (`lib/mt5/bridge.ts`). One `IMt5Bridge` interface with
   two drivers: `simulated` (in-process fills, latency, auth failures — default
   for dev/paper/CI) and `http` (production bridge `bridge/mt5_service.py`
   running the official MetaTrader5 Python package on a Windows VPS).
   Swapping is a single env var; no code change.

3. **Credentials never travel**. MT5 passwords are written once (AES-256-GCM),
   decrypted in-memory at connect-time only, never returned by any API, never
   logged — even `sessionToken` values are encrypted at rest in
   `trading_accounts`.

4. **Per-account everything**. Each `trading_account` carries its own risk %,
   daily/weekly loss caps, consecutive-loss circuit breaker, trading toggle,
   connection state and prior session. The copy-execution manager
   (`/api/execute`) builds an execution plan per account and rejects accounts
   individually (paused account, correlation clash, daily-loss breach) without
   blocking the others — this is how 50+ Exness accounts copy one master
   signal with independent money management.

5. **Same API for web and mobile**. Sessions are HMAC-signed tokens; web uses
   an HTTP-only cookie, mobile uses `Authorization: Bearer`. There is one
   authentication system (`/api/auth/login`) and one permission model.

6. **Audit trail everywhere**. Bot commands, MT5 connects/disconnects, order
   opens/modifications/closes land in `bot_events`/`mt5_events` and
   `execution_events` with latency — queryable at `/api/bot/events`.

## Data flow — master signal to N accounts

```
indicator engine ─▶ signal engine ─▶ AI quality gate (A+..reject)
        │                                     │ approved: /api/signals POST
        ▼                                     ▼
   regime snapshot                  /api/execute?signalId=N
                                             │
                        bot gate? (RUNNING, manual override on PAUSED)
                                             │
                        per-account runtime: balance±PnL, losses, open syms
                                             │ buildExecutionPlan()
                        ┌──────┬────────────┼─────────┬────────┐
                        ▼      ▼            ▼         ▼        ▼
                      Acct1  Acct2        Acct3     AcctN  (blocked list
                      1.0%   0.5%         2.0%      1.5%   w/ reasons)
                        │      │            │         │
                        ▼      ▼            ▼         ▼
                placeOrder() via MT5 manager → ticket, fill, audit
```

## Scaling 50+ Exness accounts

- Accounts are rows, sessions are a lazy Map; connect on demand.
- Execution plans loop serverside — O(n) DB inserts per master signal; move to
  a queue (e.g. BullMQ/Redis) for sub-second fan‑out at scale.
- The Python bridge runs one process per terminal; for many live terminals run
  several `mt5_service.py` instances on multiple Windows VPS hosts and shard
  accounts by `MT5_BRIDGE_URL` (extend `manager.ts` with a `bridgeUrl` column).
- Optional fields on `trading_accounts` support futures: user-scoped accounts
  (`userId`), master/copy designations (`isMaster`).
