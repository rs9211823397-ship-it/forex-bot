from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from strategy.market_regime import (
    BEARISH,
    BULLISH,
    HIGH_VOLATILITY,
    LOW_VOLATILITY,
    NEUTRAL,
    NORMAL_VOLATILITY,
    RANGING,
    TRENDING,
    MarketRegimeClassifier,
    MarketRegimeConfig,
    MarketRegimeError,
)


TEST_CONFIG = MarketRegimeConfig(
    ema_fast_period=3,
    ema_medium_period=5,
    ema_slow_period=8,
    atr_period=3,
    adx_period=3,
    realized_volatility_period=3,
    volatility_baseline_period=8,
    minimum_history=20,
    adx_trend_threshold=25.0,
    minimum_ema_separation_atr=0.10,
    high_volatility_ratio=1.50,
    low_volatility_ratio=0.75,
)


def candle_frame(close, ranges=None, start="2024-01-01"):
    close = np.asarray(close, dtype=float)
    ranges = (
        np.full(len(close), 1.0)
        if ranges is None
        else np.asarray(ranges, dtype=float)
    )
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + ranges / 2.0
    low = np.minimum(open_, close) - ranges / 2.0
    close_time = pd.date_range(
        start,
        periods=len(close),
        freq="h",
        tz="UTC",
    )

    return pd.DataFrame(
        {
            "close_time": close_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
    )


def classify(frame, decision_time=None):
    return MarketRegimeClassifier(TEST_CONFIG).classify(
        frame,
        (
            decision_time
            if decision_time is not None
            else frame["close_time"].iloc[-1]
        ),
    )


def test_bullish_trend_requires_adx_alignment_and_separation():
    frame = candle_frame(np.linspace(100.0, 130.0, 40))

    result = classify(frame)

    assert result.regime == TRENDING
    assert result.trend_state == TRENDING
    assert result.volatility_state == NORMAL_VOLATILITY
    assert result.direction == BULLISH
    assert "ADX_TREND_STRENGTH" in result.reason_codes
    assert "EMA_BULLISH_ALIGNMENT" in result.reason_codes
    assert "EMA_SEPARATION_CONFIRMED" in result.reason_codes


def test_bearish_trend_is_classified_symmetrically():
    frame = candle_frame(np.linspace(130.0, 100.0, 40))

    result = classify(frame)

    assert result.regime == TRENDING
    assert result.trend_state == TRENDING
    assert result.direction == BEARISH
    assert "EMA_BEARISH_ALIGNMENT" in result.reason_codes


def test_range_has_neutral_direction():
    frame = candle_frame(np.full(40, 100.0))

    result = classify(frame)

    assert result.regime == RANGING
    assert result.trend_state == RANGING
    assert result.direction == NEUTRAL
    assert "ADX_BELOW_TREND_THRESHOLD" in result.reason_codes
    assert "REGIME_RANGING" in result.reason_codes


def test_high_volatility_is_relative_to_prior_history():
    close = np.full(40, 100.0)
    close[-3:] = (95.0, 106.0, 94.0)
    ranges = np.ones(40)
    ranges[-3:] = 8.0
    frame = candle_frame(close, ranges)

    result = classify(frame)

    assert result.regime == HIGH_VOLATILITY
    assert result.volatility_state == HIGH_VOLATILITY
    assert result.components.atr_ratio > 1.5
    assert result.components.realized_volatility_ratio > 1.5
    assert "VOLATILITY_EXPANSION" in result.reason_codes


def test_low_volatility_is_relative_to_prior_history():
    close = 100.0 + np.resize(
        np.array((0.0, 1.5, -1.0, 2.0)),
        40,
    )
    close[-3:] = (100.01, 100.00, 100.01)
    ranges = np.full(40, 2.0)
    ranges[-3:] = 0.05
    frame = candle_frame(close, ranges)

    result = classify(frame)

    assert result.regime == LOW_VOLATILITY
    assert result.volatility_state == LOW_VOLATILITY
    assert result.components.volatility_ratio < 0.75
    assert "VOLATILITY_COMPRESSION" in result.reason_codes


def test_exact_close_boundary_includes_current_and_excludes_future():
    frame = candle_frame(np.linspace(100.0, 130.0, 42))
    decision_time = frame["close_time"].iloc[-2]

    result = classify(frame, decision_time)

    assert result.candle_close_time == decision_time
    assert result.candles_used == len(frame) - 1


def test_future_candle_mutation_cannot_change_historical_regime():
    frame = candle_frame(np.linspace(100.0, 130.0, 45))
    decision_time = frame["close_time"].iloc[39]
    mutated = frame.copy(deep=True)
    future = mutated["close_time"] > decision_time
    mutated.loc[future, "open"] = 1000.0
    mutated.loc[future, "high"] = 2500.0
    mutated.loc[future, "low"] = 0.01
    mutated.loc[future, "close"] = 2000.0

    original = classify(frame, decision_time)
    changed = classify(mutated, decision_time)

    assert original == changed


def test_precomputed_future_leaking_columns_are_ignored():
    frame = candle_frame(np.linspace(100.0, 130.0, 40))
    frame["ADX"] = np.linspace(0.0, 100000.0, len(frame))
    frame["ATR"] = -999.0
    frame["EMA_20"] = frame["close"].shift(-1)

    result = classify(frame)
    clean = classify(frame.drop(columns=["ADX", "ATR", "EMA_20"]))

    assert result == clean


def test_output_is_immutable_explainable_and_serializable():
    frame = candle_frame(np.linspace(100.0, 130.0, 40))
    result = classify(frame)

    with pytest.raises(FrozenInstanceError):
        result.regime = RANGING

    with pytest.raises(FrozenInstanceError):
        result.components.adx = 0.0

    serialized = result.to_dict()
    assert serialized["regime"] == TRENDING
    assert serialized["active_regimes"] == [
        TRENDING,
        NORMAL_VOLATILITY,
    ]
    assert isinstance(serialized["components"]["adx"], float)
    assert serialized["decision_time"].endswith("+00:00")


@pytest.mark.parametrize(
    "changes, message",
    (
        ({"ema_fast_period": 0}, "positive integer"),
        ({"ema_fast_period": 5}, "fast < medium < slow"),
        ({"low_volatility_ratio": 1.0}, "below 1"),
        ({"high_volatility_ratio": 1.0}, "above 1"),
    ),
)
def test_invalid_configuration_fails_closed(changes, message):
    values = {
        name: getattr(TEST_CONFIG, name)
        for name in TEST_CONFIG.__dataclass_fields__
    }
    values.update(changes)

    with pytest.raises(MarketRegimeError, match=message):
        MarketRegimeConfig(**values)


def test_insufficient_closed_history_fails_closed():
    frame = candle_frame(np.linspace(100.0, 110.0, 10))

    with pytest.raises(MarketRegimeError, match="Insufficient"):
        classify(frame)


@pytest.mark.parametrize(
    "mutator, message",
    (
        (
            lambda frame: frame.drop(columns=["high"]),
            "Missing OHLC",
        ),
        (
                lambda frame: frame.assign(
                    close=lambda value: value["close"].mask(
                        value.index == value.index[-1],
                        np.nan,
                    )
                ),
            "finite",
        ),
        (
            lambda frame: frame.assign(
                high=lambda value: value["low"] - 1.0
            ),
            "relationships",
        ),
    ),
)
def test_invalid_historical_ohlc_fails_closed(mutator, message):
    frame = candle_frame(np.linspace(100.0, 130.0, 40))

    with pytest.raises(MarketRegimeError, match=message):
        classify(mutator(frame))


def test_duplicate_and_non_monotonic_timestamps_fail_closed():
    duplicate = candle_frame(np.linspace(100.0, 130.0, 40))
    duplicate.loc[
        duplicate.index[-1],
        "close_time",
    ] = duplicate["close_time"].iloc[-2]
    non_monotonic = candle_frame(np.linspace(100.0, 130.0, 40))
    last = non_monotonic["close_time"].iloc[-1]
    previous = non_monotonic["close_time"].iloc[-2]
    non_monotonic.loc[
        non_monotonic.index[-1],
        "close_time",
    ] = previous
    non_monotonic.loc[
        non_monotonic.index[-2],
        "close_time",
    ] = last

    with pytest.raises(MarketRegimeError, match="unique"):
        classify(duplicate)

    with pytest.raises(MarketRegimeError, match="monotonic"):
        classify(non_monotonic)
