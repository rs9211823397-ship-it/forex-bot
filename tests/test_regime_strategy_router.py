import logging

import pandas as pd

from strategy.regime_detector import (
    REGIME_BREAKOUT,
    REGIME_LOW_VOLATILITY,
    REGIME_RANGE,
    REGIME_TREND_UP,
)
from strategy.regime_router import RegimeStrategyRouter


class StaticDetector:
    def __init__(self, regime, *, direction="NEUTRAL", confidence=75, risk=1.0):
        self.result = {
            "regime": regime,
            "direction": direction,
            "confidence": confidence,
            "risk_multiplier": risk,
            "reasons": ["fixture regime"],
        }

    def detect(self, data):
        return dict(self.result)


class StubTrendEngine:
    def __init__(self, signal="BUY"):
        self.signal = signal
        self.calls = 0

    def generate_analysis(self, data, symbol, higher_tf=None):
        self.calls += 1
        return {
            "signal": self.signal,
            "confidence": 80,
            "score": 80,
            "reasons": ["existing causal trend pipeline"],
            "decision_summary": {
                "positive": ["existing causal trend pipeline"],
                "warnings": [],
            },
        }


class StubMtf:
    def __init__(self, regime="NEUTRAL"):
        self.regime = regime

    def get_regime(self, higher_tf, decision_time=None, timeframe=None):
        return self.regime


def router(detector, *, trend=None, htf="NEUTRAL"):
    return RegimeStrategyRouter(
        trend or StubTrendEngine(),
        higher_timeframe="1h",
        lower_timeframe="15m",
        detector=detector,
        mtf_analyzer=StubMtf(htf),
    )


def range_reentry_frame(side="BUY"):
    if side == "BUY":
        rows = [
            {
                "open": 97.0,
                "high": 97.5,
                "low": 94.5,
                "close": 95.0,
                "RSI": 30.0,
                "BB_UPPER": 104.0,
                "BB_LOWER": 96.0,
                "ATR": 1.0,
            },
            {
                "open": 96.0,
                "high": 97.5,
                "low": 95.5,
                "close": 97.0,
                "RSI": 35.0,
                "BB_UPPER": 103.5,
                "BB_LOWER": 96.5,
                "ATR": 1.0,
            },
        ]
    else:
        rows = [
            {
                "open": 103.0,
                "high": 105.5,
                "low": 102.5,
                "close": 105.0,
                "RSI": 70.0,
                "BB_UPPER": 104.0,
                "BB_LOWER": 96.0,
                "ATR": 1.0,
            },
            {
                "open": 104.0,
                "high": 104.5,
                "low": 102.5,
                "close": 103.0,
                "RSI": 65.0,
                "BB_UPPER": 103.5,
                "BB_LOWER": 96.5,
                "ATR": 1.0,
            },
        ]
    frame = pd.DataFrame(rows)
    frame["close_time"] = pd.date_range(
        "2026-01-01T00:15:00Z", periods=len(frame), freq="15min"
    )
    return frame


def range_no_entry_frame():
    frame = range_reentry_frame("BUY").copy()
    frame.loc[0, "close"] = 97.0
    frame.loc[1, "close"] = 97.1
    frame.loc[1, "open"] = 97.0
    frame.loc[1, "RSI"] = 50.0
    return frame


def breakout_frame():
    rows = []
    for index in range(20):
        close = 100.0 + (index % 3) * 0.1
        rows.append(
            {
                "open": close - 0.1,
                "high": 100.8,
                "low": 99.2,
                "close": close,
                "ATR": 1.0,
                "ADX": 22.0,
            }
        )
    rows.append(
        {
            "open": 100.5,
            "high": 102.3,
            "low": 100.2,
            "close": 102.0,
            "ATR": 1.0,
            "ADX": 30.0,
        }
    )
    frame = pd.DataFrame(rows)
    frame["close_time"] = pd.date_range(
        "2026-01-01T00:15:00Z", periods=len(frame), freq="15min"
    )
    return frame


def breakout_no_entry_frame():
    frame = breakout_frame().copy()
    frame.loc[frame.index[-1], "close"] = 100.6
    frame.loc[frame.index[-1], "high"] = 100.8
    frame.loc[frame.index[-1], "open"] = 100.5
    return frame


def test_trend_regime_delegates_to_existing_causal_engine():
    trend = StubTrendEngine("BUY")
    result = router(
        StaticDetector(REGIME_TREND_UP, direction="BULLISH", risk=1.0),
        trend=trend,
    ).generate_analysis(range_reentry_frame(), "EURUSD=X")

    assert trend.calls == 1
    assert result["signal"] == "BUY"
    assert result["strategy"] == "TREND"
    assert result["risk_multiplier"] == 1.0
    assert result["regime_confidence"] == 75.0


def test_range_router_requires_confirmed_band_reentry_and_reduces_risk():
    result = router(
        StaticDetector(REGIME_RANGE, confidence=70, risk=0.5)
    ).generate_analysis(range_reentry_frame("BUY"), "EURUSD=X")

    assert result["signal"] == "BUY"
    assert result["strategy"] == "RANGE_REVERSION"
    assert result["risk_multiplier"] == 0.5
    assert result["confidence"] == 70
    assert result["regime_confidence"] == 70.0
    assert result["decision_report"]["approved"] is True


def test_range_router_supports_bearish_reentry():
    result = router(
        StaticDetector(REGIME_RANGE, confidence=70, risk=0.5)
    ).generate_analysis(range_reentry_frame("SELL"), "EURUSD=X")

    assert result["signal"] == "SELL"
    assert result["score"] < 0


def test_range_hold_does_not_report_regime_confidence_as_trade_confidence(caplog):
    caplog.set_level(logging.INFO)
    result = router(
        StaticDetector(REGIME_RANGE, confidence=78, risk=0.5)
    ).generate_analysis(range_no_entry_frame(), "CAD=X")

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0
    assert result["regime_confidence"] == 78.0
    assert result["risk_multiplier"] == 0.0
    assert "Range detected but no confirmed Bollinger/RSI re-entry" in result["reasons"]
    assert "ROUTED HOLD detail CAD=X" in caplog.text
    assert "regime_confidence=78.0" in caplog.text
    assert "trade_confidence=0" in caplog.text


def test_range_buy_is_allowed_when_higher_timeframe_is_bullish():
    result = router(
        StaticDetector(REGIME_RANGE, confidence=70, risk=0.5),
        htf="BULLISH",
    ).generate_analysis(
        range_reentry_frame("BUY"),
        "EURUSD=X",
        higher_tf=pd.DataFrame({"close": [1.0]}),
    )

    assert result["signal"] == "BUY"
    assert result["risk_multiplier"] == 0.5
    assert result["confidence"] == 70
    assert result["higher_timeframe_regime"] == "BULLISH"


def test_range_sell_is_blocked_when_higher_timeframe_is_bullish():
    result = router(
        StaticDetector(REGIME_RANGE, confidence=70, risk=0.5),
        htf="BULLISH",
    ).generate_analysis(
        range_reentry_frame("SELL"),
        "EURUSD=X",
        higher_tf=pd.DataFrame({"close": [1.0]}),
    )

    assert result["signal"] == "HOLD"
    assert result["risk_multiplier"] == 0.0
    assert result["confidence"] == 0
    assert "Range SELL conflicts with BULLISH higher timeframe" in result["reasons"]


def test_range_sell_is_allowed_when_higher_timeframe_is_bearish():
    result = router(
        StaticDetector(REGIME_RANGE, confidence=70, risk=0.5),
        htf="BEARISH",
    ).generate_analysis(
        range_reentry_frame("SELL"),
        "EURUSD=X",
        higher_tf=pd.DataFrame({"close": [1.0]}),
    )

    assert result["signal"] == "SELL"
    assert result["risk_multiplier"] == 0.5
    assert result["confidence"] == 70
    assert result["higher_timeframe_regime"] == "BEARISH"


def test_breakout_requires_range_close_atr_adx_and_htf_compatibility():
    detector = StaticDetector(
        REGIME_BREAKOUT,
        direction="BULLISH",
        confidence=82,
        risk=0.8,
    )
    accepted = router(detector, htf="BULLISH").generate_analysis(
        breakout_frame(),
        "BTC-USD",
        higher_tf=pd.DataFrame({"close": [1.0]}),
    )
    blocked = router(detector, htf="BEARISH").generate_analysis(
        breakout_frame(),
        "BTC-USD",
        higher_tf=pd.DataFrame({"close": [1.0]}),
    )

    assert accepted["signal"] == "BUY"
    assert accepted["risk_multiplier"] == 0.8
    assert accepted["confidence"] == 82
    assert accepted["regime_confidence"] == 82.0
    assert blocked["signal"] == "HOLD"
    assert blocked["confidence"] == 0
    assert blocked["risk_multiplier"] == 0.0


def test_breakout_hold_keeps_regime_confidence_separate():
    detector = StaticDetector(
        REGIME_BREAKOUT,
        direction="BULLISH",
        confidence=77,
        risk=0.8,
    )
    result = router(detector, htf="BULLISH").generate_analysis(
        breakout_no_entry_frame(),
        "ETH-USD",
        higher_tf=pd.DataFrame({"close": [1.0]}),
    )

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0
    assert result["regime_confidence"] == 77.0
    assert result["risk_multiplier"] == 0.0
    assert "Breakout regime lacks a strong close/ATR/ADX confirmation" in result["reasons"]


def test_low_volatility_fails_closed():
    result = router(
        StaticDetector(REGIME_LOW_VOLATILITY, confidence=90, risk=0.0)
    ).generate_analysis(range_reentry_frame(), "EURUSD=X")

    assert result["signal"] == "HOLD"
    assert result["strategy"] == "NO_TRADE"
    assert result["risk_multiplier"] == 0.0
    assert result["confidence"] == 0
    assert result["regime_confidence"] == 90.0
