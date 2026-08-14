# AAQTS Indicator-Only 24H Experiment

This temporary mode pauses the normal AAQTS strategy engine and accepts only TradingView alerts from these exact chart settings:

- **LuxAlgo - Liquidity Sweeps**: Swings `5`, Options `Only Wicks`, Extend `On`, Max bars `300`.
- **AlgoAlpha - Half Trend**: Amplitude `2`, Channel Deviation `2`, Linear Regression Length `7`.
- **Timeframe**: hard-locked to `15m`.

The direction comes only from the TradingView alert. Existing AAQTS regime/ADX/RSI/EMA/HTF/quality/context filters do not participate in direction selection during this experiment.

Safety checks remain active in the dedicated executor: MT5 demo identity pinning, fresh quote validation, duplicate-direction blocking, spread/stop ratio limit, free-margin validation, broker minimum stop distance, a protective broker-side stop, and a separate magic number so experiment positions are isolated from normal AAQTS positions.

## Dynamic TP rule

A future opposite signal cannot be known when the original order is opened, so no fixed broker TP is submitted. Instead, the next opposite valid 15m alert closes the current position at market and immediately opens the new opposite position. The close price of the old trade and the entry event of the new trade are logged together. This implements the requested rule: **the current trade exits/targets at the next trade's entry event**.

Same-direction duplicate alerts do not stack positions; they are logged and ignored.

## TradingView alert payloads

Create four alerts (BUY/SELL for each indicator) on the 15-minute chart. Use the webhook URL:

`http://<VPS_PUBLIC_IP>/webhook/tradingview`

The service only accepts JSON. Read the secret from `runtime/indicator_only_webhook_secret.txt` after the launcher creates it and replace `<SECRET>` below.

### LuxAlgo bullish sweep

```json
{"secret":"<SECRET>","indicator":"LuxAlgo - Liquidity Sweeps","symbol":"{{ticker}}","timeframe":"{{interval}}","side":"BUY","bar_time":"{{time}}","alert_id":"LUX_BUY_{{ticker}}_{{time}}"}
```

### LuxAlgo bearish sweep

```json
{"secret":"<SECRET>","indicator":"LuxAlgo - Liquidity Sweeps","symbol":"{{ticker}}","timeframe":"{{interval}}","side":"SELL","bar_time":"{{time}}","alert_id":"LUX_SELL_{{ticker}}_{{time}}"}
```

### AlgoAlpha Half Trend bullish signal

```json
{"secret":"<SECRET>","indicator":"AlgoAlpha - Half Trend","symbol":"{{ticker}}","timeframe":"{{interval}}","side":"BUY","bar_time":"{{time}}","alert_id":"HALF_BUY_{{ticker}}_{{time}}"}
```

### AlgoAlpha Half Trend bearish signal

```json
{"secret":"<SECRET>","indicator":"AlgoAlpha - Half Trend","symbol":"{{ticker}}","timeframe":"{{interval}}","side":"SELL","bar_time":"{{time}}","alert_id":"HALF_SELL_{{ticker}}_{{time}}"}
```

If TradingView displays a different exact alert-condition label, select the indicator's bullish/bearish condition in the TradingView alert dialog; the JSON message above determines the side sent to AAQTS.

## VPS launch

Run from an Administrator PowerShell in the repository after switching to the experiment branch:

```powershell
.\scripts\windows\start-indicator-only-24h.ps1
```

By default it allows `BTCUSD`, listens on port `80`, uses fixed lot `0.05`, and uses a 1% protective catastrophe stop. These are execution protections, not signal-generation filters.

The launcher pauses `AAQTS-Demo-Engine`, runs this mode for at most 24 hours, and starts the normal engine again when the experiment process exits.

## AWS

TradingView must be able to reach the VPS. The EC2 security group therefore needs an inbound TCP rule for the webhook port from the internet or from an appropriately restricted source. Keep RDP/3389 restricted to the operator IP; do not broaden RDP because of this experiment.

## Runtime evidence

- Status: `runtime/indicator_only_24h_status.json`
- Event/trade log: `runtime/indicator_only_24h.jsonl`
- Standard output: `runtime/indicator-only-24h.log`
- Errors: `runtime/indicator-only-24h-error.log`

The service records accepted/rejected alerts, execution blocks, execution latency, prior-trade close fill, and new-trade entry fill for later comparison with `quality_v3_balanced`.
