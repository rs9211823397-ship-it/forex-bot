import inspect
import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pandas as pd

from indicators.technical import TechnicalIndicators
from strategy.decision import SignalDecision
from strategy.pipeline import SignalPipeline
from strategy.setup_detector import SetupDetector
from strategy.signal_engine import SignalEngine
from strategy.trigger_detector import TriggerDetector
from strategy.validators import (
    validate_data,
    validate_market_regime,
    validate_risk
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "strategy_refactor_golden.json"
)


def synthetic_market(seed, drift, count=360):
    rng = np.random.default_rng(seed)
    steps = drift + rng.normal(0.0, 0.35, count)
    close = 100.0 + np.cumsum(steps)
    open_ = np.r_[close[0] - steps[0], close[:-1]]
    spread = rng.uniform(0.1, 0.7, count)

    return pd.DataFrame({
        "open": open_,
        "high": np.maximum(open_, close) + spread,
        "low": np.minimum(open_, close) - spread,
        "close": close,
        "volume": rng.integers(100, 2000, count).astype(float)
    })


def pipeline_frame():
    return pd.DataFrame({
        "open": [100.0, 100.2],
        "high": [100.6, 100.8],
        "low": [99.8, 100.0],
        "close": [100.2, 100.5],
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


class StubCandles:

    def __init__(self, patterns):
        self.patterns = patterns

    def analyze(self, data):
        return list(self.patterns)


class StubStructure:

    def __init__(self, trend, bos, choch="NO CHoCH"):
        self.trend_value = trend
        self.bos_value = bos
        self.choch_value = choch

    def trend(self, data):
        return self.trend_value

    def detect_bos(self, data):
        return self.bos_value

    def detect_choch(self, data):
        return self.choch_value


def forced_direction_frame(direction):
    data = pipeline_frame()

    if direction == "SELL":
        data["EMA_20"] = 100.0
        data["EMA_50"] = 101.0
        data["EMA_200"] = 102.0
        data["SUPERTREND"] = False
        data["MACD"] = 0.5
        data["MACD_SIGNAL"] = 1.0
        data["RSI"] = 40.0

    return data


class StrategyArchitectureTests(unittest.TestCase):

    def test_pipeline_order_is_explicit_and_deterministic(self):
        pipeline = SignalPipeline()

        pipeline.run(
            pipeline_frame(),
            "EURUSD=X"
        )

        self.assertEqual(
            pipeline.last_stage_order,
            SignalPipeline.STAGE_ORDER
        )
        self.assertEqual(
            SignalPipeline.STAGE_ORDER,
            (
                "data_validation",
                "market_regime",
                "market_structure",
                "setup_detection",
                "context_builder",
                "contextual_trigger",
                "momentum_confirmation",
                "trade_quality",
                "risk_validation",
                "final_decision"
            )
        )

    def test_pre_refactor_golden_outputs_preserve_public_contract(self):
        """
        Keep the Phase 5 API golden while allowing Phase 4 structure content.

        Causal swing confirmation intentionally changes structure-derived
        scores and reasons for timestamp-free HTF fixtures.  Those cases must
        remain deterministic and schema-compatible; fixtures without HTF
        input still require exact legacy output.
        """
        indicators = TechnicalIndicators()
        fixtures = json.loads(FIXTURE_PATH.read_text())

        for fixture in fixtures:
            with self.subTest(fixture["name"]):
                data = indicators.add_indicators(
                    synthetic_market(
                        fixture["seed"],
                        fixture["drift"]
                    )
                ).dropna()
                higher_tf = synthetic_market(
                    fixture["seed"] + 100,
                    fixture["drift"] * 2
                )

                higher_input = (
                    higher_tf
                    if fixture.get("higher_timeframe", False)
                    else None
                )
                result = SignalEngine().generate_signal(
                    data,
                    fixture["symbol"],
                    higher_input
                )
                repeated = SignalEngine().generate_signal(
                    data.copy(deep=True),
                    fixture["symbol"],
                    (
                        higher_input.copy(deep=True)
                        if higher_input is not None
                        else None
                    )
                )

                if higher_input is None:
                    self.assertEqual(result, fixture["result"])
                    continue

                self.assertEqual(result, repeated)
                self.assertEqual(
                    set(result),
                    set(fixture["result"])
                )
                self.assertIn(
                    result["signal"],
                    {"BUY", "SELL", "HOLD"}
                )
                self.assertIsInstance(result["confidence"], int)
                self.assertGreaterEqual(result["confidence"], 0)
                self.assertLessEqual(result["confidence"], 100)
                self.assertIsInstance(result["score"], int)
                self.assertIsInstance(result["reasons"], list)
                self.assertEqual(
                    set(result["decision_summary"]),
                    {"positive", "warnings"}
                )

    def test_signal_engine_public_api_and_early_output_are_compatible(self):
        self.assertEqual(
            str(inspect.signature(SignalEngine.generate_signal)),
            "(self, data, symbol, higher_tf=None)"
        )

        data = pipeline_frame()
        data.loc[data.index[-1], "ADX"] = 19.999

        self.assertEqual(
            SignalEngine().generate_signal(data, "EURUSD=X"),
            {
                "signal": "HOLD",
                "confidence": 0,
                "score": 0,
                "reasons": [
                    "Weak market (ADX below 20)"
                ]
            }
        )

    def test_decision_objects_are_immutable(self):
        decision = SignalDecision(
            signal="HOLD",
            confidence=0,
            score=0
        )

        with self.assertRaises(FrozenInstanceError):
            decision.signal = "BUY"

    def test_validators_preserve_boundary_and_selection_behavior(self):
        data = pipeline_frame()

        pd.testing.assert_series_equal(
            validate_data(data),
            data.iloc[-1]
        )
        self.assertFalse(
            validate_market_regime(pd.Series({"ADX": 19.999})).valid
        )
        self.assertTrue(
            validate_market_regime(pd.Series({"ADX": 20.0})).valid
        )
        self.assertEqual(
            validate_market_regime(
                pd.Series({"ADX": 19.999})
            ).reasons,
            ("Weak market (ADX below 20)",)
        )
        self.assertTrue(validate_risk().valid)

    def test_setup_detector_preserves_all_three_outcomes(self):
        detector = SetupDetector()

        bullish = detector.detect(pd.Series({
            "EMA_20": 3.0,
            "EMA_50": 2.0,
            "EMA_200": 1.0,
            "SUPERTREND": True
        }))
        bearish = detector.detect(pd.Series({
            "EMA_20": 1.0,
            "EMA_50": 2.0,
            "EMA_200": 3.0,
            "SUPERTREND": False
        }))
        neutral = detector.detect(pd.Series({
            "EMA_20": 2.0,
            "EMA_50": 2.0,
            "EMA_200": 1.0,
            "SUPERTREND": True
        }))

        self.assertEqual(
            (bullish.trend_score, bullish.reasons),
            (30, ("Bullish EMA alignment",))
        )
        self.assertEqual(
            (bearish.trend_score, bearish.reasons),
            (-30, ("Bearish EMA alignment",))
        )
        self.assertEqual(
            (neutral.trend_score, neutral.reasons),
            (0, ("Trend not aligned",))
        )

    def test_trigger_detector_preserves_pattern_stacking_rules(self):
        bullish = TriggerDetector(StubCandles([
            "Bullish engulfing",
            "BULLISH PIN BAR",
            "STRONG BULLISH CANDLE"
        ])).detect(pipeline_frame())
        bearish = TriggerDetector(StubCandles([
            "Bearish engulfing",
            "BEARISH PIN BAR",
            "STRONG BEARISH CANDLE"
        ])).detect(pipeline_frame())

        self.assertEqual(bullish.candle_score, 25)
        self.assertEqual(
            bullish.reasons,
            (
                "Bullish price action: Bullish engulfing",
                "Bullish price action: BULLISH PIN BAR",
                "Bullish momentum candle"
            )
        )
        self.assertEqual(bearish.candle_score, -25)
        self.assertEqual(
            bearish.reasons,
            (
                "Bearish price action: Bearish engulfing",
                "Bearish price action: BEARISH PIN BAR",
                "Bearish momentum candle"
            )
        )

    def test_buy_and_sell_decisions_preserve_legacy_scoring(self):
        bullish_pipeline = SignalPipeline(
            market_structure=StubStructure(
                "BULLISH",
                "BULLISH BOS"
            ),
            candles=StubCandles([
                "Bullish engulfing",
                "STRONG BULLISH CANDLE"
            ])
        )
        bearish_pipeline = SignalPipeline(
            market_structure=StubStructure(
                "BEARISH",
                "BEARISH BOS"
            ),
            candles=StubCandles([
                "Bearish engulfing",
                "STRONG BEARISH CANDLE"
            ])
        )

        bullish = bullish_pipeline.run(
            forced_direction_frame("BUY"),
            "BTC-USD"
        ).to_dict()
        bearish = bearish_pipeline.run(
            forced_direction_frame("SELL"),
            "BTC-USD"
        ).to_dict()

        self.assertEqual(
            bullish,
            {
                "signal": "BUY",
                "confidence": 100,
                "score": 100,
                "reasons": [
                    "Bullish EMA alignment",
                    "Bullish momentum confirmed",
                    "Bullish price action: Bullish engulfing",
                    "Bullish momentum candle",
                    "Volume confirms BUY",
                    "Market structure bullish",
                    "Bullish break of structure",
                    "Trade Quality: 100/100"
                ],
                "decision_summary": {
                    "positive": [
                        "Bullish EMA alignment",
                        "Bullish momentum confirmed",
                        "Bullish price action: Bullish engulfing",
                        "Bullish momentum candle",
                        "Market structure bullish",
                        "Bullish break of structure"
                    ],
                    "warnings": []
                }
            }
        )
        self.assertEqual(
            bearish,
            {
                "signal": "SELL",
                "confidence": 100,
                "score": -100,
                "reasons": [
                    "Bearish EMA alignment",
                    "Bearish momentum confirmed",
                    "Bearish price action: Bearish engulfing",
                    "Bearish momentum candle",
                    "Volume confirms SELL",
                    "Market structure bearish",
                    "Bearish break of structure",
                    "Trade Quality: 100/100"
                ],
                "decision_summary": {
                    "positive": [
                        "Bearish momentum confirmed"
                    ],
                    "warnings": [
                        "Bearish EMA alignment",
                        "Bearish momentum confirmed",
                        "Bearish price action: Bearish engulfing",
                        "Bearish momentum candle",
                        "Market structure bearish",
                        "Bearish break of structure"
                    ]
                }
            }
        )


if __name__ == "__main__":
    unittest.main()
