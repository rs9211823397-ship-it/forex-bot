# AAQTS Forex Bot

AAQTS is a causal, multi-asset trading research and execution project. It
includes closed-candle signal generation, point-in-time multi-timeframe
alignment, realistic backtesting costs, portfolio risk controls, paper
trading, MT5 demo execution, and Telegram monitoring.

The safe default is `PAPER`. `MT5_DEMO` must be selected explicitly.
`MT5_LIVE` is blocked in code and is not enabled by this release.

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

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` only in `.env`; never commit
them. A token previously committed to this repository must be revoked and
replaced through BotFather before Telegram is used.

MT5 demo support is Windows-only and requires an already approved MetaTrader 5
installation:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-mt5.txt
```

Then set `AAQTS_EXECUTION_MODE=MT5_DEMO` in `.env`. The router validates mode,
requires protective SL/TP, prevents duplicate managed positions, and keeps
live execution locked.

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
- Portfolio controls can block or reduce a qualified setup based on open risk,
  realized loss, drawdown, correlation, session, volatility, or news context.
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
