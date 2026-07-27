"""Deterministic regression tests for directional signal eligibility."""

import inspect

import numpy as np
import pandas as pd

from ai.trade_quality import TradeQuality
from strategy.pipeline import SignalPipeline
from strategy.signal_engine import SignalEngine


class StubCandles:

    def __init__(self, patterns):
        self.patterns = patterns

    def analyze(self, data):
        return list(self.patterns)


class StubStructure:

    def __init__(
        self,
        trend="BULLISH",
        bos="BULLISH BOS",
        choch="NO CHoCH"
    ):
        self.trend_value = trend
        self.bos_value = bos
        self.choch_value = choch

    def trend(self, data):
        return self.trend_value

    def detect_bos(self, data):
        return self.bos_value

    def detect_choch(self, data):
        return self.choch_value


class StubMtf:

    def __init__(self, regime, confirmation):
        self.regime = regime
        self.confirmation = confirmation

    def analyze(self, higher_tf, lower_tf):
        return {
            "higher_trend": self.regime,
            "confirmation": self.confirmation
        }


def strategy_frame(direction="BUY", timestamped=False):
    data = pd.DataFrame({
        "open": [100.0, 100.2],
        "high": [100.6, 100.9],
        "low": [99.8, 100.0],
        "close": [100.2, 100.7],
        "volume": [100.0, 120.0],
        "VOL_SMA20": [90.0, 90.0],
        "OBV": [0.0, 20.0],
        "ADX": [40.0, 40.0],
        "EMA_20": [102.0, 102.0],
        "EMA_50": [101.0, 101.0],
        "EMA_200": [100.0, 100.0],
        "SUPERTREND": [True, True],
        "MACD": [1.0, 1.0],
        "MACD_SIGNAL": [0.5, 0.5],
        "RSI": [60.0, 60.0],
        "STOCH_RSI": [50.0, 50.0]
    })

    if direction == "SELL":
        data["EMA_20"] = 100.0
        data["EMA_50"] = 101.0
        data["EMA_200"] = 102.0
        data["SUPERTREND"] = False
        data["MACD"] = 0.5
        data["MACD_SIGNAL"] = 1.0
        data["RSI"] = 40.0

    if timestamped:
        data["close_time"] = pd.date_range(
            "2024-01-01T00:00:00Z",
            periods=len(data),
            freq="h"
        )

    return data


def higher_frame():
    return pd.DataFrame({
        "open": [100.0, 100.0],
        "high": [101.0, 101.0],
        "low": [99.0, 99.0],
        "close": [100.5, 100.5],
        "volume": [100.0, 100.0]
    })


def test_signal_engine_public_contract_is_preserved():
    assert str(inspect.signature(SignalEngine)) == "()"
    assert (
        str(inspect.signature(SignalEngine.generate_signal))
        == "(self, data, symbol, higher_tf=None)"
    )

    result = SignalEngine().generate_signal(
        pd.DataFrame({"ADX": [20.0]}),
        "EURUSD=X"
    )

    assert result == {
        "signal": "HOLD",
        "confidence": 0,
        "score": 0,
        "reasons": ["Weak market (ADX below 25)"]
    }


def test_opposite_higher_timeframe_is_a_hard_veto():
    pipeline = SignalPipeline(
        market_structure=StubStructure(
            trend="BEARISH",
            bos="BEARISH BOS"
        ),
        candles=StubCandles([
            "Bearish engulfing",
            "STRONG BEARISH CANDLE"
        ]),
        mtf=StubMtf("BULLISH", "BUY")
    )

    result = pipeline.run(
        strategy_frame("SELL"),
        "BTC-USD",
        higher_frame()
    ).to_dict()

    assert result["score"] <= -70
    assert result["signal"] == "HOLD"
    assert (
        "Rejected: Higher timeframe conflicts with setup"
        in result["reasons"]
    )


def test_opposite_choch_is_a_hard_veto():
    pipeline = SignalPipeline(
        market_structure=StubStructure(
            trend="BULLISH",
            bos="BULLISH BOS",
            choch="BEARISH CHoCH"
        ),
        candles=StubCandles([
            "Bullish engulfing",
            "BULLISH PIN BAR",
            "STRONG BULLISH CANDLE"
        ])
    )

    result = pipeline.run(
        strategy_frame(),
        "BTC-USD"
    ).to_dict()

    assert result["score"] >= 90
    assert result["signal"] == "HOLD"
    assert (
        "Rejected: Market structure conflicts with setup"
        in result["reasons"]
    )


def test_conflicting_evidence_does_not_inflate_quality():
    result = TradeQuality().evaluate(
        trend_score=30,
        momentum_score=-20,
        structure_score=-20,
        candle_score=10,
        volume_score=-15,
        adx=40,
        mtf_confirmed=True,
        direction="BUY",
        mtf_direction="SELL"
    )

    assert result["quality"] == 45
    assert not result["approved"]
    assert result["supporting_factors"] == [
        "trend",
        "price_action",
        "market_strength"
    ]
    assert set(result["rejected_factors"]) == {
        "Momentum conflicts with BUY",
        "Market structure conflicts with BUY",
        "Participation conflicts with BUY",
        "Higher timeframe conflicts with BUY"
    }


def test_sell_participation_requires_falling_obv_for_quality():
    pipeline = SignalPipeline()
    rising_obv = strategy_frame("SELL")
    falling_obv = strategy_frame("SELL")
    falling_obv.loc[falling_obv.index[-1], "OBV"] = -20.0

    rejected = pipeline._confirm_volume(
        rising_obv,
        "BTC-USD",
        rising_obv.iloc[-1],
        directional_score=-1,
        strict_direction=True
    )
    accepted = pipeline._confirm_volume(
        falling_obv,
        "BTC-USD",
        falling_obv.iloc[-1],
        directional_score=-1,
        strict_direction=True
    )

    assert rejected.ranking_score == 0
    assert "Weak volume" in rejected.reasons
    assert accepted.ranking_score == -15
    assert "Volume confirms SELL" in accepted.reasons


def test_pattern_without_setup_cannot_create_direction():
    data = strategy_frame()
    data["EMA_20"] = data["EMA_50"]
    pipeline = SignalPipeline(
        market_structure=StubStructure(),
        candles=StubCandles([
            "Bullish engulfing",
            "BULLISH PIN BAR",
            "STRONG BULLISH CANDLE"
        ])
    )

    result = pipeline.run(data, "BTC-USD").to_dict()

    assert result["signal"] == "HOLD"


def test_nan_feature_fails_closed():
    data = strategy_frame()
    data.loc[data.index[-1], "RSI"] = np.nan

    result = SignalEngine().generate_signal(
        data,
        "EURUSD=X"
    )

    assert result["signal"] == "HOLD"
    assert result["confidence"] == 0
    assert result["score"] == 0
    assert result["reasons"] == [
        "Invalid market data: non-finite strategy feature"
    ]


def test_duplicate_and_non_monotonic_timestamps_fail_closed():
    duplicate = strategy_frame(timestamped=True)
    duplicate.loc[
        duplicate.index[-1],
        "close_time"
    ] = duplicate.iloc[0]["close_time"]
    non_monotonic = strategy_frame(timestamped=True)
    non_monotonic.loc[
        non_monotonic.index[-1],
        "close_time"
    ] = (
        non_monotonic.iloc[0]["close_time"]
        - pd.Timedelta(hours=1)
    )

    duplicate_result = SignalEngine().generate_signal(
        duplicate,
        "EURUSD=X"
    )
    non_monotonic_result = SignalEngine().generate_signal(
        non_monotonic,
        "EURUSD=X"
    )

    assert duplicate_result["signal"] == "HOLD"
    assert duplicate_result["reasons"] == [
        "Invalid market data: duplicate timestamps"
    ]
    assert non_monotonic_result["signal"] == "HOLD"
    assert non_monotonic_result["reasons"] == [
        "Invalid market data: timestamps not monotonic"
    ]


def test_same_input_produces_identical_decision():
    data = strategy_frame()
    pipeline = SignalPipeline(
        market_structure=StubStructure(),
        candles=StubCandles([
            "Bullish engulfing",
            "STRONG BULLISH CANDLE"
        ])
    )

    first = pipeline.run(data.copy(deep=True), "BTC-USD").to_dict()
    second = pipeline.run(data.copy(deep=True), "BTC-USD").to_dict()

    assert first == second
