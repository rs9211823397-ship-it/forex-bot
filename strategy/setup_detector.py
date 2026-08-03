"""Setup identification extracted from the legacy signal engine."""

import pandas as pd

from price_action.contextual_trigger import SetupContext
from strategy.decision import SetupResult


class SetupDetector:

    def __init__(self, contextual_expiry_candles=3):
        self.contextual_expiry_candles = (
            contextual_expiry_candles
        )
        self._active_contextual_setups = {}
        self._last_decision_times = {}

    def detect(self, latest):
        """Identify the existing EMA/Supertrend trend setup."""

        if (
            latest["EMA_20"] > latest["EMA_50"]
            and latest["EMA_50"] > latest["EMA_200"]
            and latest["SUPERTREND"]
        ):
            return SetupResult(
                trend_score=30,
                reasons=("Bullish EMA alignment",)
            )

        if (
            latest["EMA_20"] < latest["EMA_50"]
            and latest["EMA_50"] < latest["EMA_200"]
            and not latest["SUPERTREND"]
        ):
            return SetupResult(
                trend_score=-30,
                reasons=("Bearish EMA alignment",)
            )

        return SetupResult(
            trend_score=0,
            reasons=("Trend not aligned",)
        )

    def create_contextual_setup(
        self,
        setup,
        decision_time,
        bar_duration,
        htf_regime,
        structure_trend,
        symbol="__default__"
    ):
        """Create direction only when setup, HTF, and structure agree."""

        direction = None

        if (
            setup.trend_score > 0
            and htf_regime == "BULLISH"
            and structure_trend == "BULLISH"
        ):
            direction = "BUY"

        elif (
            setup.trend_score < 0
            and htf_regime == "BEARISH"
            and structure_trend == "BEARISH"
        ):
            direction = "SELL"

        if direction is None:
            self._active_contextual_setups.pop(
                symbol,
                None
            )
            self._last_decision_times[
                symbol
            ] = decision_time
            return None

        previous_time = self._last_decision_times.get(
            symbol
        )

        if (
            previous_time is not None
            and decision_time < previous_time
        ):
            self._active_contextual_setups.pop(
                symbol,
                None
            )

        self._last_decision_times[symbol] = decision_time
        active_setup = self._active_contextual_setups.get(
            symbol
        )

        if (
            active_setup is not None
            and active_setup.direction == direction
            and decision_time <= active_setup.valid_until
        ):
            return active_setup

        duration = (
            bar_duration
            if bar_duration is not None
            else pd.Timedelta(0)
        )

        contextual_setup = SetupContext(
            direction=direction,
            created_at=decision_time,
            valid_until=(
                decision_time
                + (
                    duration
                    * self.contextual_expiry_candles
                )
            )
        )
        self._active_contextual_setups[
            symbol
        ] = contextual_setup

        return contextual_setup
