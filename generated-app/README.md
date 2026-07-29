# AAQTS — AI Adaptive Quant Trading System v2.0

Institutional-grade, multi-asset (Forex / Gold / Silver / Crypto), multi-account
MT5 trading platform with a master AI engine, encrypted credential vault,
web dashboard and identical iOS + Android companion apps.

```
  ┌─────────────────────── OPERATORS ───────────────────────┐
  │                                                         │
  │   Web Dashboard (Next.js)      AI Trading Manager       │
  │   /login … /settings           iOS + Android apps       │
  │                                                         │
  └──────────────┬──────────────────────────┬───────────────┘
                 │ cookie/HMAC              │ Bearer/HMAC
                 ▼                          ▼
        ┌───────────────────────────────────────────┐
        │   API Server (Next.js Route Handlers)     │
        │   src/proxy.ts (edge gate)                │
        │                                           │
        │   /api/auth/*   users, sessions           │
        │   /api/bot/*    master start/stop/pause/  │
        │                 emergency, settings       │
        │   /api/mt5/*    connect, order, modify,   │
        │                 close, positions, history │
        │   /api/accounts, trades, signals, ...     │
        └───────┬────────────────────┬──────────────┘
                ▼                    ▼
        ┌──────────────┐     ┌───────────────────────┐
        │ Trading Eng. │     │ Security layer        │
        │ indicators / │     │ AES-256-GCM creds     │
        │ signal AI /  │     │ scrypt passwords      │
        │ risk / regime│     │ HMAC sessions         │
        └──────┬───────┘     └───────────┬───────────┘
               ▼                         ▼
        ┌──────────────────────────────────────────┐
        │  PostgreSQL (Drizzle ORM)                │
        │  users, sessions, trading_accounts,      │
        │  bot_state, bot_settings, trades,        │
        │  signals, mt5_events, execution_events…  │
        └──────────────────────────────────────────┘
               ▼
        ┌─────────────────────────────────────────┐
        │  MT5 Execution Manager (per-account)    │
        │  src/lib/mt5/manager.ts + bridge.ts     │
        └───────┬─────────────────────┬───────────┘
                │ simulated mode      │ http mode
                ▼                     ▼
        in-process fills       bridge/mt5_service.py
        (paper/demo)           on Windows VPS running
                               MetaTrader5 Python API
                               └──▶ 50+ Exness MT5 accounts
```

## Delivery inventory

### New files (this release, v2.0)

**Security (Feature 4)**
- `src/lib/security/crypto.ts` — AES-256-GCM credential encryption
- `src/lib/security/passwords.ts` — scrypt password hashing
- `src/lib/security/token.ts` — HMAC session tokens (Edge + Node)
- `src/lib/security/session.ts` — cookie/Bearer sessions, `requireUser` guard
- `src/proxy.ts` — edge authentication gate (twas `middleware.ts`; Next 16 proxy convention)

**Master bot control (Feature 1)**
- `src/lib/bot/state.ts` — pure `STOPPED / RUNNING / PAUSED / EMERGENCY_STOP` state machine
- `src/lib/bot/controller.ts` — persistence, audit, emergency close-all
- `src/app/api/bot/{status,control,emergency,settings,events}/route.ts`

**Auth API (Feature 4/6)**
- `src/app/api/auth/{login,logout,me,password,bootstrap}/route.ts`

**MT5 (Features 2 & 3)**
- `src/lib/mt5/bridge.ts` — `IMt5Bridge` with `simulated` + `http` (real MT5) modes
- `src/lib/mt5/manager.ts` — per-account sessions, encrypted creds, order routing, audit
- `src/app/api/mt5/{connect,disconnect,order,modify,close,positions,history}/route.ts`
- `src/app/api/accounts/credentials/route.ts`
- `bridge/mt5_service.py` — Windows MetaTrader5 Python bridge (production live mode)

**Web**
- `src/app/login/page.tsx`, `src/app/settings/page.tsx`

**Mobile (Feature 5)**
- `mobile/` — Expo React Native app (`App.tsx`, `src/api/client.ts`, `src/store/auth.tsx`, `src/screens/{Login,Dashboard,Accounts,Trades,Signals}.tsx`, `app.json`, `eas.json`, `package.json`, `README.md`) — same application id `com.aaqts.tradingmanager` for both platforms.

**Tests (Feature 8)**
- `tests/{crypto,passwords,session-token,bot-state,risk,execution,mt5-bridge}.test.ts` (43 tests)
- `vitest.config.ts`

**Docs**
- `docs/ARCHITECTURE.md`, `docs/TESTING.md`, this README

### Modified files

- `src/db/schema.ts` — users, sessions, bot_state, bot_settings, mt5_events, execution_events; `trading_accounts` gains `userId`, `tradingEnabled`, `connectionStatus`, `sessionToken`, `lastConnectedAt`; `trades.mt5Ticket`
- `src/app/api/accounts/route.ts` — encrypted storage; passwords stripped from responses; enable/disable trading
- `src/app/api/execute/route.ts` — bot state gate + per-account trading enablement + MT5 manager routing
- `src/app/api/system/route.ts` — backward-compat shim onto bot controller
- `src/app/api/seed/route.ts` — auth-protected, encrypted demo credentials
- `src/app/api/dashboard/route.ts` — credentials stripped
- `src/components/{Provider,Sidebar,Shell}.tsx` — new BOT_STATUS control panel, auth-aware
- `src/app/{page,accounts,risk}/page.tsx` — bot banner, connection management, risk controls
- `src/app/layout.tsx`, `tsconfig.json`

### Unchanged core engines (non-breaking guarantee)

- `src/lib/engine/{indicators,signalEngine,risk,execution,marketData}.ts`
- backtesting (`src/app/api/backtest/`), paper trading (`src/app/api/trades/`), AI learning (`src/app/api/ai/`)

## Installation

```bash
npm install
cp .env.example .env   # or create .env (see below)
npx drizzle-kit push   # create/upgrade database schema
```

Required environment variables:

```bash
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/app_db
SESSION_SECRET=<random 32+ chars>            # HMAC session signing
CREDENTIALS_ENCRYPTION_KEY=<random 32+ char> # AES-256-GCM key source
ADMIN_USERNAME=admin                          # first-boot admin (optional)
ADMIN_PASSWORD=admin123                       # first-boot admin (optional, used only if no users exist)
MT5_BRIDGE_MODE=simulated                     # or "http" for real MT5
MT5_BRIDGE_URL=http://127.0.0.1:8080          # only needed for http mode
```

Then:

```bash
npm run build && npm start
# or npm run dev
```

First opening shows `/login`. The one-time security bootstrap runs automatically
(creates admin + encrypts any legacy plaintext passwords). Change the default
password in Settings immediately.

## Database setup

PostgreSQL 15+. The Drizzle schema lives in `src/db/schema.ts`.

```bash
createdb app_db
npx drizzle-kit push      # sync schema (no manual migrations needed)
psql postgresql://…/app_db -c "\dt"   # verify 15 tables
```

Demo data: after logging in press **“Load demo data”** on the Overview page
(or `POST /api/seed` with your session cookie).

## MT5 / Exness connection

Two bridge modes:

1. **Simulated (default)** — full order lifecycle locally; ideal for paper trading,
   demos and CI. Nothing else to install.
2. **HTTP (production live)** — run `bridge/mt5_service.py` on a Windows machine
   with an MT5 terminal:

   ```bash
   pip install MetaTrader5 fastapi uvicorn
   uvicorn mt5_service:app --host 0.0.0.0 --port 8080
   ```

   Set `MT5_BRIDGE_MODE=http` and `MT5_BRIDGE_URL` on the server.

Then in the web dashboard → **Accounts**:

1. Add account: name, MT5 login id, password (stored AES-256-GCM — never shown again), server (`Exness-MT5Real8`…), broker, type, individual risk %.
2. Press **CONNECT MT5** — watch status flip Connected / Auth failed (latency shown in toast).
3. **TRADING ON/OFF** independently enables each account for master-signal copy execution.
4. **PASSWORD** rotates MT5 credentials (re-encrypted, session invalidated).
5. Live orders: start the bot in **LIVE** mode from the bot panel — master AI signals copy to every Connected + Trading-ON account with per-account risk scaling.

To spread across 50+ Exness sub-accounts simply add them — every account gets its own
risk %, connection token, event audit and balance ledger.

## iOS / Android builds

See `mobile/README.md`. Summary:

```bash
cd mobile && npm install
eas build --platform ios      # iOS (.ipa / TestFlight)
eas build --platform android  # Android (.apk / .aab)
```

Both apps share `com.aaqts.tradingmanager`, the same API client and auth screens.

## Testing

```bash
npx vitest run        # 46 tests — see docs/TESTING.md for the latest report
```

Coverage: encryption, password hashing, session tokens, **bot start/stop/pause/emergency**,
MT5 connect + login failures, order lifecycle (open/modify/close/partial),
**multi-account risk separation**, correlation filter, position sizing.

## API cheat sheet (for mobile or custom clients)

```
POST /api/auth/login                { username, password }  → { token }
GET  /api/bot/status                                       → BOT_STATUS snapshot
POST /api/bot/control          { command: start|pause|resume|stop|reset, mode? }
POST /api/bot/emergency        { confirm: true, closePositions?: bool }
POST /api/accounts             add MT5 account (password encrypted at rest)
POST /api/mt5/connect          { accountId }               → company + latency
POST /api/mt5/order            { accountId, symbol, direction, lots, sl, tp, mode }
POST /api/mt5/close            { accountId, tradeId, percent }
GET  /api/mt5/positions        live open positions w/ unrealized PnL
GET  /api/mt5/history          closed trades
```
