# AAQTS Chart Research Pipeline

## Current state

AAQTS now has a complete local research pipeline around actionable deterministic BUY/SELL candidates.

The research path is observer-only and has zero execution authority. Strategy, risk, execution, and position management remain deterministic and authoritative.

## Live capture flow

1. `RegimeStrategyRouter` produces the deterministic AAQTS decision.
2. Actionable BUY/SELL candidates are submitted to the chart observer.
3. The observer causally truncates M15 and H1 data to the newest completed M15 close.
4. Local M15/H1 charts and `input.json` are persisted.
5. Capture-only mode writes `capture.json` and makes no OpenAI API request.
6. The outcome evaluator follows only future completed M15 candles.
7. +1 / +3 / +6 / +12 bar labels are written to `outcome.json`.
8. Finalized outcomes are appended to `outcomes.jsonl`.
9. Outcome analytics refresh automatically into `analytics_summary.json`.

## Outcome labels

The evaluator records:

- directional return percent
- mark-to-market R
- MFE in R
- MAE in R
- first TP/SL barrier event
- same-bar TP+SL ambiguity without guessing order
- final 12-bar status and realized/normalized R

If captured trade levels are unavailable, research labels use the next completed M15 bar open and snapshot ATR as the canonical normalized risk unit.

## Analytics

`runtime/ai_chart_analysis/analytics_summary.json` contains:

- capture / pending / finalized / error counts
- expectancy R
- median R
- total R
- profit factor when both gains and losses exist
- positive-R rate
- +1 / +3 / +6 / +12 horizon averages
- symbol breakdown
- BUY vs SELL breakdown
- confidence buckets
- regime breakdown
- strategy breakdown
- future AAQTS-vs-AI agreement buckets

Small samples are explicitly guarded:

- overall conclusions require 30 finalized samples by default
- bucket-level conclusions require 10 finalized samples by default

Until those thresholds are met, statistics are descriptive only.

## Human-readable report

On the Windows VPS:

```powershell
.\scripts\windows\show-ai-chart-analytics.ps1
```

The script refreshes analytics from local evidence only. It makes no network or OpenAI API call.

## Historical AI replay

Persisted chart captures can later be sent through the remote chart analyst without changing trading logic.

Safe dry-run:

```powershell
.\.venv\Scripts\python.exe -m ai.chart_analysis.replay
```

Dry-run only reports the number of captures that do not yet have `analysis.json`.

Actual remote replay is deliberately opt-in and requires both:

- `AAQTS_AI_CHART_REMOTE_ENABLED=true`
- explicit `--execute`

Example for a future funded API account:

```powershell
.\.venv\Scripts\python.exe -m ai.chart_analysis.replay --execute --limit 5
```

Existing `analysis.json` files are skipped, so replay is idempotent. Replay failures are research failures only and do not enter the live trading path.

## Future AAQTS-vs-AI comparison

When an `analysis.json` exists, analytics classifies the AI response as:

- `AGREE` — AI BUY/SELL matches deterministic AAQTS
- `DISAGREE` — AI takes the opposite directional side
- `AI_HOLD` — AI returns HOLD without abstention
- `ABSTAIN` — AI explicitly abstains

Finalized R statistics are then computed separately for each relation bucket. This enables an evidence-based comparison of AAQTS alone versus AI agreement/disagreement without granting AI trading authority.

## What cannot be manufactured early

Two things depend on external future data and therefore must not be fabricated:

1. A 12-bar outcome cannot finalize until 12 future completed M15 candles actually exist.
2. Reliable statistical conclusions cannot exist until the configured minimum sample counts are reached.

Both conditions are now handled automatically by the pipeline as real market data accumulates.
