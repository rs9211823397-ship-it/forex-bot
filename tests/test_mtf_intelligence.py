"""Deterministic tests for causal multi-timeframe regime intelligence."""

import numpy as np
import pandas as pd
import pytest

from data.timeframes import TimeframeError
from strategy.multi_timeframe import (
    MultiTimeframeAnalyzer,
    TimeframeHierarchy
)


def _frame(
    periods=260,
    timeframe="1h",
    start="2024-01-01T00:00:00Z",
    trend=0.04
):
    frequency = {
        "1d": "1D",
        "4h": "4h",
        "1h": "1h",
        "15m": "15min"
    }[timeframe]
    index = pd.date_range(start, periods=periods, freq=frequency)
    sequence = np.arange(periods, dtype=float)
    close = 100.0 + trend * sequence + np.sin(sequence / 4.0) * 0.2
    open_ = close - np.cos(sequence / 5.0) * 0.04
    result = pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.15,
            "low": np.minimum(open_, close) - 0.15,
            "close": close,
            "volume": 1000.0 + sequence
        },
        index=index
    )
    result.attrs["timeframe"] = timeframe
    return result


def _closed_lower(decision_time):
    decision = pd.Timestamp(decision_time)
    opens = pd.date_range(
        decision - pd.Timedelta(hours=1),
        periods=4,
        freq="15min"
    )
    values = np.array([100.0, 100.2, 99.9, 100.3])
    result = pd.DataFrame(
        {
            "open": values - 0.05,
            "high": values + 0.1,
            "low": values - 0.1,
            "close": values,
            "volume": [1000.0] * 4
        },
        index=opens
    )
    result.attrs["timeframe"] = "15m"
    return result


def test_standard_hierarchy_models_daily_to_fifteen_minutes():
    hierarchy = TimeframeHierarchy.standard()

    assert hierarchy.levels == ("1d", "4h", "1h", "15m")
    hierarchy.validate_pair("1d", "15m")
    hierarchy.validate_pair("4h", "1h")


@pytest.mark.parametrize(
    ("higher", "lower"),
    [("15m", "1h"), ("1h", "1h"), ("4h", "1d")]
)
def test_invalid_hierarchy_roles_are_rejected(higher, lower):
    with pytest.raises(TimeframeError):
        MultiTimeframeAnalyzer.production(higher, lower)


def test_exact_htf_close_is_available_and_incomplete_candle_is_excluded():
    frame = _frame(periods=4, timeframe="4h")
    analyzer = MultiTimeframeAnalyzer.production("4h", "15m")

    boundary = frame.index[1] + pd.Timedelta(hours=4)
    selected = analyzer.select_as_of(frame, boundary, "4h")

    assert len(selected) == 2
    assert selected["close_time"].iloc[-1] == boundary
    assert frame.index[2] + pd.Timedelta(hours=4) > boundary


def test_future_htf_mutation_cannot_change_historical_regime():
    higher = _frame()
    decision = higher.index[229] + pd.Timedelta(hours=1)
    lower = _closed_lower(decision)
    mutated = higher.copy(deep=True)
    future = mutated.index + pd.Timedelta(hours=1) > decision
    mutated.loc[future, ["open", "high", "low", "close"]] = [
        1.0,
        50000.0,
        0.01,
        2.0
    ]
    analyzer = MultiTimeframeAnalyzer.production("1h", "15m")

    original = analyzer.analyze(higher, lower, decision_time=decision)
    changed = analyzer.analyze(mutated, lower, decision_time=decision)

    assert original == changed


def test_lower_timeframe_price_action_never_changes_htf_output():
    higher = _frame()
    decision = higher.index[-1] + pd.Timedelta(hours=1)
    lower = _closed_lower(decision)
    opposite_pattern = lower.copy(deep=True)
    opposite_pattern.loc[:, ["open", "high", "low", "close"]] = [
        [10.0, 100.0, 1.0, 90.0],
        [90.0, 100.0, 1.0, 10.0],
        [10.0, 100.0, 1.0, 90.0],
        [90.0, 100.0, 1.0, 10.0]
    ]
    analyzer = MultiTimeframeAnalyzer.production("1h", "15m")

    original = analyzer.analyze(higher, lower, decision_time=decision)
    changed = analyzer.analyze(
        higher,
        opposite_pattern,
        decision_time=decision
    )

    assert original == changed
    assert original["higher_trend"] in {
        "BULLISH",
        "BEARISH",
        "NEUTRAL"
    }


def test_directional_alias_is_derived_only_from_regime():
    analyzer = MultiTimeframeAnalyzer.production()

    assert analyzer._compatibility_result("BULLISH") == {
        "higher_trend": "BULLISH",
        "confirmation": "BUY"
    }
    assert analyzer._compatibility_result("BEARISH") == {
        "higher_trend": "BEARISH",
        "confirmation": "SELL"
    }
    assert analyzer._compatibility_result("NEUTRAL") == {
        "higher_trend": "NEUTRAL",
        "confirmation": "HOLD"
    }


def test_production_and_research_modes_reject_untimed_frames():
    higher = _frame().reset_index(drop=True)
    lower = _closed_lower(
        "2024-02-01T00:00:00Z"
    ).reset_index(drop=True)

    for analyzer in (
        MultiTimeframeAnalyzer.production("1h", "15m"),
        MultiTimeframeAnalyzer.research("1h", "15m")
    ):
        with pytest.raises(TimeframeError, match="Untimed"):
            analyzer.analyze(higher, lower)


def test_deprecated_default_constructor_preserves_untimed_api():
    higher = _frame().reset_index(drop=True)
    lower = _closed_lower(
        "2024-02-01T00:00:00Z"
    ).reset_index(drop=True)

    result = MultiTimeframeAnalyzer().analyze(higher, lower)

    assert set(result) == {"higher_trend", "confirmation"}


def test_hierarchy_alignment_never_returns_future_candles():
    frames = {
        "1d": _frame(6, "1d"),
        "4h": _frame(36, "4h"),
        "1h": _frame(144, "1h"),
        "15m": _frame(576, "15m")
    }
    decision = pd.Timestamp("2024-01-05T12:00:00Z")

    aligned = TimeframeHierarchy.standard().align(frames, decision)

    assert all(
        frame.empty or frame["close_time"].max() <= decision
        for frame in aligned.values()
    )
