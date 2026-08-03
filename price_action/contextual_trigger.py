"""Canonical contextual trigger evaluation over a causal MarketContext."""

from dataclasses import dataclass

import pandas as pd

from price_action.candle_metrics import normalize_timestamp
from price_action.context import MarketContext
from price_action.trigger_priority import choose_trigger


@dataclass(frozen=True)
class SetupContext:
    direction: str
    created_at: pd.Timestamp
    valid_until: pd.Timestamp


@dataclass(frozen=True)
class TriggerOutput:
    trigger: str
    direction: str
    location: str
    liquidity_event: str
    candle_quality: str
    valid_until: pd.Timestamp | None
    reason_codes: tuple[str, ...]

    def to_dict(self):
        return {
            "trigger": self.trigger,
            "direction": self.direction,
            "location": self.location,
            "liquidity_event": self.liquidity_event,
            "candle_quality": self.candle_quality,
            "valid_until": (
                self.valid_until.isoformat()
                if self.valid_until is not None
                else None
            ),
            "reason_codes": list(self.reason_codes)
        }


class ContextualTriggerEngine:

    def _output(
        self,
        context,
        setup,
        trigger,
        candle_quality,
        reason_codes
    ):
        return TriggerOutput(
            trigger=trigger,
            direction=(
                setup.direction
                if setup is not None
                else "NONE"
            ),
            location=context.zones.location,
            liquidity_event=context.liquidity.event,
            candle_quality=candle_quality,
            valid_until=(
                normalize_timestamp(setup.valid_until)
                if setup is not None
                else None
            ),
            reason_codes=tuple(reason_codes)
        )

    def _is_displacement(self, context, direction):
        metrics = context.candle_metrics

        if direction == "BUY":
            return (
                metrics.direction == "BULLISH"
                and metrics.body_atr >= 0.8
                and metrics.range_atr >= 1.0
                and metrics.close_location >= 0.75
            )

        return (
            metrics.direction == "BEARISH"
            and metrics.body_atr >= 0.8
            and metrics.range_atr >= 1.0
            and metrics.close_location <= 0.25
        )

    def _is_engulfing(self, context, direction):
        previous = context.previous_candle
        current = context.current_candle

        if previous is None:
            return False

        if direction == "BUY":
            return (
                previous.close < previous.open
                and current.close > current.open
                and current.close > previous.open
                and current.open < previous.close
            )

        return (
            previous.close > previous.open
            and current.close < current.open
            and current.close < previous.open
            and current.open > previous.close
        )

    def _is_rejection(self, context, direction):
        metrics = context.candle_metrics

        if direction == "BUY":
            return (
                metrics.lower_wick_ratio >= 0.5
                and metrics.close_location >= 0.65
            )

        return (
            metrics.upper_wick_ratio >= 0.5
            and metrics.close_location <= 0.35
        )

    def _is_liquidity_rejection(self, context, direction):
        if direction == "BUY":
            return (
                context.liquidity.rejection_after_low_sweep
            )

        return (
            context.liquidity.rejection_after_high_sweep
        )

    @staticmethod
    def _body(candle):
        return abs(candle.close - candle.open)

    def _is_star_reversal(self, context, direction):
        candles = context.recent_candles

        if len(candles) < 3:
            return False

        first, middle, current = candles[-3:]
        first_body = self._body(first)
        middle_body = self._body(middle)
        first_midpoint = (first.open + first.close) / 2.0

        # FX and crypto trade continuously, so a textbook price gap is not
        # required. The small middle body and decisive midpoint recovery are
        # the causal contextual equivalent.
        if direction == "BUY":
            return (
                first.close < first.open
                and middle_body <= first_body * 0.5
                and current.close > current.open
                and current.close > first_midpoint
            )

        return (
            first.close > first.open
            and middle_body <= first_body * 0.5
            and current.close < current.open
            and current.close < first_midpoint
        )

    def _is_inside_bar_breakout(self, context, direction):
        candles = context.recent_candles

        if len(candles) < 3:
            return False

        mother, inside, current = candles[-3:]
        is_inside = (
            inside.high < mother.high
            and inside.low > mother.low
        )

        if direction == "BUY":
            return (
                is_inside
                and current.close > mother.high
                and current.close > current.open
            )

        return (
            is_inside
            and current.close < mother.low
            and current.close < current.open
        )

    def evaluate(self, context: MarketContext, setup=None):
        if setup is None:
            return self._output(
                context,
                setup,
                trigger="NONE",
                candle_quality="NONE",
                reason_codes=("NO_SETUP",)
            )

        if setup.direction not in {"BUY", "SELL"}:
            raise ValueError(
                "Setup direction must be BUY or SELL"
            )

        created_at = normalize_timestamp(setup.created_at)
        valid_until = normalize_timestamp(setup.valid_until)

        if created_at > valid_until:
            raise ValueError(
                "Setup valid_until cannot precede created_at"
            )

        if context.decision_time < created_at:
            return self._output(
                context,
                setup,
                trigger="NONE",
                candle_quality="NONE",
                reason_codes=("SETUP_NOT_ACTIVE",)
            )

        if context.decision_time > valid_until:
            return self._output(
                context,
                setup,
                trigger="NONE",
                candle_quality="NONE",
                reason_codes=("SETUP_EXPIRED",)
            )

        expected_state = (
            "BULLISH"
            if setup.direction == "BUY"
            else "BEARISH"
        )

        if context.htf_regime.regime != expected_state:
            return self._output(
                context,
                setup,
                trigger="NONE",
                candle_quality="NONE",
                reason_codes=("HTF_DIRECTION_MISMATCH",)
            )

        if context.structure.trend != expected_state:
            return self._output(
                context,
                setup,
                trigger="NONE",
                candle_quality="NONE",
                reason_codes=("STRUCTURE_DIRECTION_MISMATCH",)
            )

        if not context.zones.valid_for_direction(
            setup.direction
        ):
            return self._output(
                context,
                setup,
                trigger="NONE",
                candle_quality="NONE",
                reason_codes=("INVALID_LOCATION",)
            )

        candidates = []

        if self._is_displacement(context, setup.direction):
            candidates.append("DISPLACEMENT")

        if self._is_engulfing(context, setup.direction):
            candidates.append("ENGULFING")

        if self._is_rejection(context, setup.direction):
            candidates.append("REJECTION")

        if self._is_liquidity_rejection(
            context,
            setup.direction
        ):
            candidates.append("LIQUIDITY_REJECTION")

        if self._is_star_reversal(context, setup.direction):
            candidates.append(
                "MORNING_STAR"
                if setup.direction == "BUY"
                else "EVENING_STAR"
            )

        if self._is_inside_bar_breakout(
            context,
            setup.direction
        ):
            candidates.append("INSIDE_BAR_BREAKOUT")

        trigger = choose_trigger(candidates)

        if trigger == "NONE":
            return self._output(
                context,
                setup,
                trigger=trigger,
                candle_quality="NONE",
                reason_codes=(
                    "SETUP_VALID",
                    "HTF_ALIGNED",
                    "STRUCTURE_ALIGNED",
                    "LOCATION_VALID",
                    "NO_CONTEXTUAL_TRIGGER"
                )
            )

        candle_quality = (
            "HIGH"
            if trigger in {
                "LIQUIDITY_REJECTION",
                "DISPLACEMENT"
            }
            else "VALID"
        )

        return self._output(
            context,
            setup,
            trigger=trigger,
            candle_quality=candle_quality,
            reason_codes=(
                "SETUP_VALID",
                "HTF_ALIGNED",
                "STRUCTURE_ALIGNED",
                "LOCATION_VALID",
                f"{trigger}_CONFIRMED"
            )
        )
