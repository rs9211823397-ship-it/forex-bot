# AAQTS AI Chart Analyst — Outcome Evaluator

## Scope

The Outcome Evaluator is a local, forward-only labeling layer for Phase AI-1 evidence. It does not call OpenAI and has no authority over strategy, risk, execution, or position management.

It automatically matures captured actionable BUY/SELL observations against later completed M15 candles.

## Causality policy

For a capture at `as_of_utc`, only candles with:

```text
close_time > as_of_utc
```

may contribute to an outcome.

The capture candle itself is never reused as a future result candle. This preserves next-bar execution semantics and prevents look-ahead leakage.

## Horizons

Default horizons are:

```text
+1 M15 bar
+3 M15 bars
+6 M15 bars
+12 M15 bars
```

`outcome.json` is updated progressively as each horizon becomes available. The record is finalized after the largest configured horizon is complete.

## Entry and R policy

The evaluator prefers captured deterministic levels when they exist.

Entry priority:

1. captured deterministic entry
2. otherwise first future M15 bar open

Risk-unit priority:

1. absolute captured entry-to-stop distance
2. otherwise ATR from the causal capture snapshot

When no captured stop/target exists, canonical labeling barriers are generated from the risk unit:

```text
stop   = 1.0 R adverse
 target = 2.0 R favorable
```

These fallback barriers are for signal-quality labeling only. They do not modify broker orders or the live AAQTS risk plan.

## Same-bar TP/SL ambiguity

M15 OHLC data cannot reveal intrabar ordering when both stop and target are crossed inside the same candle.

Such cases are recorded as:

```text
AMBIGUOUS_SAME_BAR
```

The evaluator does not guess whether TP or SL happened first.

## Metrics

For each available horizon the evaluator records:

- directional percent return
- mark-to-market R
- MFE in R
- MAE in R
- first TP/SL barrier event
- barrier event bar number
- barrier event close timestamp
- terminal R when TP or SL ordering is unambiguous

At the final horizon it records one final status:

- `TP`
- `SL`
- `AMBIGUOUS_SAME_BAR`
- `TIME_HORIZON`

For `TIME_HORIZON`, final realized R is the mark-to-market R at the largest horizon.

## Persistence

Each observation directory may gain:

```text
outcome.json
```

Finalized outcomes are also appended to:

```text
runtime/ai_chart_analysis/outcomes.jsonl
```

On process restart, unfinished `input.json` captures are rediscovered from disk and continue maturing when later market candles become available.

## Runtime configuration

The Windows demo launcher sets:

```text
AAQTS_AI_CHART_OUTCOMES_ENABLED=true
AAQTS_AI_CHART_OUTCOME_HORIZONS=1,3,6,12
AAQTS_AI_CHART_OUTCOME_STOP_R=1.0
AAQTS_AI_CHART_OUTCOME_TARGET_R=2.0
```

Remote OpenAI analysis remains independently controlled by:

```text
AAQTS_AI_CHART_REMOTE_ENABLED=false
```

Therefore outcome labeling remains free/local while capture-only mode is active.

## Acceptance checks

The regression tests verify:

1. candles closing at or before `as_of_utc` cannot become future labels;
2. partial horizons mature into a final +12-bar record;
3. finalized observations are not duplicated;
4. same-bar TP/SL events remain ambiguous;
5. unfinished captures are recovered after restart;
6. Windows runtime keeps remote OpenAI calls disabled while outcome labels are enabled.
