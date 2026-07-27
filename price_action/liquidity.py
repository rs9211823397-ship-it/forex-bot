"""Causal protected-swing liquidity sweep detection."""

from dataclasses import dataclass

from price_action.candle_metrics import closed_candles_as_of


@dataclass(frozen=True)
class LiquidityState:
    swing_high_sweep: bool
    swing_low_sweep: bool
    rejection_after_high_sweep: bool
    rejection_after_low_sweep: bool
    event: str

    def to_dict(self):
        return {
            "swing_high_sweep": self.swing_high_sweep,
            "swing_low_sweep": self.swing_low_sweep,
            "rejection_after_high_sweep": (
                self.rejection_after_high_sweep
            ),
            "rejection_after_low_sweep": (
                self.rejection_after_low_sweep
            ),
            "event": self.event
        }


class LiquidityDetector:

    def detect(
        self,
        data,
        decision_time,
        protected_high=None,
        protected_low=None
    ):
        candles = closed_candles_as_of(
            data,
            decision_time
        )
        current = candles.iloc[-1]
        previous = (
            candles.iloc[-2]
            if len(candles) > 1
            else None
        )

        high_sweep = (
            protected_high is not None
            and current["high"] > protected_high
        )
        low_sweep = (
            protected_low is not None
            and current["low"] < protected_low
        )

        previous_high_sweep = (
            previous is not None
            and protected_high is not None
            and previous["high"] > protected_high
        )
        previous_low_sweep = (
            previous is not None
            and protected_low is not None
            and previous["low"] < protected_low
        )

        high_rejection = (
            protected_high is not None
            and (
                (
                    high_sweep
                    and current["close"] <= protected_high
                )
                or (
                    previous_high_sweep
                    and current["close"] <= protected_high
                    and current["close"] < current["open"]
                )
            )
        )
        low_rejection = (
            protected_low is not None
            and (
                (
                    low_sweep
                    and current["close"] >= protected_low
                )
                or (
                    previous_low_sweep
                    and current["close"] >= protected_low
                    and current["close"] > current["open"]
                )
            )
        )

        if high_rejection and low_rejection:
            event = "DUAL_SWEEP_REJECTION"
        elif high_rejection:
            event = "SWING_HIGH_SWEEP_REJECTION"
        elif low_rejection:
            event = "SWING_LOW_SWEEP_REJECTION"
        elif high_sweep and low_sweep:
            event = "DUAL_SWEEP"
        elif high_sweep:
            event = "SWING_HIGH_SWEEP"
        elif low_sweep:
            event = "SWING_LOW_SWEEP"
        else:
            event = "NONE"

        return LiquidityState(
            swing_high_sweep=bool(high_sweep),
            swing_low_sweep=bool(low_sweep),
            rejection_after_high_sweep=bool(high_rejection),
            rejection_after_low_sweep=bool(low_rejection),
            event=event
        )
