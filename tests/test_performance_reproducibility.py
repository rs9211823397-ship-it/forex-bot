import json

import numpy as np
import pandas as pd
import pytest

from backtesting.backtest_engine import BacktestEngine
from backtesting.experiments import ExperimentTracker
from data.historical import (
    CausalAsOfCache,
    HistoricalDataError,
    HistoricalDataStore
)
from risk.instrument import InstrumentSpec


def market_frame(periods=8):
    index = pd.date_range(
        "2024-01-01T00:00:00Z",
        periods=periods,
        freq="h"
    )
    close = 100.0 + np.arange(periods, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0 + np.arange(periods)
        },
        index=index
    )


def executable_frame():
    frame = market_frame(4).drop(columns=["volume"])
    frame.loc[:, "open"] = [100.0, 100.0, 100.5, 101.0]
    frame.loc[:, "high"] = [100.2, 100.5, 103.0, 101.5]
    frame.loc[:, "low"] = [99.8, 99.5, 100.0, 100.5]
    frame.loc[:, "close"] = [100.0, 100.2, 102.5, 101.2]
    frame["ATR"] = 1.0
    frame["ADX"] = 20.0
    return frame


def test_causal_prefix_cache_matches_uncached_as_of_selection():
    frame = market_frame()
    store = HistoricalDataStore()
    cached = store.prefix_cache(
        frame,
        "1h",
        max_entries=4
    )
    decision_time = "2024-01-01T04:00:00Z"

    expected = store.prepare(
        frame,
        "1h",
        as_of=decision_time
    )
    actual = cached.select(decision_time)

    pd.testing.assert_frame_equal(actual, expected)
    assert actual["close_time"].max() <= pd.Timestamp(
        decision_time
    )


def test_prefix_cache_isolated_from_future_and_consumer_mutations():
    frame = market_frame()
    cache = CausalAsOfCache(
        frame,
        "1h",
        max_entries=2
    )
    decision_time = "2024-01-01T04:00:00Z"
    before = cache.as_of(decision_time)

    frame.loc[frame.index[-1], "close"] = 999999.0
    after_future_mutation = cache.as_of(decision_time)

    pd.testing.assert_frame_equal(
        before,
        after_future_mutation
    )

    after_future_mutation.loc[
        after_future_mutation.index[0],
        "close"
    ] = -1.0
    after_consumer_mutation = cache.as_of(decision_time)

    pd.testing.assert_frame_equal(
        before,
        after_consumer_mutation
    )


def test_future_rows_cannot_change_historical_cached_selection():
    original = market_frame()
    mutated = original.copy()
    decision_time = pd.Timestamp("2024-01-01T04:00:00Z")
    future = (
        mutated.index + pd.Timedelta(hours=1)
        > decision_time
    )
    mutated.loc[future, "open"] += 5000.0
    mutated.loc[future, "high"] += 5000.0
    mutated.loc[future, "low"] += 5000.0
    mutated.loc[future, "close"] += 5000.0

    original_selection = CausalAsOfCache(
        original,
        "1h"
    ).select(decision_time)
    mutated_selection = CausalAsOfCache(
        mutated,
        "1h"
    ).select(decision_time)

    pd.testing.assert_frame_equal(
        original_selection,
        mutated_selection
    )


def test_prefix_cache_has_deterministic_bounded_lru_behavior():
    cache = CausalAsOfCache(
        market_frame(),
        "1h",
        max_entries=2
    )

    cache.select("2024-01-01T02:00:00Z")
    cache.select("2024-01-01T03:00:00Z")
    cache.select("2024-01-01T04:00:00Z")
    first_info = cache.cache_info()
    cache.select("2024-01-01T04:30:00Z")
    second_info = cache.cache_info()

    assert first_info["entries"] == 2
    assert first_info["misses"] == 3
    assert second_info["entries"] == 2
    assert second_info["hits"] == 1


def test_prefix_cache_enforces_total_cached_row_budget():
    cache = CausalAsOfCache(
        market_frame(),
        "1h",
        max_entries=8,
        max_cached_rows=5
    )

    cache.select("2024-01-01T02:00:00Z")
    cache.select("2024-01-01T04:00:00Z")
    cache.select("2024-01-01T08:00:00Z")
    info = cache.cache_info()

    assert info["cached_rows"] <= 5
    assert info["max_cached_rows"] == 5
    assert info["entries"] <= 2


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_prefix_cache_rejects_invalid_bounds(value):
    with pytest.raises(
        HistoricalDataError,
        match="max_entries"
    ):
        CausalAsOfCache(
            market_frame(),
            "1h",
            max_entries=value
        )


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_prefix_cache_rejects_invalid_row_budgets(value):
    with pytest.raises(
        HistoricalDataError,
        match="max_cached_rows"
    ):
        CausalAsOfCache(
            market_frame(),
            "1h",
            max_cached_rows=value
        )


def test_experiment_identity_captures_reproducibility_inputs(
    tmp_path
):
    store = HistoricalDataStore(tmp_path / "cache")
    dataset = store.save(
        market_frame(),
        "EURUSD",
        "1h",
        source="synthetic-v1"
    )
    tracker = ExperimentTracker(tmp_path / "experiments")
    instrument = InstrumentSpec(
        symbol="EURUSD",
        tick_size=0.0001,
        contract_multiplier=100000.0,
        quantity_step=0.01,
        minimum_quantity=0.01,
        spread=0.0001
    )
    common = {
        "strategy": "baseline",
        "dataset": dataset,
        "parameters": {"threshold": 35},
        "trades": [],
        "initial_equity": 10000.0,
        "source_revision": "revision-abc",
        "instrument_config": instrument,
        "execution_config": {
            "same_bar_policy": "STOP_FIRST"
        }
    }

    first = tracker.record(random_seed=7, **common)
    repeated = tracker.record(random_seed=7, **common)
    different_seed = tracker.record(random_seed=8, **common)

    assert first == repeated
    assert first.experiment_id != different_seed.experiment_id
    assert first.identity_sha256
    assert len(first.identity_sha256) == 64
    assert first.source_revision == "revision-abc"
    assert first.dataset_source == "synthetic-v1"
    assert first.random_seed == 7
    assert first.instrument_config["symbol"] == "EURUSD"
    assert first.execution_config == {
        "same_bar_policy": "STOP_FIRST"
    }


def test_experiment_artifacts_are_atomic_and_deterministic(
    tmp_path
):
    store = HistoricalDataStore(tmp_path / "cache")
    dataset = store.save(
        market_frame(),
        "EURUSD",
        "1h",
        source="fixture"
    )
    tracker = ExperimentTracker(tmp_path / "experiments")
    record = tracker.record(
        "baseline",
        dataset,
        {},
        [],
        1000.0,
        source_revision="revision-abc"
    )
    comparison = tracker.save_comparison([record])

    assert json.loads(
        (
            tmp_path
            / "experiments"
            / f"{record.experiment_id}.json"
        ).read_text(encoding="utf-8")
    ) == record.to_dict()
    assert comparison.read_bytes().endswith(b"\n")
    assert sorted(
        path.name
        for path in (tmp_path / "experiments").iterdir()
    ) == sorted([
        f"{record.experiment_id}.json",
        "comparison.csv"
    ])


def test_experiment_tracker_does_not_change_backtest_outcomes(
    tmp_path
):
    data = executable_frame()

    def strategy(position):
        return "BUY" if position == 0 else "HOLD"

    direct = BacktestEngine(
        data,
        strategy,
        force_close=True
    )
    expected_trades = direct.run()
    store = HistoricalDataStore(tmp_path / "cache")
    dataset = store.save(
        data,
        "EURUSD",
        "1h",
        source="fixture"
    )
    tracker = ExperimentTracker(tmp_path / "experiments")
    _, tracked = tracker.run_backtest(
        "baseline",
        dataset,
        {},
        data,
        strategy,
        source_revision="revision-abc",
        random_seed=123,
        force_close=True
    )

    assert tracked.trades == expected_trades
    assert tracked.equity_history == direct.equity_history
    assert tracked.balance == direct.balance


def test_legacy_experiment_manifest_remains_loadable(tmp_path):
    tracker = ExperimentTracker(tmp_path)
    payload = {
        "experiment_id": "experiment-legacy",
        "strategy": "legacy",
        "dataset_version": "ohlcv-v1-example",
        "dataset_sha256": "abc",
        "symbol": "EURUSD",
        "timeframe": "1h",
        "parameters": {},
        "trades": 0,
        "completed_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_percent": 0.0,
        "expectancy": 0.0,
        "average_r": 0.0,
        "ending_equity": 1000.0
    }
    path = tmp_path / "experiment-legacy.json"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8"
    )

    loaded = tracker.load("experiment-legacy")

    assert loaded.source_revision == "unversioned"
    assert loaded.random_seed == 0
    assert loaded.instrument_config == {}
