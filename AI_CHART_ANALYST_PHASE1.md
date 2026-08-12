# AAQTS AI Chart Analyst — Phase AI-1

## Scope

Phase AI-1 is an **observer only**. It may create chart images, optionally call a vision-capable model, validate structured analysis, and persist evidence for later evaluation. It has no authority to place, size, modify, delay, approve, reject, or close a trade.

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
- H1 data is truncated before indicator calculation as an extra look-ahead guard
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

When remote analysis is enabled, the model must return one strict structured record containing:

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

When remote analysis is enabled, the model is instructed to:

- remain observational
- use no data after `as_of_utc`
- independently evaluate structure, regime, liquidity, setup quality, invalidation, and targets
- prefer HOLD/abstain when evidence is conflicting
- never guess the withheld deterministic AAQTS decision

Prompt versions are persisted with every observation so prompt experiments can be evaluated independently.

## Scheduling policy

Phase AI-1 deduplicates by symbol and completed M15 candle. Repeated five-minute engine scans must not create duplicate evidence or duplicate remote calls for the same completed candle.

Default policy is `only_actionable=true`: only deterministic BUY/SELL candidates are submitted to the observer. HOLD candles are marked seen and skipped. This default controls storage, cost, and concurrency while the evaluation dataset is being established.

The observer uses a bounded worker pool. When all observer workers are busy, the deterministic trading loop is never made to wait.

## Capture-only mode

AAQTS now separates local evidence collection from paid remote model usage:

- `AAQTS_AI_CHART_ENABLED=true` enables local observer work.
- `AAQTS_AI_CHART_REMOTE_ENABLED=false` hard-disables all OpenAI/API requests.
- In capture-only mode, actionable candidates still produce the causal M15/H1 charts and `input.json`.
- `capture.json` and a `CAPTURED` row in `observations.jsonl` confirm successful local collection.
- No `analysis.json` is expected until remote analysis is deliberately re-enabled.

The Windows demo launcher currently runs in **capture-only mode** so dataset collection continues with zero API usage.

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
        ├── capture.json        # capture-only mode
        ├── analysis.json       # remote mode only
        └── error.json          # only when an observation fails
```

`input.json` stores the causal snapshot and deterministic comparison record separately. `capture.json` marks successful local-only evidence collection. `analysis.json` stores the validated AI result plus response metadata/usage when remote analysis is enabled. `observations.jsonl` is an append-only compact index for later evaluation.

Secrets and API keys are never written to these evidence files.

## Configuration

The reusable package remains disabled by default. Remote API usage is also independently disabled by default.

```text
AAQTS_AI_CHART_ENABLED=false
AAQTS_AI_CHART_REMOTE_ENABLED=false
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
```

For Windows demo runtime, `scripts/windows/set-openai-api-key.ps1` prompts with hidden input and stores only Windows-DPAPI ciphertext at:

```text
runtime/secrets/openai_api_key.dpapi
```

In capture-only mode, `start-demo-engine.ps1` does **not** decrypt that saved key into the process environment. The encrypted key remains stored for a future deliberate remote-analysis activation.

Do not commit a real API key.

## Optional dependency

Install the AI rendering extras with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

The remote client intentionally uses Python's standard HTTP library so Phase AI-1 does not depend on a particular OpenAI Python SDK version.

## Current implementation boundary

The Phase AI-1 package, causal snapshot contract, renderer, structured schema, Responses API client, evidence store, async observer, capture-only switch, lazy integration bridge, Windows DPAPI key storage, router hook, and regression tests are implemented.

The observer hook runs **after** `RegimeStrategyRouter` has produced the deterministic routed decision. The bridge receives the exact lower/higher frames and a copy of the deterministic decision for local comparison evidence. The observer return value is ignored; no AI result is returned to strategy, portfolio risk, execution, or position management.

Only when all of the following are true can an observation be scheduled:

1. `AAQTS_AI_CHART_ENABLED=true`.
2. A higher-timeframe frame is available.
3. The configured bounded worker pool has capacity.
4. With the default policy, the deterministic result is BUY or SELL.
5. The completed M15 candle has not already been observed for that symbol.

A remote request additionally requires `AAQTS_AI_CHART_REMOTE_ENABLED=true` and a usable local API key.

## Activation acceptance criteria

Before treating the VPS capture observer as active:

1. Existing deterministic test suite remains green.
2. Phase AI-1 tests prove H1 data is causally truncated to the M15 snapshot timestamp.
3. Duplicate scans of one completed M15 candle create at most one observation.
4. HOLD candidates create no observer work with the default actionable-only policy.
5. Capture-only mode never calls the remote client.
6. The deterministic comparison record remains separated from remote model input.
7. Invalid response identity/schema is rejected and logged when remote mode is used.
8. Observer failure cannot interrupt or reject a deterministic trade.
9. No execution or risk module imports the AI chart-analysis result.
10. At least one actionable VPS candidate produces `input.json`, both chart PNGs, `capture.json`, and a `CAPTURED` row in `observations.jsonl` without a new quota error.

## Next phase after data collection

Once sufficient observations exist, an outcome evaluator will attach forward-only labels such as 1/3/6/12-bar returns, MFE, MAE, TP/SL ordering, and realized/normalized R. AAQTS-alone performance can then be compared with later AI agreement/disagreement buckets before any confirmation-mode authority is considered.
