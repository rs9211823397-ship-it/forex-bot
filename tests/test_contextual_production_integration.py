import inspect
import unittest

import pandas as pd

from strategy.decision import SetupResult
from strategy.pipeline import SignalPipeline
from strategy.setup_detector import SetupDetector
from strategy.signal_engine import SignalEngine


BASE_TIME = pd.Timestamp("2024-02-01T00:00:00Z")


def timestamp(hour):
    return BASE_TIME + pd.Timedelta(hours=hour)


class StubCandles:

    def __init__(self, direction):
        self.direction = direction

    def analyze(self, data):
        if self.direction == "BUY":
            return [
                "Bullish engulfing",
                "STRONG BULLISH CANDLE"
            ]

        return [
            "Bearish engulfing",
            "STRONG BEARISH CANDLE"
        ]


class StubMarketStructure:

    def __init__(self, direction):
        self.direction = direction
        self.lookback = 1

    def trend(self, data):
        return (
            "BULLISH"
            if self.direction == "BUY"
            else "BEARISH"
        )

    def detect_bos(self, data):
        return (
            "BULLISH BOS"
            if self.direction == "BUY"
            else "BEARISH BOS"
        )

    def detect_choch(self, data):
        return "NO CHoCH"

    def find_swings(self, data):
        return (
            [{"index": 1, "price": 110.0}],
            [{"index": 2, "price": 100.0}]
        )


class StubMultiTimeframe:

    def __init__(self, direction):
        self.direction = direction

    def analyze(self, higher_tf, lower_tf):
        return {
            "higher_trend": (
                "BULLISH"
                if self.direction == "BUY"
                else "BEARISH"
            ),
            "confirmation": self.direction
        }


def timed_data(direction, location="VALID"):
    rows = []

    for hour in range(8):
        rows.append({
            "close_time": timestamp(hour),
            "open": 104.0,
            "high": 105.0,
            "low": 103.0,
            "close": 104.2,
            "volume": 100.0,
            "VOL_SMA20": 90.0,
            "OBV": float(hour * 10),
            "ATR": 2.0,
            "ADX": 40.0,
            "EMA_20": 102.0,
            "EMA_50": 101.0,
            "EMA_200": 100.0,
            "SUPERTREND": True,
            "MACD": 1.0,
            "MACD_SIGNAL": 0.5,
            "RSI": 60.0,
            "STOCH_RSI": 50.0
        })

    data = pd.DataFrame(rows)

    if direction == "BUY" and location == "VALID":
        values = {
            "open": 103.8,
            "high": 105.0,
            "low": 101.0,
            "close": 104.5
        }

    elif direction == "BUY":
        values = {
            "open": 107.0,
            "high": 109.0,
            "low": 106.5,
            "close": 108.0
        }

    elif location == "VALID":
        values = {
            "open": 106.2,
            "high": 109.0,
            "low": 105.0,
            "close": 105.5
        }

    else:
        values = {
            "open": 103.0,
            "high": 103.5,
            "low": 101.0,
            "close": 102.0
        }

    for column, value in values.items():
        data.loc[data.index[-1], column] = value

    data.loc[data.index[-1], "volume"] = 120.0

    if direction == "SELL":
        data["EMA_20"] = 100.0
        data["EMA_50"] = 101.0
        data["EMA_200"] = 102.0
        data["SUPERTREND"] = False
        data["MACD"] = 0.5
        data["MACD_SIGNAL"] = 1.0
        data["RSI"] = 40.0

    data.attrs["decision_time"] = timestamp(7)
    return data


def higher_timeframe():
    return pd.DataFrame({
        "close_time": [
            timestamp(hour)
            for hour in range(8)
        ],
        "open": [100.0] * 8,
        "high": [101.0] * 8,
        "low": [99.0] * 8,
        "close": [100.5] * 8,
        "volume": [100.0] * 8
    })


def pipeline_for(direction):
    candles = StubCandles(direction)

    return SignalPipeline(
        market_structure=StubMarketStructure(direction),
        candles=candles,
        mtf=StubMultiTimeframe(direction)
    )


class ContextualProductionIntegrationTests(unittest.TestCase):

    def test_setup_formation_and_expiry_are_tracked_per_symbol(self):
        detector = SetupDetector(
            contextual_expiry_candles=3
        )
        bullish = SetupResult(trend_score=30)

        formed = detector.create_contextual_setup(
            setup=bullish,
            decision_time=timestamp(1),
            bar_duration=pd.Timedelta(hours=1),
            htf_regime="BULLISH",
            structure_trend="BULLISH",
            symbol="EURUSD=X"
        )
        refreshed_setup = detector.create_contextual_setup(
            setup=bullish,
            decision_time=timestamp(5),
            bar_duration=pd.Timedelta(hours=1),
            htf_regime="BULLISH",
            structure_trend="BULLISH",
            symbol="EURUSD=X"
        )

        self.assertIsNot(formed, refreshed_setup)
        self.assertEqual(formed.created_at, timestamp(1))
        self.assertEqual(formed.valid_until, timestamp(4))
        self.assertLess(
            formed.valid_until,
            timestamp(5)
        )
        self.assertEqual(
            refreshed_setup.created_at,
            timestamp(5)
        )
        self.assertEqual(
            refreshed_setup.valid_until,
            timestamp(8)
        )

        detector.create_contextual_setup(
            setup=SetupResult(trend_score=0),
            decision_time=timestamp(6),
            bar_duration=pd.Timedelta(hours=1),
            htf_regime="BULLISH",
            structure_trend="BULLISH",
            symbol="EURUSD=X"
        )
        reformed = detector.create_contextual_setup(
            setup=bullish,
            decision_time=timestamp(7),
            bar_duration=pd.Timedelta(hours=1),
            htf_regime="BULLISH",
            structure_trend="BULLISH",
            symbol="EURUSD=X"
        )

        self.assertEqual(reformed.created_at, timestamp(7))
        self.assertEqual(reformed.valid_until, timestamp(10))

    def test_context_receives_only_historical_closed_candles(self):
        data = timed_data("BUY")
        future = data.iloc[-1].copy()
        future["close_time"] = timestamp(8)
        future["close"] = 10000.0
        future["high"] = 10001.0
        data.loc[len(data)] = future
        data.attrs["decision_time"] = timestamp(7)
        pipeline = pipeline_for("BUY")

        pipeline.run(
            data,
            "BTC-USD",
            higher_timeframe()
        )
        context = pipeline.last_context

        self.assertEqual(context.closed_candle_count, 8)
        self.assertEqual(
            context.current_candle.close_time,
            timestamp(7)
        )
        self.assertLessEqual(
            context.current_candle.close_time,
            context.decision_time
        )

    def test_context_builder_receives_confirmed_states_only(self):
        pipeline = pipeline_for("BUY")

        pipeline.run(
            timed_data("BUY"),
            "BTC-USD",
            higher_timeframe()
        )
        context = pipeline.last_context

        self.assertLessEqual(
            context.htf_regime.confirmed_at,
            context.decision_time
        )
        self.assertLessEqual(
            context.structure.confirmed_at,
            context.decision_time
        )
        self.assertLessEqual(
            context.protected_swing_high.confirmed_at,
            context.decision_time
        )
        self.assertLessEqual(
            context.protected_swing_low.confirmed_at,
            context.decision_time
        )

    def test_contextual_trigger_never_creates_direction(self):
        data = timed_data("BUY")
        data["EMA_20"] = data["EMA_50"]
        pipeline = pipeline_for("BUY")

        result = pipeline.run(
            data,
            "BTC-USD",
            higher_timeframe()
        ).to_dict()

        self.assertEqual(result["signal"], "HOLD")
        self.assertEqual(
            pipeline.last_contextual_trigger.trigger,
            "NONE"
        )
        self.assertEqual(
            pipeline.last_contextual_trigger.direction,
            "NONE"
        )

    def test_existing_buy_setup_can_be_rejected(self):
        pipeline = pipeline_for("BUY")

        result = pipeline.run(
            timed_data("BUY", location="INVALID"),
            "BTC-USD",
            higher_timeframe()
        ).to_dict()

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["signal"], "HOLD")
        self.assertIn(
            "Contextual INVALID_LOCATION",
            result["reasons"]
        )

    def test_existing_sell_setup_can_be_rejected(self):
        pipeline = pipeline_for("SELL")

        result = pipeline.run(
            timed_data("SELL", location="INVALID"),
            "BTC-USD",
            higher_timeframe()
        ).to_dict()

        self.assertEqual(result["score"], -100)
        self.assertEqual(result["signal"], "HOLD")
        self.assertIn(
            "Contextual INVALID_LOCATION",
            result["reasons"]
        )

    def test_matching_context_confirms_existing_directions(self):
        buy_pipeline = pipeline_for("BUY")
        sell_pipeline = pipeline_for("SELL")

        buy = buy_pipeline.run(
            timed_data("BUY"),
            "BTC-USD",
            higher_timeframe()
        ).to_dict()
        sell = sell_pipeline.run(
            timed_data("SELL"),
            "BTC-USD",
            higher_timeframe()
        ).to_dict()

        self.assertEqual(buy["signal"], "BUY")
        self.assertEqual(sell["signal"], "SELL")
        self.assertEqual(
            set(buy),
            {
                "signal",
                "confidence",
                "score",
                "reasons",
                "decision_summary"
            }
        )
        self.assertEqual(
            buy_pipeline.last_contextual_trigger.direction,
            "BUY"
        )
        self.assertEqual(
            sell_pipeline.last_contextual_trigger.direction,
            "SELL"
        )

    def test_future_candle_mutation_cannot_change_decision(self):
        baseline_data = timed_data("BUY")
        future = baseline_data.iloc[-1].copy()
        future["close_time"] = timestamp(8)
        baseline_data.loc[len(baseline_data)] = future
        baseline_data.attrs["decision_time"] = timestamp(7)
        mutated_data = baseline_data.copy(deep=True)
        mutated_data.attrs["decision_time"] = timestamp(7)
        mutated_data.loc[
            mutated_data.index[-1],
            [
                "open",
                "high",
                "low",
                "close",
                "ATR",
                "ADX",
                "EMA_20",
                "EMA_50",
                "EMA_200"
            ]
        ] = [
            10000.0,
            20000.0,
            1.0,
            15000.0,
            5000.0,
            1.0,
            -1000.0,
            5000.0,
            9000.0
        ]
        baseline_higher = higher_timeframe()
        higher_future = baseline_higher.iloc[-1].copy()
        higher_future["close_time"] = timestamp(8)
        baseline_higher.loc[len(baseline_higher)] = (
            higher_future
        )
        mutated_higher = baseline_higher.copy(deep=True)
        mutated_higher.loc[
            mutated_higher.index[-1],
            ["open", "high", "low", "close", "volume"]
        ] = [
            10000.0,
            20000.0,
            1.0,
            15000.0,
            999999.0
        ]

        baseline = pipeline_for("BUY").run(
            baseline_data,
            "BTC-USD",
            baseline_higher
        ).to_dict()
        mutated = pipeline_for("BUY").run(
            mutated_data,
            "BTC-USD",
            mutated_higher
        ).to_dict()

        self.assertEqual(baseline, mutated)

    def test_signal_engine_public_api_is_unchanged(self):
        self.assertEqual(
            str(inspect.signature(SignalEngine)),
            "()"
        )
        self.assertEqual(
            str(inspect.signature(SignalEngine.generate_signal)),
            "(self, data, symbol, higher_tf=None)"
        )

        result = SignalEngine().generate_signal(
            pd.DataFrame({
                "ADX": [20.0]
            }),
            "EURUSD=X"
        )

        self.assertEqual(
            set(result),
            {
                "signal",
                "confidence",
                "score",
                "reasons"
            }
        )
        self.assertEqual(result["signal"], "HOLD")


if __name__ == "__main__":
    unittest.main()
