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

### Independent Python-only gate parity

TradingView cannot verify the Python market-structure/context implementation.
For that reason, export raw M15 and H1 OHLC candles and independently recompute
H1 direction, protected swings, BOS/CHoCH, premium/discount location, and
liquidity sweeps. The independent side deliberately does not import any
production structure/context/indicator helper:

```powershell
.\.venv\Scripts\python.exe scripts\compare_context_gates.py `
  --lower outputs\validation\eth_m15.csv `
  --higher outputs\validation\eth_h1.csv `
  --decision-time "2026-08-10T06:15:00Z" `
  --direction BUY `
  --output outputs\validation\context_eth_001.json
```

Collect at least 100 snapshots across all configured symbols, covering BUY,
SELL, BOS, CHoCH, range, sweep, and no-sweep states. Combine them fail-closed:

```powershell
.\.venv\Scripts\python.exe scripts\combine_context_parity.py `
  --inputs outputs\validation\context_*.json `
  --min-snapshots 100
```

Any mismatched field blocks promotion. This catches a contextual/structure bug
even when the portable TradingView vote still agrees.

## 3. MT5 demo forward test

Export only closed AAQTS deals (identified by the AAQTS magic number), then
build the report:

```powershell
.\.venv\Scripts\python.exe scripts\export_mt5_forward_deals.py `
  --terminal "C:\Program Files\Exness JO MT5 Terminal\terminal64.exe"

.\.venv\Scripts\python.exe scripts\forward_test_report.py `
  --deals outputs\validation\mt5_demo_deals.csv `
  --min-trades 100 `
  --min-symbol-trades 10 `
  --expected-symbols "EURUSDm,GBPUSDm,USDJPYm,USDCHFm,USDCADm,AUDUSDm,NZDUSDm,BTCUSDm,ETHUSDm" `
  --starting-equity 96.69
```

Use the AAQTS equity recorded at the forward-test risk baseline, not the current
balance after unrelated manual trades. Do not judge profitability before 100
closed AAQTS-only trades. Forward profit factor must be at least 1.2,
expectancy positive, and maximum drawdown no greater than 10%. Demo results do
not guarantee live results.

The report includes a per-symbol sample, PF, expectancy, and drawdown table.
Promotion fails if even one expected symbol lacks its minimum sample or fails
PF/expectancy/drawdown; a strong symbol therefore cannot hide a weak one.

It also estimates the calendar time remaining from observed AAQTS broker
closes/day over the last 7 and 30 days. Do not multiply 100 trades by all three
stages: backtests and parity are historical/parallel. Only the 100-trade demo
forward stage consumes calendar time, and an ETA remains unavailable until
actual AAQTS closes establish a non-zero rate.

### Restart/soak resilience

Run this only on the demo worker, during a controlled window in which no new
entry is expected. It never force-kills a stuck process:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\windows\test-demo-restart-soak.ps1
```

The report requires a fresh RUNNING heartbeat, the same account/login/server,
the same risk baseline and risk identity, a non-decreasing persisted equity
peak, the same managed position tickets, and no duplicates. A mismatch blocks
promotion and must be investigated before another soak attempt.

### Backtest-versus-demo slippage

New MT5 entries append request price, broker fill price, adverse slippage, and
the configured backtest assumption to
`runtime\mt5_fill_audit.jsonl`. Request-price fallbacks are retained for audit
but excluded from calibration because they are not broker-observed fills.

```powershell
.\.venv\Scripts\python.exe scripts\slippage_report.py `
  --fills runtime\mt5_fill_audit.jsonl `
  --min-fills 20 `
  --min-symbol-fills 3 `
  --expected-symbols "EURUSD=X,GBPUSD=X,JPY=X,CHF=X,CAD=X,AUDUSD=X,NZDUSD=X,BTC-USD,ETH-USD"
```

Each expected symbol must have a real broker-fill sample and its adverse p95
slippage must remain within the backtest assumption. If not, update assumptions
and rerun the causal backtest before promotion; never tune the report limit to
make an optimistic backtest pass.

## Promotion rule

Backtest, TradingView parity, and forward-test reports are reviewed together:

```powershell
.\.venv\Scripts\python.exe scripts\promotion_report.py `
  --backtest outputs\validation\backtest_metrics_eth_usd.json `
  --parity outputs\validation\tradingview_parity.json `
  --context-parity outputs\validation\context_parity_combined.json `
  --forward outputs\validation\forward_test.json `
  --slippage outputs\validation\slippage.json `
  --restart-soak outputs\validation\restart_soak.json
```

The command exits non-zero if any aggregate or per-symbol sample, PF,
expectancy, drawdown, parity, context, restart, or slippage check fails.
`promotion_report()` can only mark a strategy eligible for human review and
always returns `automatic_live_enable: false`.

## Selectivity diagnostic scope

`scripts/strategy_selectivity_report.py` is a deterministic synthetic
indicator-clash diagnostic, not a real-market frequency test. Its JSON output
must disclose symbol count, first/last decision timestamps, elapsed duration,
the exact frozen audit policy, and the strong-trend RSI-veto ablation. Actual
trade frequency is measured only
from MT5 AAQTS broker deals.
