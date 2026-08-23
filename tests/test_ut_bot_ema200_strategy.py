from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.ut_bot_ema200 import BUY, HOLD, SELL, UTBotConfig, UTBotStrategy


def _frame(closes) -> pd.DataFrame:
    close = np.asarray(closes, dtype=float)
    index = pd.date_range("2026-01-01", periods=len(close), freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "volume": 100.0,
            "close_time": index + pd.Timedelta(minutes=15),
        },
        index=index,
    )
    frame.attrs.update({"source": "MT5", "fresh": True})
    return frame


def _strategy() -> UTBotStrategy:
    return UTBotStrategy(
        UTBotConfig(
            key_value=3.0,
            atr_period=10,
            signal_confidence=80,
        )
    )


def test_ut_bot_buy_requires_only_latest_confirmed_cross():
    strategy = _strategy()
    prices = np.r_[np.linspace(100.0, 90.0, 210), 100.0, 110.0, 120.0, 130.0]
    featured = strategy.add_indicators(_frame(prices))
    buy_indexes = np.flatnonzero(featured["UTBOT_SIGNAL"].to_numpy() == BUY)
    assert len(buy_indexes) >= 1

    decision = strategy.generate_analysis(
        featured.iloc[: buy_indexes[0] + 1],
        "EURUSD=X",
        higher_tf=None,
    )

    assert decision["signal"] == BUY
    assert decision["exit_signal"] == BUY
    assert decision["confidence"] == 80
    assert decision["strategy"] == "UT_BOT"
    assert decision["higher_timeframe_regime"] == "NOT_USED"
    assert decision["signal_id"].startswith("EURUSD=X|")
    assert decision["signal_id"].endswith("|BUY")
    assert decision["reasons"] == ["Confirmed UT Bot BUY crossover"]


def test_opposite_ut_cross_is_actionable_without_ema_filter():
    strategy = _strategy()
    prices = np.r_[
        np.linspace(100.0, 90.0, 210),
        100.0,
        110.0,
        120.0,
        130.0,
        140.0,
        135.0,
        125.0,
        115.0,
        105.0,
    ]
    featured = strategy.add_indicators(_frame(prices))
    buy_positions = np.flatnonzero(featured["UTBOT_SIGNAL"].to_numpy() == BUY)
    assert len(buy_positions) >= 1
    sell_positions = np.flatnonzero(featured["UTBOT_SIGNAL"].to_numpy() == SELL)
    sell_positions = sell_positions[sell_positions > buy_positions[0]]
    assert len(sell_positions) >= 1
    end = int(sell_positions[0])

    decision = strategy.generate_analysis(featured.iloc[: end + 1], "ETH-USD")

    assert decision["signal"] == SELL
    assert decision["signal_id"].endswith("|SELL")
    assert decision["exit_signal"] == SELL
    assert decision["reasons"] == ["Confirmed UT Bot SELL crossover"]


def test_no_cross_is_the_only_normal_indicator_hold_reason():
    strategy = _strategy()
    featured = strategy.add_indicators(_frame(np.linspace(100.0, 120.0, 240)))

    decision = strategy.generate_analysis(featured, "BTC-USD")

    assert decision["signal"] == HOLD
    assert decision["reasons"][0] == "No new UT Bot crossover on the latest closed candle"
    assert not any(
        name in " ".join(decision["reasons"]).upper()
        for name in ("RSI", "ADX", "MACD", "BOLLINGER", "REGIME", "CONTEXT")
    )


def test_ut_bot_feature_history_is_causal_and_preserves_provider_metadata():
    strategy = _strategy()
    base = _frame(np.sin(np.arange(280) / 5.0) * 5.0 + 100.0)
    changed = base.copy()
    changed.attrs.update(base.attrs)
    changed.loc[changed.index[240] :, ["open", "high", "low", "close"]] *= 2.0

    first = strategy.add_indicators(base)
    second = strategy.add_indicators(changed)

    pd.testing.assert_frame_equal(
        first.loc[first.index[:240], ["ATR", "UTBOT_TRAILING_STOP", "UTBOT_SIGNAL"]],
        second.loc[second.index[:240], ["ATR", "UTBOT_TRAILING_STOP", "UTBOT_SIGNAL"]],
    )
    assert first.attrs["source"] == "MT5"
    assert first.attrs["fresh"] is True


def test_strategy_requires_no_higher_timeframe_or_legacy_indicator_columns():
    strategy = _strategy()
    featured = strategy.add_indicators(_frame(np.linspace(100.0, 120.0, 240)))

    assert strategy.requires_higher_timeframe is False
    for removed in (
        "RSI",
        "STOCH_RSI",
        "MACD",
        "MACD_SIGNAL",
        "ADX",
        "BB_UPPER",
        "BB_LOWER",
        "SUPERTREND",
        "EMA_200",
    ):
        assert removed not in featured.columns
