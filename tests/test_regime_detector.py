import numpy as np
import pandas as pd

from strategy.regime_detector import (
    MarketRegimeDetector,
    REGIME_BREAKOUT,
    REGIME_LOW_VOLATILITY,
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
)


def make_frame(direction="up", rows=140, adx=32.0, volatility=1.0):
    index = pd.RangeIndex(rows)
    if direction == "up":
        close = np.linspace(100, 130, rows)
    elif direction == "down":
        close = np.linspace(130, 100, rows)
    else:
        close = 115 + np.sin(np.linspace(0, 8 * np.pi, rows)) * volatility

    frame = pd.DataFrame(index=index)
    frame["close"] = close
    frame["high"] = close + volatility
    frame["low"] = close - volatility
    frame["ATR"] = volatility
    frame["ADX"] = adx
    frame["EMA_20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["EMA_50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame["EMA_200"] = frame["close"].ewm(span=200, adjust=False).mean()
    middle = frame["close"].rolling(20, min_periods=1).mean()
    width = max(volatility * 2, 0.01)
    frame["BB_MIDDLE"] = middle
    frame["BB_UPPER"] = middle + width
    frame["BB_LOWER"] = middle - width
    return frame


def test_detects_uptrend():
    result = MarketRegimeDetector().detect(make_frame("up"))
    assert result["regime"] == REGIME_TREND_UP
    assert result["direction"] == "BULLISH"


def test_detects_downtrend():
    result = MarketRegimeDetector().detect(make_frame("down"))
    assert result["regime"] == REGIME_TREND_DOWN
    assert result["direction"] == "BEARISH"


def test_detects_range_when_adx_is_weak():
    result = MarketRegimeDetector().detect(make_frame("range", adx=12.0))
    assert result["regime"] in {REGIME_RANGE, REGIME_LOW_VOLATILITY}


def test_detects_breakout_without_lookahead():
    frame = make_frame("range", adx=29.0)
    frame.loc[frame.index[-1], "close"] = frame["high"].iloc[-21:-1].max() + 5
    frame.loc[frame.index[-1], "high"] = frame.loc[frame.index[-1], "close"] + 1
    frame.loc[frame.index[-1], "low"] = frame.loc[frame.index[-1], "close"] - 1
    frame.loc[frame.index[-1], "ATR"] = 4.0
    middle = frame.loc[frame.index[-1], "BB_MIDDLE"]
    frame.loc[frame.index[-1], "BB_UPPER"] = middle + 8
    frame.loc[frame.index[-1], "BB_LOWER"] = middle - 8

    result = MarketRegimeDetector().detect(frame)
    assert result["regime"] == REGIME_BREAKOUT
    assert result["direction"] == "BULLISH"


def test_regime_filter_blocks_countertrend_and_unstructured_volatility():
    detector = MarketRegimeDetector()
    allowed, _ = detector.allows_signal({"regime": REGIME_TREND_UP, "direction": "BULLISH"}, "SELL")
    assert not allowed
    allowed, _ = detector.allows_signal({"regime": REGIME_TREND_UP, "direction": "BULLISH"}, "BUY")
    assert allowed


def test_missing_columns_raise_clear_error():
    frame = pd.DataFrame({"close": [1, 2, 3]})
    try:
        MarketRegimeDetector().detect(frame)
    except ValueError as exc:
        assert "Missing regime columns" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
