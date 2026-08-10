# AAQTS Strategy Validation Workflow

No strategy is promoted because a chart or headline looks profitable. Evidence
is collected in three independent stages, and live execution is never enabled
automatically.

## 1. Causal backtest

Run `backtesting/run_backtest.py` with completed candles, next-bar fills,
spread/slippage-aware instrument settings, and immutable experiment metadata.
Every run writes a symbol-specific primary ledger plus full and chronological
70/30 holdout metrics. This ledger intentionally contains the portable primary
vote, not the later Python-only execution gates.

Run every configured strategy symbol independently:

```powershell
$symbols = @(
  "EURUSD=X","GBPUSD=X","JPY=X","CHF=X","CAD=X",
  "AUDUSD=X","NZDUSD=X","BTC-USD","ETH-USD"
)
foreach ($symbol in $symbols) {
  .\.venv\Scripts\python.exe -m backtesting.run_backtest --symbol $symbol
}
```

Each symbol requires at least 100 completed full-sample trades and 20 completed
holdout trades. Both full and holdout segments must have profit factor at least
1.2, positive expectancy, and maximum drawdown no greater than 10%. Parameters
must never be selected from the holdout segment.

## 2. TradingView verification

Add `tradingview/aaqts_primary_vote_verifier.pine` to the same symbol and
timeframe. Export close-confirmed TradingView signals with these columns:

```text
timestamp,symbol,signal
```

Export the equivalent AAQTS primary-vote ledger, then run:

```powershell
.\.venv\Scripts\python.exe scripts\compare_tradingview_signals.py `
  --aaqts outputs\validation\aaqts_primary_signals_eth_usd.csv `
  --tradingview outputs\validation\tradingview_signals.csv
```

Repeat the parity export for every configured symbol. The Pine verifier checks
the portable primary vote and H1 direction. Python
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
  --min-trades 100 `
  --starting-equity 96.69
```

Use the AAQTS equity recorded at the forward-test risk baseline, not the current
balance after unrelated manual trades. Do not judge profitability before 100
closed AAQTS-only trades. Forward profit factor must be at least 1.2,
expectancy positive, and maximum drawdown no greater than 10%. Demo results do
not guarantee live results.

## Promotion rule

Backtest, TradingView parity, and forward-test reports are reviewed together:

```powershell
.\.venv\Scripts\python.exe scripts\promotion_report.py `
  --backtest outputs\validation\backtest_metrics_eth_usd.json `
  --parity outputs\validation\tradingview_parity.json `
  --forward outputs\validation\forward_test.json
```

The command exits non-zero if any sample, PF, expectancy, drawdown, coverage,
or parity check fails. `promotion_report()` can only mark a strategy eligible
for human review and always returns `automatic_live_enable: false`.

## Selectivity diagnostic scope

`scripts/strategy_selectivity_report.py` is a deterministic synthetic
indicator-clash diagnostic, not a real-market frequency test. Its JSON output
must disclose symbol count, first/last decision timestamps, elapsed duration,
the exact frozen audit policy, and the strong-trend RSI-veto ablation. Actual
trade frequency is measured only
from MT5 AAQTS broker deals.
