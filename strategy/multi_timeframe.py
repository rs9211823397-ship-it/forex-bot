"""Causal multi-timeframe regime alignment.

The higher timeframe has one responsibility: classify directional regime.
It deliberately does not inspect lower-timeframe candle patterns or entry
triggers.  ``analyze`` retains the historical dictionary response for older
callers, but its ``confirmation`` value is now only a compatibility alias for
the regime direction.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from data.timeframes import (
    TimeframeError,
    frame_decision_time,
    normalize_timeframe,
    select_closed_candles,
    timeframe_delta
)
from indicators.technical import TechnicalIndicators


BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class TimeframeHierarchy:
    """
    Ordered high-to-low timeframe hierarchy.

    ``("1d", "4h", "1h", "15m")`` is valid; equal or ascending adjacent
    levels are rejected.
    """

    levels: tuple[str, ...]

    def __post_init__(self):
        normalized = tuple(
            normalize_timeframe(level)
            for level in self.levels
        )

        if len(normalized) < 2:
            raise TimeframeError(
                "A hierarchy requires at least two timeframes"
            )

        durations = [
            timeframe_delta(level)
            for level in normalized
        ]

        for higher, lower in zip(durations, durations[1:]):
            if higher <= lower:
                raise TimeframeError(
                    "Each higher timeframe must be greater than "
                    "the next lower timeframe"
                )

        object.__setattr__(self, "levels", normalized)

    @classmethod
    def standard(cls):
        return cls(("1d", "4h", "1h", "15m"))

    def align(self, frames, decision_time):
        """Causally align one frame for every configured level."""

        missing = [
            level for level in self.levels
            if level not in frames
        ]

        if missing:
            raise TimeframeError(
                "Missing timeframe data: " + ", ".join(missing)
            )

        return {
            level: select_closed_candles(
                frames[level],
                decision_time,
                level
            )
            for level in self.levels
        }

    def validate_pair(self, higher_timeframe, lower_timeframe):
        """Validate that two roles occur in the configured hierarchy."""

        higher = normalize_timeframe(higher_timeframe)
        lower = normalize_timeframe(lower_timeframe)

        if higher not in self.levels or lower not in self.levels:
            raise TimeframeError(
                "Both timeframe roles must exist in the hierarchy"
            )

        if self.levels.index(higher) >= self.levels.index(lower):
            raise TimeframeError(
                "Higher timeframe must precede lower timeframe"
            )


class MultiTimeframeAnalyzer:
    """
    Preserve the historical analyzer API while enforcing causal alignment
    whenever timestamped data is available.
    """

    def __init__(
        self,
        higher_timeframe=None,
        lower_timeframe=None,
        allow_untimed_legacy=True
    ):
        self.indicators = TechnicalIndicators()
        # The default preserves the original two-argument API for old
        # third-party callers. Production and research code must construct
        # this class through ``production``/``research`` (or explicitly set
        # this flag to False), which fail closed on untimed frames.
        self.allow_untimed_legacy = bool(allow_untimed_legacy)
        self.higher_timeframe = (
            normalize_timeframe(higher_timeframe)
            if higher_timeframe is not None
            else None
        )
        self.lower_timeframe = (
            normalize_timeframe(lower_timeframe)
            if lower_timeframe is not None
            else None
        )

        if (
            self.higher_timeframe is not None
            and self.lower_timeframe is not None
        ):
            TimeframeHierarchy((
                self.higher_timeframe,
                self.lower_timeframe
            ))

    @classmethod
    def production(
        cls,
        higher_timeframe=None,
        lower_timeframe=None
    ):
        """Return a fail-closed analyzer for production decisions."""

        return cls(
            higher_timeframe=higher_timeframe,
            lower_timeframe=lower_timeframe,
            allow_untimed_legacy=False
        )

    @classmethod
    def research(
        cls,
        higher_timeframe=None,
        lower_timeframe=None
    ):
        """Return a fail-closed analyzer for historical research."""

        return cls.production(
            higher_timeframe=higher_timeframe,
            lower_timeframe=lower_timeframe
        )

    def select_as_of(
        self,
        frame,
        decision_time,
        timeframe=None
    ):
        """Public as-of selector used by backtests and research."""

        return select_closed_candles(
            frame,
            decision_time,
            timeframe
        )

    def align_hierarchy(
        self,
        frames,
        decision_time,
        levels=None
    ):
        hierarchy = TimeframeHierarchy(
            tuple(levels)
            if levels is not None
            else TimeframeHierarchy.standard().levels
        )
        return hierarchy.align(frames, decision_time)

    def get_trend(
        self,
        df,
        decision_time=None,
        timeframe=None
    ):
        if decision_time is not None:
            df = self.select_as_of(
                df,
                decision_time,
                timeframe or self.higher_timeframe
            )

        df = self.indicators.add_indicators(df)
        df = df.dropna()

        if len(df) == 0:
            return "SIDEWAYS"

        latest = df.iloc[-1]

        if (
            latest["EMA_20"] > latest["EMA_50"]
            and latest["EMA_50"] > latest["EMA_200"]
        ):
            return "BULLISH"

        if (
            latest["EMA_20"] < latest["EMA_50"]
            and latest["EMA_50"] < latest["EMA_200"]
        ):
            return "BEARISH"

        return "SIDEWAYS"

    def get_regime(
        self,
        df,
        decision_time=None,
        timeframe=None
    ):
        """Return the canonical HTF regime without evaluating LTF evidence."""

        trend = self.get_trend(
            df,
            decision_time=decision_time,
            timeframe=timeframe
        )

        if trend == BULLISH:
            return BULLISH

        if trend == BEARISH:
            return BEARISH

        return NEUTRAL

    def _resolve_decision_time(
        self,
        lower_tf,
        decision_time,
        lower_timeframe
    ):
        if decision_time is not None:
            return decision_time

        return frame_decision_time(
            lower_tf,
            lower_timeframe
        )

    @staticmethod
    def _has_time_contract(frame):
        return (
            "open_time" in frame.columns
            or "close_time" in frame.columns
            or isinstance(frame.index, pd.DatetimeIndex)
        )

    def _legacy_analyze(self, higher_tf, lower_tf):
        """
        Preserve callers that provide non-temporal synthetic frames.

        This deprecated branch intentionally retains the original LTF candle
        confirmation contract. Strict production and research analyzers
        disable the branch and never inspect LTF price action here.
        """

        from price_action.candles import CandlePatterns

        higher_trend = self.get_trend(higher_tf)
        patterns = CandlePatterns().analyze(lower_tf)
        bullish = (
            "Bullish engulfing" in patterns
            or "BULLISH PIN BAR" in patterns
            or "STRONG BULLISH CANDLE" in patterns
        )
        bearish = (
            "Bearish engulfing" in patterns
            or "BEARISH PIN BAR" in patterns
            or "STRONG BEARISH CANDLE" in patterns
        )

        if higher_trend == BULLISH and bullish:
            confirmation = "BUY"
        elif higher_trend == BEARISH and bearish:
            confirmation = "SELL"
        else:
            confirmation = "HOLD"

        return {
            "higher_trend": higher_trend,
            "confirmation": confirmation
        }

    @staticmethod
    def _compatibility_result(regime):
        """
        Preserve the original response keys without mixing timeframe roles.

        ``confirmation`` is a deprecated directional alias. It contains no
        lower-timeframe candle or trigger evidence.
        """

        directional_alias = {
            BULLISH: "BUY",
            BEARISH: "SELL",
            NEUTRAL: "HOLD"
        }[regime]
        return {
            "higher_trend": regime,
            "confirmation": directional_alias
        }

    def analyze(
        self,
        higher_tf,
        lower_tf,
        decision_time=None,
        higher_timeframe=None,
        lower_timeframe=None
    ):
        """
        Analyze only candles closed by the lower-timeframe decision time.

        The original two-positional-argument call remains valid.
        """

        resolved_higher = (
            higher_timeframe or self.higher_timeframe
        )
        resolved_lower = (
            lower_timeframe or self.lower_timeframe
        )

        if (
            resolved_higher is not None
            and resolved_lower is not None
        ):
            TimeframeHierarchy((
                resolved_higher,
                resolved_lower
            ))

        try:
            resolved_decision = self._resolve_decision_time(
                lower_tf,
                decision_time,
                resolved_lower
            )
            causal_higher = self.select_as_of(
                higher_tf,
                resolved_decision,
                resolved_higher
            )
            causal_lower = self.select_as_of(
                lower_tf,
                resolved_decision,
                resolved_lower
            )
        except TimeframeError:
            if (
                decision_time is not None
                or self._has_time_contract(higher_tf)
                or self._has_time_contract(lower_tf)
            ):
                raise

            if not self.allow_untimed_legacy:
                raise TimeframeError(
                    "Untimed candle frames are disabled; provide open_time "
                    "or close_time timestamps"
                )

            return self._legacy_analyze(
                higher_tf,
                lower_tf
            )

        # Validate and causally truncate the lower frame, but do not inspect
        # its price action. Its only role here is to establish decision time.
        del causal_lower
        return self._compatibility_result(
            self.get_regime(causal_higher)
        )
