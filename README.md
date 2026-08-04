# AAQTS Forex Bot

AAQTS is a causal, multi-asset trading research and execution project. It
includes closed-candle signal generation, point-in-time multi-timeframe
alignment, causal trend/range/breakout routing, realistic backtesting costs,
portfolio risk controls, paper trading, managed MT5 demo exits, and a
role-protected Telegram console that defaults to one personally managed account.
The multi-account registry remains available as an explicit future opt-in.

The safe default is `PAPER`. `MT5_DEMO` must be selected explicitly.
Set `AAQTS_PAPER_STARTING_BALANCE` to the forward-test account size; the
default is `1000`, while a small-account simulation can use `100`.
`MT5_LIVE` is blocked in code and is not enabled by this release.

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

Then set `AAQTS_EXECUTION_MODE=MT5_DEMO`, `AAQTS_MT5_LOGIN`,
`AAQTS_MT5_PASSWORD`, and `AAQTS_MT5_SERVER` in `.env` for a single worker, or
use the per-account variables above with `account_supervisor.py`. The router
validates the returned account login, requires protective SL/TP, prevents
duplicate managed positions, and keeps live execution locked.

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
- The regime router delegates trends to the existing causal pipeline, requires
  Bollinger/RSI re-entry for ranges, requires range-close/ATR/ADX confirmation
  for breakouts, and blocks unknown or unsafe volatility states.
- Range and breakout strategies use reduced position-size multipliers that are
  preserved in deterministic backtest records.
- Portfolio controls can block or reduce a qualified setup based on open risk,
  realized loss, drawdown, correlation, session, volatility, or news context.
- MT5 demo positions are recovered into the lifecycle manager and can advance
  to break-even, trail by ATR, take broker-valid partial profits, retain a
  runner, or close on time limits. Paper trading continues to use deterministic
  fixed SL/TP exits until those lifecycle fills are modeled equivalently.
- Demo portfolio checks use the connected broker's equity, managed positions,
  remaining loss to each stop, and realized exit deals; paper account state is
  never mixed into MT5 demo authorization.
- Runtime state, credentials, logs, caches, and paper-account files are ignored
  by Git and checked by CI.

## Research data and reproducibility

Yahoo downloads can be cached under ignored `data/cache/` storage with a
content-addressed dataset version and SHA-256 manifest. Deterministic CSV
replay supports explicit version validation. Experiment reports record the
dataset hash, parameters, fills, costs, expectancy, average R, profit factor,
drawdown, and ending equity.

Use `python -m backtesting.run_backtest` only when network or a validated local
cache is available. CI never depends on live market downloads.
