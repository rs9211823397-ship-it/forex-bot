# AAQTS Strategy Validation Workflow

No strategy is promoted because a chart or headline looks profitable. Evidence
is collected in three independent stages, and live execution is never enabled
automatically.

## 1. Causal backtest

Run `backtesting/run_backtest.py` with completed candles, next-bar fills,
spread/slippage-aware instrument settings, and immutable experiment metadata.
The run writes `outputs/validation/aaqts_primary_signals.csv` for parity
verification. This ledger intentionally contains the portable primary vote,
not the later Python-only execution gates.
Require at least 100 completed trades and review profit factor, expectancy,
maximum drawdown, average R, and the out-of-sample segment. Optimization results
must not be evaluated on the same period used to choose parameters.

## 2. TradingView verification

Add `tradingview/aaqts_primary_vote_verifier.pine` to the same symbol and
timeframe. Export close-confirmed TradingView signals with these columns:

```text
timestamp,symbol,signal
```

Export the equivalent AAQTS primary-vote ledger, then run:

```powershell
.\.venv\Scripts\python.exe scripts\compare_tradingview_signals.py `
  --aaqts outputs\validation\aaqts_primary_signals.csv `
  --tradingview outputs\validation\tradingview_signals.csv
```

The Pine verifier checks the portable primary vote and H1 direction. Python
remains authoritative for market structure, contextual state, risk, portfolio,
news, sizing, and execution. Any mismatch must be explained before promotion.

## 3. MT5 demo forward test

Export only closed AAQTS deals (identified by the AAQTS magic number), then
build the report:

```powershell
.\.venv\Scripts\python.exe scripts\export_mt5_forward_deals.py `
  --terminal "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"

.\.venv\Scripts\python.exe scripts\forward_test_report.py `
  --deals outputs\validation\mt5_demo_deals.csv `
  --min-trades 100
```

Do not judge profitability before the configured minimum sample is complete.
Forward expectancy must be positive and drawdown must remain within the account
risk policy. Demo results do not guarantee live results.

## Promotion rule

Backtest, TradingView parity, and forward-test reports are reviewed together.
`promotion_report()` can mark a strategy eligible for human review, but always
returns `automatic_live_enable: false`.
