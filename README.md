# forex-bot
AI-powered modular Forex trading bot with risk management, backtesting, MT5 integration, and future AI signal generation.

## Release validation

Run the repository from the repository root.

- Backtest: `python -m backtesting.run_backtest`
- Research generation: `python -m backtesting.run_backtest`
- Tests: `python -m pytest -q`
- Preflight: `python scripts/preflight.py`

## Quick commands

```bash
python scripts/preflight.py
python -m pytest -q
python -m compileall .
git diff --check
python -m backtesting.run_backtest
```

## Strategy research foundation

Phase 2 adds causal multi-timeframe alignment, versioned local historical
datasets, CSV replay, and deterministic experiment reports.

### Timeframe contract

Timestamped production data is interpreted as candle-open time unless it has
an explicit `close_time` column. Higher-timeframe candles are available only
when `close_time <= decision_time`. The supported hierarchy is strictly
high-to-low, for example:

```python
from strategy.multi_timeframe import TimeframeHierarchy

hierarchy = TimeframeHierarchy(("1d", "4h", "1h", "15m"))
aligned = hierarchy.align(frames, decision_time)
```

Incomplete candles, duplicate timestamps, non-monotonic timestamps, and
invalid hierarchy ordering are rejected.

### Historical cache and CSV replay

Yahoo downloads are saved under the ignored `data/cache/` directory using a
content-addressed dataset version and SHA-256 manifest. If Yahoo is
unavailable, `MarketData` can replay the latest validated local version.

```python
from data.historical import HistoricalDataStore

store = HistoricalDataStore()
metadata = store.save(data, "EURUSD=X", "1h", source="broker")
replay = store.load(
    "EURUSD=X",
    "1h",
    metadata.dataset_version
)
```

Pass an explicit version to reproduce an experiment exactly. CSV replay also
supports `expected_version` integrity validation.

### Experiment tracking

```python
from backtesting.experiments import ExperimentTracker

tracker = ExperimentTracker()
record = tracker.record(
    strategy="baseline",
    dataset=metadata,
    parameters={"risk_percent": 1.0},
    trades=trades,
    initial_equity=1000.0,
    equity_curve=equity_curve
)
```

Each JSON report records the dataset hash/version, symbol, timeframe,
parameters, completed trades, win rate, profit factor, drawdown, expectancy,
average R, and ending equity. Comparison CSVs preserve stable experiment-ID
ordering and do not perform parameter optimization.
