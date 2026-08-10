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
        """Identify mature or developing EMA/Supertrend trend setups.

        A fully stacked EMA20/50/200 trend with matching Supertrend keeps the
        legacy +/-30 score.  A developing trend can now establish direction
        with a smaller +/-15 score when EMA20/50 and Supertrend agree while
        EMA50/200 have not fully stacked yet.  The reduced score intentionally
        does not bypass downstream structure, momentum, price-action, HTF,
        contextual, quality, or risk gates.
        """

        ema20 = latest["EMA_20"]
        ema50 = latest["EMA_50"]
        ema200 = latest["EMA_200"]
        supertrend_bullish = bool(latest["SUPERTREND"])

        if (
            ema20 > ema50
            and ema50 > ema200
            and supertrend_bullish
        ):
            return SetupResult(
                trend_score=30,
                reasons=("Bullish EMA alignment",)
            )

        if (
            ema20 < ema50
            and ema50 < ema200
            and not supertrend_bullish
        ):
            return SetupResult(
                trend_score=-30,
                reasons=("Bearish EMA alignment",)
            )

        if ema20 > ema50 and supertrend_bullish:
            return SetupResult(
                trend_score=15,
                reasons=(
                    "Developing bullish trend (EMA20 > EMA50 + Supertrend)",
                )
            )

        if ema20 < ema50 and not supertrend_bullish:
            return SetupResult(
                trend_score=-15,
                reasons=(
                    "Developing bearish trend (EMA20 < EMA50 + Supertrend)",
                )
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
        """Create a contextual direction without treating neutral HTF as opposite.

        Directional higher-timeframe states remain hard gates.  A NEUTRAL HTF
        may carry a lower-timeframe setup forward only when market structure
        agrees with that setup; contextual location/trigger and quality checks
        still decide whether the trade is ultimately eligible.
        """

        direction = None
        buy_htf_ok = htf_regime in {"BULLISH", "NEUTRAL"}
        sell_htf_ok = htf_regime in {"BEARISH", "NEUTRAL"}

        if (
            setup.trend_score > 0
            and buy_htf_ok
            and structure_trend == "BULLISH"
        ):
            direction = "BUY"

        elif (
            setup.trend_score < 0
            and sell_htf_ok
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
