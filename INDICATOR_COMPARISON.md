# UT Bot + EMA200 vs VWAP + EMA9

This is an isolated research comparison. It does not change the AAQTS live or
demo decision engine and it never submits an order.

## Fixed rules

Both strategies use completed M15 candles, act at the next candle's open, hold
at most one normalized position per symbol, charge the same round-trip cost,
and use the same 1% catastrophe price stop. An opposite confirmed event closes
the current position and reverses only when the new entry is allowed.

### UT Bot + EMA200

- UT Bot key value: `3`
- ATR period: `10`, using Wilder's RMA like TradingView `ta.atr`
- BUY event: price crosses above the UT trailing stop
- SELL event: price crosses below the UT trailing stop
- BUY entry allowed only when the signal close is above EMA200
- SELL entry allowed only when the signal close is below EMA200
- An opposite UT event still closes the current position when EMA200 blocks
  the reversal

### Daily VWAP + EMA9

- VWAP source: typical price `(high + low + close) / 3`
- VWAP weight: reported volume; a weight of one is used only when volume is
  unavailable or zero
- VWAP anchor: UTC calendar day
- BUY: EMA9 crosses above VWAP
- SELL: EMA9 crosses below VWAP
- A daily VWAP reset cannot create a crossover by itself

## Universe

`ALL` means the 13 enabled, exactly mapped research instruments:

`EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD, NZDUSD, XAUUSD, XAGUSD,
XPTUSD, XPDUSD, BTCUSD, ETHUSD`.

Known close-only, unavailable, or non-USD instruments are listed in the JSON
report with their exclusion reason. They are not silently proxied with another
instrument.

## Run on the Windows MT5 VPS

Keep the Exness MT5 terminal logged in. From PowerShell in the repository:

```powershell
$repo = "$env:USERPROFILE\forex-bot"
$python = "$repo\.venv\Scripts\python.exe"
Set-Location $repo

& $python scripts\compare_utbot_vwap.py `
  --provider MT5 `
  --symbols ALL `
  --timeframe 15m `
  --lookback-bars 6000 `
  --holdout-percent 30 `
  --min-oos-trades 10 `
  --cost-bps 5 `
  --output-dir outputs\indicator_comparison
```

The script creates:

- `utbot_vwap_report.md`: readable per-symbol and overall comparison
- `utbot_vwap_report.json`: complete settings, coverage, and dataset hashes
- `utbot_vwap_metrics.csv`: full-sample and OOS metrics
- `utbot_vwap_trades.csv`: trade ledger for independent inspection

## Interpretation

The primary evidence is the final 30% chronological out-of-sample segment.
A per-symbol winner is withheld unless both strategies have at least the
configured number of completed OOS trades. The overall verdict uses the
majority of eligible per-symbol winners; the report also shows mean and median
symbol return, profitable-symbol count, trade count, and worst drawdown so the
majority result can be challenged.

Returns are normalized price returns, not MT5 lot-size or leverage returns.
This makes signal quality comparable across instruments but is not a forecast
of account profit. Reported maximum drawdown is calculated on trade-close
equity, not intrabar mark-to-market equity. Stop gaps fill at the less favorable
next open rather than the configured stop price. A backtest winner must still
pass a forward demo test before any production integration is considered.
