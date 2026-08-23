# AAQTS Forex Bot

AAQTS is a causal, multi-asset trading research and execution project. Its
Windows demo launcher uses one deliberately small entry policy: a confirmed
UT Bot crossover. Legacy multi-indicator and regime
modules remain available for research but are not part of that deployed entry
decision. Portfolio risk controls, paper trading, managed MT5 exits, and
the role-protected Telegram console remain independent safety/runtime layers.

The safe default is `PAPER`. `MT5_DEMO` must be selected explicitly.
Set `AAQTS_PAPER_STARTING_BALANCE` to the forward-test account size; the
default is `1000`, while a small-account simulation can use `100`.
`MT5_LIVE` has a separate acknowledgement, account pin, server pin and
preflight path. Code support does not establish profitability; complete demo
and out-of-sample validation before intentionally starting real-money orders.

## Active UT Bot-only policy

The demo launcher sets `AAQTS_STRATEGY_MODE=UT_BOT` with:

- UT Bot key value `3.0`
- Wilder ATR period `10`
- closed `15m` candles only
- poll every `1` second, with at most one action per symbol/candle signal ID
- BUY on every fresh confirmed UT Bot BUY crossover
- SELL on every fresh confirmed UT Bot SELL crossover
- an opposite crossover closes the current position and reverses direction
- initial broker stop at `1.5 × ATR`
- move the stop to break-even at `+1R`
- from `+1.5R`, trail the best observed price by `2.5 × ATR`
- no fixed take-profit cap; the trailing stop or opposite UT signal exits

RSI, Stochastic RSI, MACD, ADX, Bollinger Bands, Supertrend, market regime,
market structure, contextual triggers and H1 voting do not confirm or reject
entries in this mode. Protected execution risks `0.5%` per accepted trade,
derives volume from the broker-calculated loss at the initial stop, permits at
most three simultaneous positions, and keeps the news, spread, margin,
portfolio-loss, account-pin and duplicate-candle protections enabled. The old
fixed `0.01`/zero-protection `OPPOSITE_SIGNAL` compatibility mode remains
demo-only and is hard-blocked from `MT5_LIVE`.

The faster poll does not trade a forming candle. It only reduces the delay
between an M15 candle closing and AAQTS observing that closed-candle signal.

## Symbol catalog

The authoritative catalog includes the seven Forex majors, USD and cross-quote
gold/silver, platinum, palladium, BTC/ETH majors, and the requested Bitcoin
crosses. Default scanning is limited to symbols with a validated research feed
and USD-account risk model:

- Forex: `EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `USDCAD`, `AUDUSD`, `NZDUSD`
- Metals: `XAUUSD`, `XAGUSD`, `XPTUSD`, `XPDUSD`
- Crypto: `BTCUSD`, `ETHUSD` (plus `SOLUSD` in paper research only)

`BTCUSDT`, `ETHBTC`, `BTCJPY`, `BTCKRW`, metal crosses, and all requested BTC
crosses remain visible in `config/symbols.py` with explicit disabled reasons.
`BTCAUD`, `BTCCNH`, `BTCTHB`, `BTCZAR`, `BTCXAU`, and `BTCXAG` are broker
close-only instruments and cannot generate new AAQTS entries. `BTCKRW` is not
listed in the current Exness specification. This prevents unsupported symbols
or missing quote-currency conversion from silently producing unsafe orders.

See [AUDIT_STATUS.md](AUDIT_STATUS.md) for the recovery audit, completed work,
validation evidence, and owner-only remaining actions.

## No-admin Windows setup

GitHub CLI is not required. These commands use a project-local Python virtual
environment and do not install a Windows application or require an
administrator password:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts\preflight.py
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m backtesting.run_fast_backtest
```

Start the paper bot only after the checks pass:

```powershell
.venv\Scripts\python.exe main.py
```

If Python itself is not already approved and installed on the office laptop,
use an approved machine or cloud environment. Do not bypass company controls.

## Optional integrations

Telegram dependencies stay separate from the core runtime:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-telegram.txt
.venv\Scripts\python.exe -m telegram_bot.bot
```

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_OWNER_IDS` only in `.env`; never commit
them. `TELEGRAM_CHAT_ID` remains a backward-compatible single-owner fallback.
Optional risk-manager, operator, and viewer allowlists use numeric Telegram
user IDs. Stop-engine and emergency-close confirmations also require a Base32
`TELEGRAM_CONTROL_TOTP_SECRET`. A token previously committed to this repository
must be revoked and replaced through BotFather before Telegram is used.

Generate the TOTP secret locally without installing another application, put
the printed key in `.env`, then add the same key manually to an authenticator:

```powershell
.venv\Scripts\python.exe -c "import base64,secrets; print(base64.b32encode(secrets.token_bytes(20)).decode().rstrip('='))"
```

### Telegram single-account console

`/start` or `/menu` opens a compact dashboard for Dashboard, Positions,
Performance, Signals, Risk, Alerts, Controls, Settings, Audit, and Safety.
`AAQTS_SINGLE_ACCOUNT_MODE=true` is the default. With no account registered,
the owner sees only `Set Up My Account`; after setup, account switching,
combined portfolio, groups, and additional-account buttons remain hidden. The
account wizard stores only alias, broker, fixed MT4/MT5 platform, demo/live
type, login, server, and connection metadata. It never asks for or persists a
trading password.

If an older registry already contains multiple accounts, set
`AAQTS_PRIMARY_ACCOUNT_ID` to the one account that should be visible and
runnable. The application fails closed rather than guessing. Multi-account
mode can be restored later with `AAQTS_SINGLE_ACCOUNT_MODE=false`; no registry
data or underlying isolation support is removed.

Per-account secrets are supplied on the trusted host. An account ID such as
`exness_mt5_01` maps to this environment prefix:

```text
AAQTS_ACCOUNT_EXNESS_MT5_01_PASSWORD=
AAQTS_ACCOUNT_EXNESS_MT5_01_TERMINAL_PATH=C:\MT5-01\terminal64.exe
AAQTS_ACCOUNT_EXNESS_MT5_01_USE_PREAUTHENTICATED_SESSION=false
```

For an already logged-in, approved MT5 terminal, set the account-specific
`USE_PREAUTHENTICATED_SESSION` flag to `true` and leave the account password
unset. The worker attaches to that terminal without storing a password, then
fails closed unless the returned login matches the registered account and the
broker reports demo mode.

Start the Telegram console and account workers in separate terminals:

```powershell
.venv\Scripts\python.exe -m telegram_bot.bot
.venv\Scripts\python.exe account_supervisor.py
```

In the default mode, the supervisor launches one isolated process and state
directory for the selected paper/MT5-demo account. In optional multi-account
mode, each simultaneously running MT5 account must have a unique,
already-approved terminal path. Duplicate terminal assignments fail closed.
The setup does not install a Windows application or bypass office laptop
policy; use existing approved terminals or a VPS.

Exness is treated as the broker, while every trading account keeps its fixed
MT4 or MT5 platform. MT5 demo accounts use the direct Python/terminal worker.
MT4 has no direct connector in this repository, so an MT4 account uses the
documented local/HTTPS bridge contract and remains `SETUP_REQUIRED` until its
bridge URL and `AAQTS_ACCOUNT_<ID>_BRIDGE_TOKEN` are configured. Live accounts
can be registered for read-only visibility but are never started or controlled
by the supervisor.

Telegram controls write durable per-account requests which are claimed by the
actual worker process. Pause blocks new entries while position management
continues. Stop and emergency actions require Owner role, private chat, an
expiring confirmation, and TOTP. Emergency close remains limited to positions
owned by the AAQTS magic number.

For phone-only Codespaces setup, a temporary private browser form can save the
BotFather token without putting it in terminal history. Keep port `8765`
private, open the forwarded URL, and close it after the one successful save:

```bash
.venv/bin/python scripts/codespace_secret_setup.py --host 0.0.0.0 --port 8765
```

The helper validates the token shape, writes `.env` atomically with mode `600`,
does not log the submitted value, and shuts down after a successful save or ten
minutes. It is an onboarding helper only; it never starts or enables trading.

An optional local economic calendar can block entries around verified news
without installing another application. Copy
`config/news_calendar.example.json` to an ignored local file, replace its
contents with verified UTC events, and set:

```text
AAQTS_NEWS_FILTER_ENABLED=true
AAQTS_NEWS_CALENDAR_FILE=config/news_calendar.local.json
```

When enabled, a missing, malformed, or unavailable calendar blocks new trades.
Preflight validates the file before the bot starts.

MT5 demo support is Windows-only and requires an already approved MetaTrader 5
installation:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-mt5.txt
```

For a persistent Windows VPS, keep the password out of `.env`. Log into the
demo account visibly in MT5, then save a DPAPI-encrypted password that only the
same Windows user can decrypt:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\save-demo-credentials.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\install-scheduled-tasks.ps1
Start-ScheduledTask -TaskName "AAQTS-MT5"
Start-ScheduledTask -TaskName "AAQTS-Demo-Engine"
Start-ScheduledTask -TaskName "AAQTS-Telegram"
```

The versioned engine launcher uses the encrypted credential when present. If
it is absent, it explicitly selects demo-only preauthenticated-session mode;
this ignores stale `AAQTS_MT5_LOGIN/PASSWORD/SERVER` values in `.env` and pins
the account identity. `MT5_LIVE` rejects preauthenticated-session mode.

The router validates the returned account login, requires the protective stop,
prevents duplicate managed positions, and serializes access to one MT5 terminal
across the engine and Telegram processes.

For an intentional WinProFX real-account preflight, first save credentials
under the VPS Windows user, then provide the exact terminal path and symbol
suffix to the live launcher. The launcher validates the pinned REAL login,
exact server, quotes, candles, volume metadata and protection policy before it
starts the engine:

```powershell
& .\scripts\windows\save-winprofx-live-credentials.ps1
& .\scripts\windows\start-winprofx-live-engine.ps1 `
  -TerminalPath "C:\Path\To\WinProFX MT5\terminal64.exe" `
  -SymbolSuffix ""
```

## Release validation

Run from the repository root:

```text
python -m compileall -q .
python scripts/security_check.py
python scripts/preflight.py
python -m pytest -q
python -m backtesting.run_fast_backtest
git diff --check
```

The fast backtest is an offline, deterministic release smoke test. It reports
whether a fallback signal was injected to exercise next-bar execution and cost
accounting; it is not evidence of future profitability.

## Architecture and safety contracts

- Production signals use completed candles only.
- Higher-timeframe candles are visible only when
  `close_time <= decision_time`.
- Backtests fill no earlier than the next bar and include spread, slippage,
  commissions, tick rounding, and point-in-time equity sizing.
- Invalid, incomplete, duplicate, or non-monotonic data fails closed.
- AI components may rank or explain an existing rules-based setup; they do not
  invent trade direction.
- The regime router delegates trend and range regimes to the same 2-of-3
  primary trend vote (EMA, Supertrend, momentum). RSI is advisory and becomes
  an opposing-extreme veto only when Bollinger position and an opposing
  reversal candle agree; it is never a duplicate positive confirmation.
  Missing contextual micro-triggers/locations are advisory for an aligned
  majority setup, while a neutral H1 requires high conviction and an opposite
  H1 remains a hard veto. Breakouts still require a range close plus ATR/ADX
  confirmation; unknown or unsafe volatility states remain fail-closed.
- `AAQTS_MIN_ADX` is the canonical ADX eligibility threshold for signal
  validation and all regime classifiers; there is no hidden stronger regime
  boundary after a candle passes validation.
- Range and breakout strategies use reduced position-size multipliers that are
  preserved in deterministic backtest records.
- Portfolio controls can block or reduce a qualified setup based on open risk,
  realized loss, drawdown, correlation, session, volatility, or news context.
- MT5 demo positions are recovered into an independent 10-second lifecycle
  loop and can advance
  to break-even, trail by ATR, take broker-valid partial profits, retain a
  runner, or close on time limits. Paper trading continues to use deterministic
  fixed SL/TP exits until those lifecycle fills are modeled equivalently.
- Demo portfolio checks use the connected broker's equity, managed positions,
  remaining loss to each stop, and realized exit deals; paper account state is
  never mixed into MT5 demo authorization.
- Runtime state, credentials, logs, caches, and paper-account files are ignored
  by Git and checked by CI.
- Runtime state records every decision stage separately (strategy HOLD,
  trade-level reject, portfolio-risk block, execution reject, and execution),
  so a zero-trade period no longer hides the actual gate.

## Research data and reproducibility

Yahoo downloads can be cached under ignored `data/cache/` storage with a
content-addressed dataset version and SHA-256 manifest. Deterministic CSV
replay supports explicit version validation. Experiment reports record the
dataset hash, parameters, fills, costs, expectancy, average R, profit factor,
drawdown, and ending equity.

Use `python -m backtesting.run_backtest` only when network or a validated local
cache is available. CI never depends on live market downloads.
