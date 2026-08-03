import unittest

import pandas as pd

from price_action.candle_metrics import (
    CandleSnapshot,
    calculate_candle_metrics
)
from price_action.context import (
    ContextEngine,
    ProtectedSwing,
    RegimeState,
    StructureState
)
from price_action.contextual_trigger import (
    ContextualTriggerEngine,
    SetupContext
)
from price_action.liquidity import LiquidityDetector
from price_action.trigger_priority import choose_trigger


BASE_TIME = pd.Timestamp("2024-01-01T00:00:00Z")


def timestamp(hour):
    return BASE_TIME + pd.Timedelta(hours=hour)


def frame(rows):
    return pd.DataFrame(rows)


def bullish_rejection_data():
    return frame([
        {
            "close_time": timestamp(1),
            "open": 105.0,
            "high": 105.5,
            "low": 103.5,
            "close": 104.0,
            "ATR": 2.0
        },
        {
            "close_time": timestamp(2),
            "open": 103.8,
            "high": 105.0,
            "low": 101.0,
            "close": 104.5,
            "ATR": 2.0
        }
    ])


def bearish_rejection_data():
    return frame([
        {
            "close_time": timestamp(1),
            "open": 105.0,
            "high": 106.5,
            "low": 104.5,
            "close": 106.0,
            "ATR": 2.0
        },
        {
            "close_time": timestamp(2),
            "open": 106.2,
            "high": 109.0,
            "low": 105.0,
            "close": 105.5,
            "ATR": 2.0
        }
    ])


def context_for(data, direction, decision_time=None):
    decision = decision_time or timestamp(2)
    state = (
        "BULLISH"
        if direction == "BUY"
        else "BEARISH"
    )

    return ContextEngine().build(
        data=data,
        decision_time=decision,
        htf_regime=RegimeState(
            regime=state,
            confirmed_at=timestamp(1)
        ),
        structure=StructureState(
            trend=state,
            confirmed_at=timestamp(1)
        ),
        protected_swing_high=ProtectedSwing(
            kind="HIGH",
            price=110.0,
            formed_at=timestamp(0),
            confirmed_at=timestamp(1)
        ),
        protected_swing_low=ProtectedSwing(
            kind="LOW",
            price=100.0,
            formed_at=timestamp(0),
            confirmed_at=timestamp(1)
        )
    )


def setup_for(direction, valid_until=None):
    return SetupContext(
        direction=direction,
        created_at=timestamp(1),
        valid_until=valid_until or timestamp(4)
    )


class ContextualPriceActionTests(unittest.TestCase):

    def test_atr_normalization_is_scale_invariant(self):
        original = CandleSnapshot(
            open=100.0,
            high=103.0,
            low=99.0,
            close=102.0,
            close_time=timestamp(1)
        )
        scaled = CandleSnapshot(
            open=1000.0,
            high=1030.0,
            low=990.0,
            close=1020.0,
            close_time=timestamp(1)
        )

        original_metrics = calculate_candle_metrics(
            original,
            atr=2.0
        )
        scaled_metrics = calculate_candle_metrics(
            scaled,
            atr=20.0
        )

        self.assertAlmostEqual(
            original_metrics.body_atr,
            scaled_metrics.body_atr
        )
        self.assertAlmostEqual(
            original_metrics.range_atr,
            scaled_metrics.range_atr
        )
        self.assertAlmostEqual(
            original_metrics.upper_wick_ratio,
            scaled_metrics.upper_wick_ratio
        )
        self.assertAlmostEqual(
            original_metrics.lower_wick_ratio,
            scaled_metrics.lower_wick_ratio
        )
        self.assertAlmostEqual(
            original_metrics.close_location,
            scaled_metrics.close_location
        )

    def test_swing_high_and_low_sweeps_are_detected(self):
        high_sweep_data = frame([
            {
                "close_time": timestamp(1),
                "open": 109.0,
                "high": 109.5,
                "low": 108.5,
                "close": 109.2,
                "ATR": 1.0
            },
            {
                "close_time": timestamp(2),
                "open": 110.5,
                "high": 111.0,
                "low": 109.0,
                "close": 109.5,
                "ATR": 1.0
            }
        ])
        low_sweep_data = frame([
            {
                "close_time": timestamp(1),
                "open": 101.0,
                "high": 101.5,
                "low": 100.5,
                "close": 100.8,
                "ATR": 1.0
            },
            {
                "close_time": timestamp(2),
                "open": 99.5,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "ATR": 1.0
            }
        ])
        detector = LiquidityDetector()

        high_state = detector.detect(
            high_sweep_data,
            timestamp(2),
            protected_high=110.0,
            protected_low=100.0
        )
        low_state = detector.detect(
            low_sweep_data,
            timestamp(2),
            protected_high=110.0,
            protected_low=100.0
        )

        self.assertTrue(high_state.swing_high_sweep)
        self.assertTrue(
            high_state.rejection_after_high_sweep
        )
        self.assertEqual(
            high_state.event,
            "SWING_HIGH_SWEEP_REJECTION"
        )
        self.assertTrue(low_state.swing_low_sweep)
        self.assertTrue(
            low_state.rejection_after_low_sweep
        )
        self.assertEqual(
            low_state.event,
            "SWING_LOW_SWEEP_REJECTION"
        )

    def test_rejection_on_candle_after_sweep_is_detected(self):
        data = frame([
            {
                "close_time": timestamp(1),
                "open": 109.5,
                "high": 111.0,
                "low": 109.0,
                "close": 110.5,
                "ATR": 1.0
            },
            {
                "close_time": timestamp(2),
                "open": 109.8,
                "high": 109.9,
                "low": 109.0,
                "close": 109.5,
                "ATR": 1.0
            }
        ])

        state = LiquidityDetector().detect(
            data,
            timestamp(2),
            protected_high=110.0
        )

        self.assertFalse(state.swing_high_sweep)
        self.assertTrue(state.rejection_after_high_sweep)
        self.assertEqual(
            state.event,
            "SWING_HIGH_SWEEP_REJECTION"
        )

    def test_bullish_rejection_requires_full_context(self):
        context = context_for(
            bullish_rejection_data(),
            "BUY"
        )

        result = ContextualTriggerEngine().evaluate(
            context,
            setup_for("BUY")
        )

        self.assertEqual(result.trigger, "REJECTION")
        self.assertEqual(result.direction, "BUY")
        self.assertEqual(
            result.location,
            "BULLISH_PULLBACK"
        )
        self.assertEqual(result.candle_quality, "VALID")

    def test_bearish_rejection_requires_full_context(self):
        context = context_for(
            bearish_rejection_data(),
            "SELL"
        )

        result = ContextualTriggerEngine().evaluate(
            context,
            setup_for("SELL")
        )

        self.assertEqual(result.trigger, "REJECTION")
        self.assertEqual(result.direction, "SELL")
        self.assertEqual(
            result.location,
            "BEARISH_PULLBACK"
        )
        self.assertEqual(result.candle_quality, "VALID")

    def test_morning_star_is_one_contextual_trigger(self):
        data = frame([
            {
                "close_time": timestamp(0),
                "open": 105.0,
                "high": 105.5,
                "low": 103.0,
                "close": 103.5,
                "ATR": 2.0,
            },
            {
                "close_time": timestamp(1),
                "open": 103.5,
                "high": 104.0,
                "low": 103.2,
                "close": 103.6,
                "ATR": 2.0,
            },
            {
                "close_time": timestamp(2),
                "open": 103.6,
                "high": 105.0,
                "low": 103.4,
                "close": 104.5,
                "ATR": 2.0,
            },
        ])

        result = ContextualTriggerEngine().evaluate(
            context_for(data, "BUY"),
            setup_for("BUY"),
        )

        self.assertEqual(result.trigger, "MORNING_STAR")
        self.assertEqual(result.direction, "BUY")

    def test_inside_bar_breakout_is_contextual_and_canonical(self):
        data = frame([
            {
                "close_time": timestamp(0),
                "open": 103.5,
                "high": 104.3,
                "low": 103.0,
                "close": 104.0,
                "ATR": 2.0,
            },
            {
                "close_time": timestamp(1),
                "open": 103.5,
                "high": 104.0,
                "low": 103.2,
                "close": 103.6,
                "ATR": 2.0,
            },
            {
                "close_time": timestamp(2),
                "open": 103.7,
                "high": 104.7,
                "low": 103.6,
                "close": 104.5,
                "ATR": 2.0,
            },
        ])

        result = ContextualTriggerEngine().evaluate(
            context_for(data, "BUY"),
            setup_for("BUY"),
        )

        self.assertEqual(result.trigger, "INSIDE_BAR_BREAKOUT")
        self.assertEqual(
            result.reason_codes.count(
                "INSIDE_BAR_BREAKOUT_CONFIRMED"
            ),
            1,
        )

    def test_expired_setup_cannot_emit_trigger(self):
        context = context_for(
            bullish_rejection_data(),
            "BUY"
        )

        result = ContextualTriggerEngine().evaluate(
            context,
            setup_for(
                "BUY",
                valid_until=timestamp(1)
            )
        )

        self.assertEqual(result.trigger, "NONE")
        self.assertEqual(
            result.reason_codes,
            ("SETUP_EXPIRED",)
        )

    def test_candle_without_setup_cannot_emit_trigger(self):
        context = context_for(
            bullish_rejection_data(),
            "BUY"
        )

        result = ContextualTriggerEngine().evaluate(
            context,
            setup=None
        )

        self.assertEqual(result.trigger, "NONE")
        self.assertEqual(result.direction, "NONE")
        self.assertEqual(result.reason_codes, ("NO_SETUP",))

    def test_liquidity_rejection_has_canonical_priority(self):
        data = bullish_rejection_data()
        data.loc[
            data.index[-1],
            "low"
        ] = 99.0
        context = context_for(data, "BUY")

        result = ContextualTriggerEngine().evaluate(
            context,
            setup_for("BUY")
        )

        self.assertEqual(
            result.trigger,
            "LIQUIDITY_REJECTION"
        )
        self.assertEqual(
            result.liquidity_event,
            "SWING_LOW_SWEEP_REJECTION"
        )
        self.assertEqual(result.candle_quality, "HIGH")

    def test_future_candle_mutation_cannot_change_past_context(self):
        baseline_data = bullish_rejection_data()
        baseline_data.loc[len(baseline_data)] = {
            "close_time": timestamp(3),
            "open": 104.5,
            "high": 106.0,
            "low": 104.0,
            "close": 105.5,
            "ATR": 2.0
        }
        mutated_data = baseline_data.copy(deep=True)
        future_index = mutated_data.index[-1]
        mutated_data.loc[
            future_index,
            ["open", "high", "low", "close", "ATR"]
        ] = [
            10000.0,
            20000.0,
            1.0,
            15000.0,
            5000.0
        ]

        baseline = context_for(
            baseline_data,
            "BUY",
            decision_time=timestamp(2)
        )
        mutated = context_for(
            mutated_data,
            "BUY",
            decision_time=timestamp(2)
        )

        self.assertEqual(baseline, mutated)
        self.assertEqual(
            ContextualTriggerEngine().evaluate(
                baseline,
                setup_for("BUY")
            ),
            ContextualTriggerEngine().evaluate(
                mutated,
                setup_for("BUY")
            )
        )

    def test_future_confirmed_state_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "HTF regime was not confirmed"
        ):
            ContextEngine().build(
                data=bullish_rejection_data(),
                decision_time=timestamp(2),
                htf_regime=RegimeState(
                    regime="BULLISH",
                    confirmed_at=timestamp(3)
                ),
                structure=StructureState(
                    trend="BULLISH",
                    confirmed_at=timestamp(1)
                )
            )

    def test_trigger_priority_is_deterministic(self):
        candidates = [
            "DISPLACEMENT",
            "REJECTION",
            "ENGULFING",
            "LIQUIDITY_REJECTION"
        ]

        self.assertEqual(
            choose_trigger(candidates),
            "LIQUIDITY_REJECTION"
        )
        self.assertEqual(
            choose_trigger(reversed(candidates)),
            "LIQUIDITY_REJECTION"
        )

    def test_trigger_output_schema_is_complete(self):
        context = context_for(
            bullish_rejection_data(),
            "BUY"
        )
        result = ContextualTriggerEngine().evaluate(
            context,
            setup_for("BUY")
        ).to_dict()

        self.assertEqual(
            set(result),
            {
                "trigger",
                "direction",
                "location",
                "liquidity_event",
                "candle_quality",
                "valid_until",
                "reason_codes"
            }
        )
        self.assertIsInstance(result["reason_codes"], list)


if __name__ == "__main__":
    unittest.main()
