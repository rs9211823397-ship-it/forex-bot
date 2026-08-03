# Repository Recovery Status

Updated: 2026-08-03

## Starting condition on `main`

The audited default branch could not compile or run end to end. It contained a
syntax error in MT5 execution, a broken controller import and constructor,
incompatible signal/analyzer calls, committed runtime data and bytecode, no
CI, and a hard-coded Telegram token in two public files. The strongest causal
strategy, risk, execution-simulation, and testing work existed only on the
divergent `strategy-investigation` branch.

## Completed in the recovery branch

| Area | Result |
|---|---|
| Branch recovery | Integrated the strategy-investigation foundation into a fresh branch from `main` and reconciled newer execution and Telegram work. |
| Credentials | Removed the two token-bearing phone files from the current tree and added a token-shaped credential check. |
| Runtime | Rebuilt `main.py` as a valid composition of loop, controller, market data, strategy, risk, paper/MT5 routing, and runtime heartbeat. |
| Strategy | Preserved the stable signal dictionary while exposing richer AI decision reports through a separate analysis API. |
| Causality | Kept completed-candle, point-in-time HTF selection and next-bar execution contracts. |
| Risk | Added instrument-aware sizing and active daily, weekly, drawdown, consecutive-loss, open-trade, and portfolio-heat limits. |
| Execution | Restored the tested MT5 executor with required SL/TP, duplicate protection, managed-position recovery, pause, and emergency stop. |
| Paper state | Added UTC open/close timestamps and project-root state paths for deterministic portfolio context. |
| Dependencies | Split core, development, Telegram, and Windows MT5 requirements; removed unused heavyweight packages. |
| Hygiene | Removed tracked logs, runtime account/trade JSON, backups, phone copies, output artifacts, and bytecode caches. |
| Automation | Added GitHub Actions for install, compile, security, preflight, tests, and an offline deterministic backtest smoke test. |
| Documentation | Added safe no-admin Windows commands, configuration template, architecture contracts, and release validation steps. |
| Regime routing | Added causal trend/range/breakout strategy routing with strict confirmation, HTF conflict gates, reduced risk, and fail-closed volatility handling. |
| Position lifecycle | Completed the MT5 executor contract for quotes, break-even, trailing stops, partial closes, and wired recovery/management into the application cycle. Demo risk now reads broker equity, positions, stop exposure, and realized exits rather than the paper ledger. |
| News protection | Added an optional strict local UTC calendar, currency exposure mapping, preflight validation, and fail-closed runtime behavior. |

## Validation evidence

- Python compile: passed.
- Security and tracked-artifact check: passed.
- Preflight in safe `PAPER` mode: passed.
- Test suite: **318 passed, 2 subtests passed**.
- Deterministic backtest smoke: completed one next-bar trade after explicitly
  reporting that its fallback execution signal was used; ending equity
  `1007.1682`, average R `1.4341`, max drawdown `0.2408%` for that synthetic
  smoke sample. This validates mechanics only, not profitability.
- Diff whitespace check: passed.

## Remaining owner-only or real-world validation

1. Revoke the exposed Telegram token in BotFather and create a new token. Git
   deletion cannot invalidate a leaked credential or erase it from existing
   clones/history.
2. Put the replacement token only in local `.env`, then test the Telegram bot
   on an approved runtime machine.
3. If MetaTrader 5 is already approved and installed, configure a demo account
   and complete a multi-session demo soak test covering restart recovery,
   disconnections, duplicate orders, spreads, SL/TP, and emergency stop.
4. Run walk-forward, out-of-sample research on versioned real data across
   symbols and market regimes before changing any risk settings.
5. Review and merge the strengthening pull request. Keep `MT5_LIVE` locked
   until a separate, evidence-backed live-release decision is made.

No code change can honestly guarantee trading profit. The repository is now
structured to measure expectancy and drawdown causally and to fail closed when
required evidence or runtime dependencies are missing.
