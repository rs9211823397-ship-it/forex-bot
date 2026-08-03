import pandas as pd

from structure.market_structure import (
    BEARISH,
    BULLISH,
    SWING_HIGH,
    MarketStructure,
)


def bullish_structure_frame():
    high = [
        1.10, 1.12, 1.15, 1.11, 1.18, 1.20, 1.16,
        1.22, 1.25, 1.21, 1.28, 1.30, 1.26, 1.32,
    ]
    low = [
        1.05, 1.08, 1.10, 1.06, 1.12, 1.15, 1.10,
        1.18, 1.20, 1.16, 1.22, 1.25, 1.21, 1.27,
    ]
    close_time = pd.date_range(
        "2024-01-01 01:00",
        periods=len(high),
        freq="h",
        tz="UTC",
    )
    return pd.DataFrame(
        {
            "close_time": close_time,
            "high": high,
            "low": low,
            "close": high,
        }
    )


def test_swing_is_unavailable_until_confirmation_candle_closes():
    frame = pd.DataFrame(
        {
            "close_time": pd.date_range(
                "2024-01-01 01:00",
                periods=5,
                freq="h",
                tz="UTC",
            ),
            "high": [1.0, 2.0, 3.0, 2.0, 1.0],
            "low": [0.5, 1.0, 1.5, 1.0, 0.5],
            "close": [0.8, 1.8, 2.8, 1.8, 0.8],
        }
    )
    structure = MarketStructure(lookback=1)

    before = structure.state(
        frame,
        decision_time=frame["close_time"].iloc[2],
    )
    confirmed = structure.state(
        frame,
        decision_time=frame["close_time"].iloc[3],
    )

    assert not before.swings
    assert confirmed.swings[0].type == SWING_HIGH
    assert confirmed.swings[0].formed_at == frame["close_time"].iloc[2]
    assert confirmed.swings[0].confirmed_at == frame["close_time"].iloc[3]


def test_future_mutation_cannot_change_historical_structure_state():
    frame = bullish_structure_frame()
    decision_time = frame["close_time"].iloc[10]
    mutated = frame.copy(deep=True)
    future = mutated["close_time"] > decision_time
    mutated.loc[future, "high"] = 99.0
    mutated.loc[future, "low"] = 0.01
    mutated.loc[future, "close"] = 50.0

    expected = MarketStructure(lookback=1).state(
        frame,
        decision_time=decision_time,
    )
    actual = MarketStructure(lookback=1).state(
        mutated,
        decision_time=decision_time,
    )

    assert actual == expected


def test_bos_is_close_confirmed_and_uses_confirmed_level():
    frame = bullish_structure_frame()
    structure = MarketStructure(lookback=1)

    state = structure.state(frame)

    assert state.trend == BULLISH
    assert state.latest_bos is not None
    assert state.latest_bos.direction == BULLISH
    assert state.latest_bos.level == 1.30
    assert structure.detect_bos(frame) == "BULLISH BOS"

    wick_only = frame.copy(deep=True)
    wick_only.loc[wick_only.index[-1], "close"] = 1.29
    assert structure.detect_bos(wick_only) == "NO BOS"
    assert (
        structure.detect_false_breakout(wick_only)
        == "BULLISH FALSE BREAKOUT"
    )


def test_choch_requires_prior_trend_and_is_not_also_bos():
    frame = bullish_structure_frame()
    frame.loc[len(frame)] = {
        "close_time": frame["close_time"].iloc[-1]
        + pd.Timedelta(hours=1),
        "high": 1.28,
        "low": 1.15,
        "close": 1.18,
    }
    structure = MarketStructure(lookback=1)

    state = structure.state(frame)

    assert state.trend == BEARISH
    assert state.latest_choch is not None
    assert state.latest_choch.direction == BEARISH
    assert state.latest_bos is None
    assert structure.detect_choch(frame) == "BEARISH CHoCH"
    assert structure.detect_bos(frame) == "NO BOS"

    no_prior_trend = frame.tail(3).reset_index(drop=True)
    assert (
        structure.detect_choch(no_prior_trend)
        == "NO CHoCH"
    )


def test_repeated_break_does_not_duplicate_structure_event():
    frame = bullish_structure_frame()
    frame.loc[len(frame)] = {
        "close_time": frame["close_time"].iloc[-1]
        + pd.Timedelta(hours=1),
        "high": 1.34,
        "low": 1.28,
        "close": 1.33,
    }
    state = MarketStructure(lookback=1).state(frame)

    level_breaks = [
        event
        for event in state.breaks
        if event.event == "BOS" and event.level == 1.30
    ]
    assert len(level_breaks) == 1


def test_equal_highs_and_lows_are_deterministic_non_swings():
    frame = pd.DataFrame(
        {
            "high": [1.0, 2.0, 2.0, 2.0, 1.0],
            "low": [0.0, -1.0, -1.0, -1.0, 0.0],
            "close": [0.5, 1.0, 1.0, 1.0, 0.5],
        }
    )
    structure = MarketStructure(lookback=1)

    first = structure.swing_events(frame)
    second = structure.swing_events(frame.copy(deep=True))

    assert first == second == ()


def test_event_stream_is_chronological_and_alternating():
    events = MarketStructure(lookback=1).swing_events(
        bullish_structure_frame()
    )

    assert all(
        left.confirmed_index <= right.confirmed_index
        for left, right in zip(events, events[1:])
    )
    assert all(
        left.type != right.type
        for left, right in zip(events, events[1:])
    )
