# AAQTS UT Bot + EMA200 24H Experiment

This temporary mode pauses the normal AAQTS strategy engine and runs one simple BTCUSD strategy directly from MT5 15-minute closed candles.

## Strategy

- **Timeframe:** `15m`
- **UT Bot Key Value / Sensitivity:** `3`
- **UT Bot ATR Period:** `10`
- **EMA filter:** `200`
- **BUY:** only on a fresh UT Bot BUY signal when the closed candle is above EMA200.
- **SELL:** only on a fresh UT Bot SELL signal when the closed candle is below EMA200.
- A BUY below EMA200 is ignored for entry.
- A SELL above EMA200 is ignored for entry.

No TradingView webhook is required. The Python service calculates ATR(10), the UT Bot trailing stop, signal flips and EMA200 directly from Exness MT5 candle data every few seconds, acting only once per newly closed 15-minute bar.

## Exit / next-entry rule

The normal exit is the **next opposite UT Bot signal**.

If a SELL is open and the next UT Bot signal is BUY, the SELL is closed even if the BUY is still below EMA200. The BUY is opened only when the BUY signal also passes the EMA200 filter. The mirror rule applies to a BUY followed by a SELL.

No fixed broker TP is submitted. The next opposite UT Bot signal is the logical exit event. A separate 1% broker-side catastrophe stop remains enabled only as emergency protection against connectivity/process failure or an extreme move; it is not the intended strategy exit.

Same-direction signals never stack positions.

## Safety retained

The temporary executor keeps MT5 demo-account identity pinning, fresh quote validation, one managed position per symbol, spread/stop ratio validation, free-margin validation, broker minimum-stop validation and a dedicated magic number. Normal AAQTS regime, RSI, ADX, HTF, quality and contextual strategy filters do not participate in this 24-hour test.

## Windows launch

Switch to branch `agent/indicator-only-24h`, pull the latest commits, then run from Administrator PowerShell:

```powershell
.\scripts\windows\start-indicator-only-24h.ps1
```

Defaults:

- Symbol: `BTCUSD`
- Fixed lot: `0.05`
- Duration: maximum `24` hours
- Poll interval: `5` seconds
- Emergency catastrophe stop: `1%`

The launcher pauses `AAQTS-Demo-Engine` for the experiment and starts the normal engine again when the temporary process exits.

## Runtime evidence

- Status: `runtime/indicator_only_24h_status.json`
- Bar/signal/trade events: `runtime/indicator_only_24h.jsonl`
- Standard output: `runtime/indicator-only-24h.log`
- Errors: `runtime/indicator-only-24h-error.log`

Each newly closed 15m candle records the close, EMA200, ATR10, UT trailing stop, generated signal and whether the EMA entry filter passed. Trade events record the prior position close and any new entry so the 24-hour test can be reviewed afterward.
