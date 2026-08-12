# AAQTS AI Chart Analyst — Phase AI-1

## Scope

Phase AI-1 is an **observer only**. It may create chart images, call a vision-capable model, validate structured analysis, and persist evidence for later evaluation. It has no authority to place, size, modify, delay, approve, reject, or close a trade.

The existing deterministic AAQTS strategy, portfolio-risk, execution, and position-management paths remain authoritative.

## Safety and architecture boundary

The Phase AI-1 package lives under `ai/chart_analysis/` and deliberately has no dependency on `execution.execution_router`, `risk.protection`, or broker order methods.

Observer failures are fail-open with respect to trading: a rendering, network, authentication, schema, or storage failure must not block the deterministic engine.

The deterministic AAQTS decision is stored as comparison evidence, but it is not passed to the remote model. This preserves a blind second opinion and avoids anchoring the model to AAQTS's answer.

## Causal market snapshot

The observer consumes the same completed broker-market frames used by AAQTS.

- Lower timeframe: M15
- Higher timeframe: H1
- Authoritative `as_of_utc`: close time of the newest completed M15 candle
- Both M15 and H1 frames are truncated to `close_time <= as_of_utc`
- No candle closing after `as_of_utc` may appear in numeric input or chart rendering
- Snapshot IDs include symbol, timeframe identity, timestamp, and a deterministic digest

The numeric snapshot contains recent OHLCV bars plus available indicator values such as EMA 20/50/200, RSI, Stochastic RSI, MACD, ATR, ADX, Bollinger Bands, volume context, OBV, and Supertrend.

## Chart rendering

Charts are rendered locally from the causal DataFrames rather than scraped from TradingView. This makes live observations and historical replay reproducible from the exact input used by AAQTS.

Each observation renders two PNG files:

- `m15.png` — entry/execution context
- `h1.png` — higher-timeframe context

The renderer uses completed candles and overlays EMA 20/50/200 and Bollinger-band boundaries when available. RSI, ADX, ATR, and Supertrend are included as compact diagnostics.

## Model output contract

The model must return one strict structured record containing:

- snapshot identity and timestamp
- market regime
- trend direction
- higher-timeframe bias
- market structure
- BOS/CHoCH state
- liquidity event
- setup classification
- BUY / SELL / HOLD
- evidence-strength confidence from 0 to 100
- optional entry zone, invalidation, targets, and estimated R:R
- concise supporting evidence
- concise contradictions
- data quality
- explicit abstention flag

Identity fields are validated against the local snapshot before a result is accepted.

Confidence is treated as an uncalibrated evidence-strength score in Phase AI-1, not as a probability of profit.

## Prompt policy

Prompt version: `aaqts_chart_v1.0`

The model is instructed to:

- remain observational
- use no data after `as_of_utc`
- independently evaluate structure, regime, liquidity, setup quality, invalidation, and targets
- prefer HOLD/abstain when evidence is conflicting
- never guess the withheld deterministic AAQTS decision

Prompt versions are persisted with every observation so prompt experiments can be evaluated independently.

## Scheduling policy

Phase AI-1 deduplicates by symbol and completed M15 candle. Repeated five-minute engine scans must not call the model repeatedly for the same completed candle.

Default policy is `only_actionable=true`: only deterministic BUY/SELL candidates are submitted to the observer. HOLD candles are marked seen and skipped. This default controls cost and concurrency while the evaluation dataset is being established.

The observer uses a bounded worker pool. When all observer workers are busy, the deterministic trading loop is never made to wait.

## Evidence layout

Runtime artifacts are stored beneath the already-gitignored `runtime/` tree:

```text
runtime/ai_chart_analysis/
├── observations.jsonl
└── YYYY-MM-DD/
    └── <snapshot_id>/
        ├── input.json
        ├── m15.png
        ├── h1.png
        ├── analysis.json
        └── error.json          # only when an observation fails
```

`input.json` stores the causal snapshot and deterministic comparison record separately. `analysis.json` stores the validated AI result plus response metadata/usage. `observations.jsonl` is an append-only compact index for later evaluation.

Secrets and API keys are never written to these evidence files.

## Configuration

Phase AI-1 is disabled by default.

```text
AAQTS_AI_CHART_ENABLED=false
AAQTS_AI_CHART_MODE=OBSERVER
AAQTS_AI_CHART_MODEL=gpt-5
AAQTS_AI_CHART_ONLY_ACTIONABLE=true
AAQTS_AI_CHART_MAX_INFLIGHT=2
AAQTS_AI_CHART_LOWER_RENDER_BARS=96
AAQTS_AI_CHART_HIGHER_RENDER_BARS=96
AAQTS_AI_CHART_NUMERIC_BARS=24
AAQTS_AI_CHART_TIMEOUT_SECONDS=30
AAQTS_AI_CHART_IMAGE_DETAIL=high
AAQTS_AI_CHART_MAX_OUTPUT_TOKENS=1400
AAQTS_AI_CHART_PROMPT_VERSION=aaqts_chart_v1.0
AAQTS_AI_CHART_OUTPUT_ROOT=runtime/ai_chart_analysis
AAQTS_AI_CHART_API_KEY_ENV=OPENAI_API_KEY
OPENAI_API_KEY=<local secret only>
```

Do not commit a real API key.

## Optional dependency

Install the AI rendering extras with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

The remote client intentionally uses Python's standard HTTP library so Phase AI-1 does not depend on a particular OpenAI Python SDK version.

## Current implementation boundary

The Phase AI-1 package, causal snapshot contract, renderer, structured schema, API client, evidence store, async observer, and unit/regression tests are implemented as isolated components.

**The live `TradingApplication` hook remains intentionally disabled/not wired during the current one-day deterministic demo observation window.** No API request is made merely by pulling these files. Activation should be a separate controlled step after the current trading window so AI scaffolding cannot contaminate the baseline being measured.

## Activation acceptance criteria

Before wiring the observer into `main.py`:

1. Existing deterministic test suite remains green.
2. Phase AI-1 tests prove H1 data is causally truncated to the M15 snapshot timestamp.
3. Duplicate scans of one completed M15 candle create at most one observation.
4. HOLD candidates create no remote work with the default actionable-only policy.
5. The deterministic comparison record is absent from the model input.
6. Invalid response identity/schema is rejected and logged.
7. Observer failure cannot interrupt or reject a deterministic trade.
8. No execution or risk module imports the AI chart-analysis result.

## Next phase after activation

Once sufficient observations exist, an outcome evaluator will attach forward-only labels such as 1/3/6/12-bar returns, MFE, MAE, TP/SL ordering, and realized/normalized R. AAQTS-alone performance will then be compared with AI-agreement/disagreement buckets before any confirmation-mode authority is considered.
