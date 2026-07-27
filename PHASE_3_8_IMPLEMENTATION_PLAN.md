# Phase 3–8 Implementation Plan

## Scope and invariants

The Phase 1 execution/accounting contract and the Phase 2 historical-data
contracts are the baseline. Later phases may add policy, classification, and
production interfaces, but must not reintroduce same-candle execution,
look-ahead access, unclosed higher-timeframe candles, or inconsistent cash P&L.

Public entry points remain compatible:

- `BacktestEngine(data, strategy)`
- `SignalEngine.analyze(data, higher_tf_data=None)`
- `RiskManager.position_size(...)`
- the paper-trading start/pause/resume/stop surface

## Phase 3 — Advanced signal engine

Files:

- `strategy/market_regime.py`
- `strategy/multi_timeframe.py`
- `strategy/pipeline.py`
- `strategy/signal_engine.py`
- `ai/trade_quality.py`
- focused tests under `tests/`

Changes:

- classify `TRENDING`, `RANGING`, `HIGH_VOLATILITY`, and `LOW_VOLATILITY`
  from closed-candle ADX, ATR, EMA structure, and point-in-time volatility;
- make the HTF analyzer return directional regime only;
- enforce ordered, fail-closed eligibility gates before ranking;
- make each indicator evidence role unique and keep quality distinct from a
  calibrated probability;
- preserve the existing `SignalEngine` return schema.

Success:

- future LTF/HTF mutations do not change historical decisions;
- an HTF result never depends on LTF trigger candles;
- duplicate evidence cannot create multiple votes;
- legacy imports and outputs remain valid.

## Phase 4 — Market structure intelligence

Files:

- `structure/market_structure.py`
- structure-focused tests under `tests/`

Changes:

- replace separate high/low lists internally with an ordered event stream;
- record swing `formed_at` and `confirmed_at`;
- maintain protected high/low and `BULLISH`, `BEARISH`, `NEUTRAL` state;
- emit close-confirmed BOS or CHoCH once per broken protected level;
- add causal support/resistance, continuation/reversal, false-breakout, and
  quality outputs through backward-compatible wrappers.

Success:

- unconfirmed swings never influence a decision;
- BOS and CHoCH cannot be emitted for the same break;
- repeated closes beyond one level do not duplicate events;
- existing `MarketStructure` methods remain callable.

## Phase 5 — Contextual price action

Files:

- `price_action/`
- `strategy/contextual_integration.py`
- `strategy/setup_detector.py`
- `strategy/trigger_detector.py`
- `strategy/pipeline.py`
- contextual tests under `tests/`

Changes:

- retain the existing causal contextual engine;
- use the shared close-time/as-of contract;
- refresh expired setups deterministically;
- require setup, regime, structure, valid location, and momentum context;
- select exactly one canonical trigger from ATR-normalized candle evidence.

Success:

- a candle pattern cannot create direction;
- expired setups cannot remain permanently deadlocked;
- context uses only confirmed state and closed candles;
- the public signal API remains unchanged.

## Phase 6 — Risk protection and execution

Files:

- `risk/`
- `execution/`
- compatibility integration in `main.py` and paper modules
- risk/execution tests under `tests/`

Changes:

- add post-signal `ALLOW`, `BLOCK`, and optional `REDUCE_SIZE` policies;
- enforce configurable daily/weekly loss, drawdown, consecutive-loss,
  position-count, correlation, session, volatility, and news controls;
- add explicit order states, acknowledgements, idempotency, retry policy, and
  reconciliation interfaces;
- leave all new policy switches disabled where necessary to preserve behavior.

Success:

- risk never creates a direction;
- normal sizing remains within the Phase 1 cost-inclusive risk cap;
- order transitions are deterministic and invalid transitions fail closed;
- existing paper APIs keep working.

## Phase 7 — AI-ready trade quality layer

Files:

- `ai/`
- research-only tests and dataset contracts

Changes:

- create immutable point-in-time feature snapshots;
- record decision context and completed outcomes separately;
- add versioned dataset and model/filter interfaces;
- keep the model layer disabled by default and do not train a model.

Success:

- no outcome field is available during feature construction;
- feature schemas and dataset versions are reproducible;
- the layer can rank or veto only when explicitly enabled;
- baseline production decisions are unchanged while disabled.

## Phase 8 — Production architecture

Files:

- broker and account abstraction modules
- `execution/`
- `config/`
- `logs/`
- controller integration and production tests

Changes:

- define broker-neutral orders, fills, positions, and account snapshots;
- add multi-account isolation, reconciliation, lifecycle control, structured
  event logging, configuration validation, and persistent emergency stops;
- provide non-live adapters/stubs for future MT5 and exchange integrations.

Success:

- accounts and persistence paths cannot collide;
- retries are idempotent and reconciliation detects divergence;
- emergency stop prevents new orders without inventing closes;
- configuration and active sources validate offline.

## Validation after implementation

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error pytest tests -v
PYTHONPYCACHEPREFIX=/tmp/forex-bot-compileall python -m compileall .
git diff --check
```

The complete validation is run twice after integration. Only a clean second run
is eligible for the requested commit and push.
