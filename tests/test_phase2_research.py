import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtesting.experiments import ExperimentTracker
from data.historical import (
    HistoricalDataError,
    HistoricalDataStore
)
from data.market_data import MarketData
from data.timeframes import TimeframeError
from strategy.multi_timeframe import (
    MultiTimeframeAnalyzer,
    TimeframeHierarchy
)


def raw_market(
    periods=12,
    frequency="h",
    start="2024-01-01T00:00:00Z"
):
    index = pd.date_range(
        start,
        periods=periods,
        freq=frequency
    )
    values = np.arange(periods, dtype=float)
    close = 100.0 + values * 0.1 + np.sin(values) * 0.05
    open_ = close - 0.02

    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.1,
            "low": np.minimum(open_, close) - 0.1,
            "close": close,
            "volume": 1000.0 + values
        },
        index=index
    )


def analyzed_higher_frame():
    data = raw_market(periods=280, frequency="h")
    data["close_time"] = data.index + pd.Timedelta(hours=1)
    data.attrs["timeframe"] = "1h"
    return data


def bullish_lower_frame(decision_time):
    close = pd.Timestamp(decision_time)
    return pd.DataFrame({
        "open_time": [
            close - pd.Timedelta(minutes=30),
            close - pd.Timedelta(minutes=15)
        ],
        "close_time": [
            close - pd.Timedelta(minutes=15),
            close
        ],
        "open": [101.0, 99.8],
        "high": [101.2, 101.5],
        "low": [99.7, 99.5],
        "close": [100.0, 101.3],
        "volume": [1000.0, 1200.0]
    })


def test_standard_timeframe_hierarchy_is_strict():
    hierarchy = TimeframeHierarchy.standard()

    assert hierarchy.levels == ("1d", "4h", "1h", "15m")

    with pytest.raises(TimeframeError, match="greater"):
        TimeframeHierarchy(("15m", "1h"))

    with pytest.raises(TimeframeError, match="greater"):
        TimeframeHierarchy(("1h", "1h"))


def test_analyzer_rejects_invalid_pair_configuration():
    with pytest.raises(TimeframeError, match="greater"):
        MultiTimeframeAnalyzer(
            higher_timeframe="15m",
            lower_timeframe="1h"
        )


def test_as_of_selector_includes_exact_close_boundary():
    data = pd.DataFrame({
        "close_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-01T11:00:00Z",
            "2024-01-01T12:00:00Z"
        ]),
        "open": [1.0, 2.0, 3.0],
        "high": [2.0, 3.0, 4.0],
        "low": [0.0, 1.0, 2.0],
        "close": [1.5, 2.5, 3.5]
    })
    analyzer = MultiTimeframeAnalyzer()

    selected = analyzer.select_as_of(
        data,
        "2024-01-01T11:00:00Z",
        "1h"
    )

    assert len(selected) == 2
    assert selected["close_time"].iloc[-1] == pd.Timestamp(
        "2024-01-01T11:00:00Z"
    )


def test_incomplete_higher_timeframe_candle_is_excluded():
    data = raw_market(
        periods=3,
        frequency="h",
        start="2024-01-01T09:00:00Z"
    )

    selected = MultiTimeframeAnalyzer().select_as_of(
        data,
        "2024-01-01T11:30:00Z",
        "1h"
    )

    assert len(selected) == 2
    assert selected["close_time"].max() == pd.Timestamp(
        "2024-01-01T11:00:00Z"
    )


def test_regular_hourly_candles_are_accepted_by_shared_timeframe_contract():
    frame = raw_market(periods=3, frequency="h")
    frame.attrs["timeframe"] = "1h"

    selected = MultiTimeframeAnalyzer().select_as_of(
        frame,
        "2024-01-01T01:00:00Z",
        "1h"
    )

    assert len(selected) == 1
    assert selected["close_time"].tolist() == [
        pd.Timestamp("2024-01-01T01:00:00Z"),
    ]


def test_future_higher_timeframe_mutation_cannot_change_decision():
    higher = analyzed_higher_frame()
    decision_time = higher["close_time"].iloc[239]
    lower = bullish_lower_frame(decision_time)
    mutated = higher.copy(deep=True)
    future = mutated["close_time"] > decision_time
    mutated.loc[future, "open"] = 10000.0
    mutated.loc[future, "high"] = 20000.0
    mutated.loc[future, "low"] = 1.0
    mutated.loc[future, "close"] = 2.0
    analyzer = MultiTimeframeAnalyzer(
        higher_timeframe="1h",
        lower_timeframe="15m"
    )

    original_result = analyzer.analyze(
        higher,
        lower,
        decision_time=decision_time
    )
    mutated_result = analyzer.analyze(
        mutated,
        lower,
        decision_time=decision_time
    )

    assert original_result == mutated_result


def test_hierarchy_aligns_every_level_to_one_decision_time():
    frames = {
        "1d": raw_market(4, "D"),
        "4h": raw_market(12, "4h"),
        "1h": raw_market(48, "h"),
        "15m": raw_market(192, "15min")
    }
    decision_time = pd.Timestamp("2024-01-02T12:00:00Z")

    aligned = TimeframeHierarchy.standard().align(
        frames,
        decision_time
    )

    assert set(aligned) == {"1d", "4h", "1h", "15m"}
    assert all(
        frame.empty
        or frame["close_time"].max() <= decision_time
        for frame in aligned.values()
    )


def test_duplicate_and_non_monotonic_mtf_timestamps_are_rejected():
    duplicate = pd.DataFrame({
        "close_time": pd.to_datetime([
            "2024-01-01T10:00:00Z",
            "2024-01-01T10:00:00Z"
        ]),
        "open": [1.0, 1.0],
        "high": [2.0, 2.0],
        "low": [0.0, 0.0],
        "close": [1.0, 1.0]
    })
    non_monotonic = duplicate.copy()
    non_monotonic["close_time"] = pd.to_datetime([
        "2024-01-01T11:00:00Z",
        "2024-01-01T10:00:00Z"
    ])
    analyzer = MultiTimeframeAnalyzer()

    with pytest.raises(TimeframeError, match="unique"):
        analyzer.select_as_of(
            duplicate,
            "2024-01-01T12:00:00Z",
            "1h"
        )

    with pytest.raises(TimeframeError, match="monotonic"):
        analyzer.select_as_of(
            non_monotonic,
            "2024-01-01T12:00:00Z",
            "1h"
        )


def test_timestamped_data_cannot_fall_back_to_legacy_alignment():
    higher = raw_market(20, "h")
    lower = pd.DataFrame({
        "open": [1.0, 1.0],
        "high": [2.0, 2.0],
        "low": [0.0, 0.0],
        "close": [1.0, 1.0]
    })

    with pytest.raises(TimeframeError):
        MultiTimeframeAnalyzer().analyze(higher, lower)


def test_legacy_untimed_analyzer_call_remains_supported():
    higher = raw_market(240, "h").reset_index(drop=True)
    lower = bullish_lower_frame(
        "2024-02-01T00:00:00Z"
    ).drop(columns=["open_time", "close_time"])

    result = MultiTimeframeAnalyzer().analyze(
        higher,
        lower
    )

    assert set(result) == {"higher_trend", "confirmation"}


def test_versioned_cache_round_trip_is_reproducible(tmp_path):
    store = HistoricalDataStore(tmp_path / "cache")
    data = raw_market(6, "h")

    first = store.save(
        data,
        "EURUSD=X",
        "1h",
        source="synthetic"
    )
    second = store.save(
        data.copy(deep=True),
        "EURUSD=X",
        "1h",
        source="synthetic"
    )
    loaded = store.load(
        "EURUSD=X",
        "1h",
        first.dataset_version
    )

    assert first == second
    assert store.list_versions("EURUSD=X", "1h") == [
        first.dataset_version
    ]
    assert len(loaded) == len(data)
    assert loaded.attrs["timeframe"] == "1h"
    assert loaded["close_time"].iloc[-1] == (
        data.index[-1] + pd.Timedelta(hours=1)
    )


def test_csv_replay_validates_expected_dataset_version(tmp_path):
    store = HistoricalDataStore(tmp_path / "cache")
    metadata = store.save(
        raw_market(5, "h"),
        "GBPUSD=X",
        "1h",
        source="synthetic"
    )
    csv_path = (
        tmp_path
        / "cache"
        / "GBPUSD_X"
        / "1h"
        / f"{metadata.dataset_version}.csv"
    )

    replay = store.load_csv(
        csv_path,
        "1h",
        expected_version=metadata.dataset_version
    )

    assert len(replay) == 5

    with pytest.raises(HistoricalDataError, match="version"):
        store.load_csv(
            csv_path,
            "1h",
            expected_version="ohlcv-v1-wrong"
        )


def test_cache_integrity_failure_is_detected(tmp_path):
    store = HistoricalDataStore(tmp_path / "cache")
    metadata = store.save(
        raw_market(4, "h"),
        "USDJPY=X",
        "1h",
        source="synthetic"
    )
    csv_path = (
        tmp_path
        / "cache"
        / "USDJPY_X"
        / "1h"
        / f"{metadata.dataset_version}.csv"
    )
    csv_path.write_bytes(csv_path.read_bytes() + b"\n")

    with pytest.raises(HistoricalDataError, match="integrity"):
        store.load(
            "USDJPY=X",
            "1h",
            metadata.dataset_version
        )


def test_dataset_snapshot_excludes_incomplete_candles(tmp_path):
    store = HistoricalDataStore(tmp_path / "cache")
    data = raw_market(3, "h")

    metadata = store.save(
        data,
        "AUDUSD=X",
        "1h",
        source="synthetic",
        as_of="2024-01-01T02:00:00Z"
    )

    assert metadata.rows == 2
    assert metadata.end_time == pd.Timestamp(
        "2024-01-01T02:00:00Z"
    ).isoformat()


def test_market_data_falls_back_to_local_cache_offline(
    tmp_path,
    monkeypatch
):
    market = MarketData(
        cache_dir=tmp_path / "cache",
        cache_downloads=True
    )
    market.history.save(
        raw_market(5, "h"),
        "EURUSD=X",
        "1h",
        source="fixture"
    )

    def unavailable(symbol, interval):
        raise RuntimeError("offline")

    monkeypatch.setattr(market, "_download", unavailable)

    replay = market.download_data(
        "EURUSD=X",
        "1h"
    )

    assert len(replay) == 5
    assert "close_time" in replay.columns


def test_successful_download_is_cached_with_dataset_version(
    tmp_path,
    monkeypatch
):
    market = MarketData(
        cache_dir=tmp_path / "cache",
        cache_downloads=True
    )
    downloaded = raw_market(4, "h")
    monkeypatch.setattr(
        market,
        "_download",
        lambda symbol, interval: downloaded.copy(deep=True)
    )

    result = market.download_data(
        "GBPUSD=X",
        "1h",
        as_of="2024-01-01T04:00:00Z"
    )
    versions = market.history.list_versions(
        "GBPUSD=X",
        "1h"
    )

    assert len(result) == 4
    assert len(versions) == 1
    assert market.history.metadata(
        "GBPUSD=X",
        "1h",
        versions[0]
    ).source == "yahoo"


def test_cached_replay_honors_historical_as_of(
    tmp_path,
    monkeypatch
):
    market = MarketData(
        cache_dir=tmp_path / "cache",
        cache_downloads=True
    )
    market.history.save(
        raw_market(5, "h"),
        "EURUSD=X",
        "1h",
        source="fixture"
    )

    def unavailable(symbol, interval):
        raise RuntimeError("offline")

    monkeypatch.setattr(market, "_download", unavailable)

    replay = market.download_data(
        "EURUSD=X",
        "1h",
        as_of="2024-01-01T02:00:00Z"
    )

    assert len(replay) == 2
    assert replay["close_time"].max() == pd.Timestamp(
        "2024-01-01T02:00:00Z"
    )


def test_experiment_report_tracks_dataset_parameters_and_metrics(
    tmp_path
):
    store = HistoricalDataStore(tmp_path / "cache")
    dataset = store.save(
        raw_market(5, "h"),
        "EURUSD=X",
        "1h",
        source="fixture"
    )
    tracker = ExperimentTracker(tmp_path / "experiments")
    trades = [
        {
            "type": "EXIT",
            "profit": 10.0,
            "r_multiple": 1.0,
            "starting_equity": 1000.0,
            "equity": 1010.0
        },
        {
            "type": "EXIT",
            "profit": -5.0,
            "r_multiple": -0.5,
            "equity": 1005.0
        }
    ]

    record = tracker.record(
        "baseline",
        dataset,
        {"risk_percent": 1.0, "threshold": 35},
        trades,
        initial_equity=1000.0
    )
    repeated = tracker.record(
        "baseline",
        dataset,
        {"threshold": 35, "risk_percent": 1.0},
        trades,
        initial_equity=1000.0
    )
    saved = json.loads(
        (
            tmp_path
            / "experiments"
            / f"{record.experiment_id}.json"
        ).read_text(encoding="utf-8")
    )

    assert repeated == record
    assert saved["dataset_version"] == dataset.dataset_version
    assert saved["dataset_sha256"] == dataset.content_sha256
    assert saved["timeframe"] == "1h"
    assert saved["parameters"] == {
        "risk_percent": 1.0,
        "threshold": 35
    }
    assert saved["trades"] == 2
    assert saved["completed_trades"] == 2
    assert saved["win_rate"] == pytest.approx(50.0)
    assert saved["profit_factor"] == pytest.approx(2.0)
    assert saved["max_drawdown"] == pytest.approx(5.0)
    assert saved["expectancy"] == pytest.approx(2.5)


def test_strategy_comparison_is_stable_and_exportable(tmp_path):
    store = HistoricalDataStore(tmp_path / "cache")
    dataset = store.save(
        raw_market(4, "h"),
        "XAUUSD",
        "1h",
        source="fixture"
    )
    tracker = ExperimentTracker(tmp_path / "experiments")
    first = tracker.record(
        "strategy-b",
        dataset,
        {"variant": "b"},
        [],
        initial_equity=1000.0
    )
    second = tracker.record(
        "strategy-a",
        dataset,
        {"variant": "a"},
        [],
        initial_equity=1000.0
    )

    comparison = tracker.compare([first, second])
    path = tracker.save_comparison([first, second])

    assert comparison["experiment_id"].is_monotonic_increasing
    assert path.exists()
    assert list(pd.read_csv(path)["strategy"]) == list(
        comparison["strategy"]
    )
