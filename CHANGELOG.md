# Changelog

## [Unreleased] - 2026-08-03

### Added
- Causal trend, range-reversion, breakout, and no-trade regime routing.
- Regime risk multipliers in runtime sizing and deterministic backtest records.
- MT5 demo break-even, ATR trailing, partial-close, and lifecycle wiring.
- Broker-backed demo equity, open-stop exposure, and realized-loss controls.
- Optional fail-closed JSON economic calendar and symbol currency exposure.
- Runtime integration tests for managed position recovery and exits.
- Authoritative 30-instrument symbol catalog with corrected Yahoo/MT5 Forex
  mappings and explicit close-only/unavailable entry gates.
- Single-account Telegram mode as the safe default, with a compact owner
  dashboard, one-account registration cap, and fail-closed primary selection.
- Optional multi-account registry and supervisor behavior retained behind
  `AAQTS_SINGLE_ACCOUNT_MODE=false` for future expansion.

## [1.0.0] - 2026-07-27

### Added
- Release preflight script and documented validation commands.
- Reproducible release workflow for the Platform Foundation foundation package.
