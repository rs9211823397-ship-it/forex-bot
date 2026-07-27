"""Causal multi-timeframe alignment with legacy signal compatibility."""

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
from price_action.candles import CandlePatterns


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


class MultiTimeframeAnalyzer:
    """
    Preserve the historical analyzer API while enforcing causal alignment
    whenever timestamped data is available.
    """

    def __init__(
        self,
        higher_timeframe=None,
        lower_timeframe=None
    ):
        self.indicators = TechnicalIndicators()
        self.candles = CandlePatterns()
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

        Production and research data are timestamped and therefore use the
        causal path below.
        """

        higher_trend = self.get_trend(higher_tf)
        return self._confirmation(
            higher_trend,
            lower_tf
        )

    def _confirmation(self, higher_trend, lower_tf):
        patterns = self.candles.analyze(lower_tf)

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

        if higher_trend == "BULLISH" and bullish:
            confirmation = "BUY"
        elif higher_trend == "BEARISH" and bearish:
            confirmation = "SELL"
        else:
            confirmation = "HOLD"

        return {
            "higher_trend": higher_trend,
            "confirmation": confirmation
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

            return self._legacy_analyze(
                higher_tf,
                lower_tf
            )

        higher_trend = self.get_trend(causal_higher)
        return self._confirmation(
            higher_trend,
            causal_lower
        )
