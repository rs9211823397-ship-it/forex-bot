"""Causal, event-driven market-structure analysis.

Swing points are formed at the candidate candle but become usable only after
``lookback`` candles have closed.  The implementation rebuilds state from an
ordered event stream for every supplied point-in-time frame, which makes it
deterministic and prevents state from one backtest run leaking into another.

The historical ``MarketStructure`` methods remain available as compatibility
wrappers around the richer :meth:`state` result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from data.timeframes import (
    TimeframeError,
    candle_close_times,
    normalize_timestamp,
    select_closed_candles,
)


BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"
SWING_HIGH = "SWING_HIGH"
SWING_LOW = "SWING_LOW"


class MarketStructureError(ValueError):
    """Raised when market data cannot satisfy the structure contract."""


@dataclass(frozen=True)
class SwingEvent:
    """A swing that is unavailable until ``confirmed_at``."""

    price: float
    type: str
    formed_at: Any
    confirmed_at: Any
    formed_index: int
    confirmed_index: int
    classification: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class StructureBreakEvent:
    """One close-confirmed BOS or CHoCH event."""

    event: str
    direction: str
    level: float
    level_formed_at: Any
    confirmed_at: Any
    close: float
    reason_code: str

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class StructureState:
    """Immutable point-in-time structure snapshot."""

    trend: str
    swings: tuple[SwingEvent, ...]
    protected_high: SwingEvent | None
    protected_low: SwingEvent | None
    breaks: tuple[StructureBreakEvent, ...]
    latest_bos: StructureBreakEvent | None
    latest_choch: StructureBreakEvent | None
    false_breakout: str
    quality_score: float
    decision_time: Any

    def to_dict(self):
        return {
            "trend": self.trend,
            "swings": [event.to_dict() for event in self.swings],
            "protected_high": (
                self.protected_high.to_dict()
                if self.protected_high is not None
                else None
            ),
            "protected_low": (
                self.protected_low.to_dict()
                if self.protected_low is not None
                else None
            ),
            "breaks": [event.to_dict() for event in self.breaks],
            "latest_bos": (
                self.latest_bos.to_dict()
                if self.latest_bos is not None
                else None
            ),
            "latest_choch": (
                self.latest_choch.to_dict()
                if self.latest_choch is not None
                else None
            ),
            "false_breakout": self.false_breakout,
            "quality_score": self.quality_score,
            "decision_time": self.decision_time,
        }


class MarketStructure:
    """Build causal market structure from confirmed swing events."""

    def __init__(self, lookback=3, break_buffer=0.0, max_history=300):
        if isinstance(lookback, bool) or not isinstance(lookback, int):
            raise MarketStructureError("lookback must be a positive integer")
        if lookback <= 0:
            raise MarketStructureError("lookback must be a positive integer")
        if isinstance(max_history, bool) or not isinstance(max_history, int):
            raise MarketStructureError(
                "max_history must be a positive integer"
            )
        if max_history <= 0:
            raise MarketStructureError(
                "max_history must be a positive integer"
            )
        if (
            isinstance(break_buffer, bool)
            or not isinstance(break_buffer, (int, float))
            or not isfinite(float(break_buffer))
            or float(break_buffer) < 0
        ):
            raise MarketStructureError(
                "break_buffer must be a finite non-negative number"
            )

        self.lookback = lookback
        self.break_buffer = float(break_buffer)
        self.max_history = max_history

    @staticmethod
    def normalize_columns(df):
        if not isinstance(df, pd.DataFrame):
            raise MarketStructureError(
                "Market structure data must be a pandas DataFrame"
            )
        normalized = df.copy()
        normalized.columns = [
            str(column).lower()
            for column in normalized.columns
        ]
        return normalized

    @staticmethod
    def _has_time_contract(frame):
        return (
            "open_time" in frame.columns
            or "close_time" in frame.columns
            or isinstance(frame.index, pd.DatetimeIndex)
        )

    def _prepare(self, df, decision_time=None, timeframe=None):
        frame = self.normalize_columns(df)
        missing = [
            column
            for column in ("high", "low", "close")
            if column not in frame.columns
        ]
        if missing:
            raise MarketStructureError(
                "Missing market-structure columns: " + ", ".join(missing)
            )

        if decision_time is not None:
            if not self._has_time_contract(frame):
                raise MarketStructureError(
                    "decision_time requires timestamped candle data"
                )
            try:
                frame = select_closed_candles(
                    frame,
                    normalize_timestamp(decision_time, "decision_time"),
                    timeframe,
                )
            except TimeframeError as exc:
                raise MarketStructureError(str(exc)) from exc
        elif self._has_time_contract(frame):
            try:
                frame = frame.copy()
                frame["close_time"] = candle_close_times(frame, timeframe)
            except TimeframeError as exc:
                raise MarketStructureError(str(exc)) from exc

        frame = frame.tail(self.max_history).copy()
        if frame.empty:
            return frame, ()

        try:
            numeric = frame.loc[:, ["high", "low", "close"]].astype(float)
        except (TypeError, ValueError) as exc:
            raise MarketStructureError(
                "High, low, and close values must be numeric"
            ) from exc

        if not np.isfinite(numeric.to_numpy()).all():
            raise MarketStructureError(
                "High, low, and close values must be finite"
            )
        if (numeric["high"] < numeric["low"]).any():
            raise MarketStructureError("Candle high cannot be below low")
        if (
            (numeric["close"] > numeric["high"])
            | (numeric["close"] < numeric["low"])
        ).any():
            raise MarketStructureError(
                "Candle close must be between high and low"
            )

        frame.loc[:, ["high", "low", "close"]] = numeric
        if "close_time" in frame.columns:
            times = tuple(frame["close_time"])
        else:
            times = tuple(frame.index)
        return frame, times

    def swing_events(self, df, decision_time=None, timeframe=None):
        """Return one chronological, alternating stream of confirmed swings."""

        frame, times = self._prepare(df, decision_time, timeframe)
        radius = self.lookback
        if len(frame) < (2 * radius) + 1:
            return ()

        highs = frame["high"].to_numpy(dtype=float)
        lows = frame["low"].to_numpy(dtype=float)
        candidates = []

        for index in range(radius, len(frame) - radius):
            high = highs[index]
            low = lows[index]
            left_highs = highs[index - radius:index]
            right_highs = highs[index + 1:index + radius + 1]
            left_lows = lows[index - radius:index]
            right_lows = lows[index + 1:index + radius + 1]

            # Strict comparisons deliberately make equal high/low plateaus
            # non-swings. This is deterministic and avoids arbitrary ties.
            if high > left_highs.max() and high > right_highs.max():
                candidates.append(
                    SwingEvent(
                        price=float(high),
                        type=SWING_HIGH,
                        formed_at=times[index],
                        confirmed_at=times[index + radius],
                        formed_index=index,
                        confirmed_index=index + radius,
                    )
                )
            if low < left_lows.min() and low < right_lows.min():
                candidates.append(
                    SwingEvent(
                        price=float(low),
                        type=SWING_LOW,
                        formed_at=times[index],
                        confirmed_at=times[index + radius],
                        formed_index=index,
                        confirmed_index=index + radius,
                    )
                )

        candidates.sort(
            key=lambda event: (
                event.confirmed_index,
                event.formed_index,
                0 if event.type == SWING_HIGH else 1,
            )
        )

        # Enforce a single alternating stream. Consecutive extrema of one type
        # are consolidated to the more extreme, later-confirmed candidate.
        alternating = []
        for event in candidates:
            if not alternating or alternating[-1].type != event.type:
                alternating.append(event)
                continue

            previous = alternating[-1]
            replace = (
                event.price > previous.price
                if event.type == SWING_HIGH
                else event.price < previous.price
            )
            if replace:
                alternating[-1] = event

        previous_high = None
        previous_low = None
        classified = []
        for event in alternating:
            if event.type == SWING_HIGH:
                if previous_high is None:
                    label = ""
                elif event.price > previous_high:
                    label = "HH"
                elif event.price < previous_high:
                    label = "LH"
                else:
                    label = "EH"
                previous_high = event.price
            else:
                if previous_low is None:
                    label = ""
                elif event.price > previous_low:
                    label = "HL"
                elif event.price < previous_low:
                    label = "LL"
                else:
                    label = "EL"
                previous_low = event.price

            classified.append(
                SwingEvent(
                    price=event.price,
                    type=event.type,
                    formed_at=event.formed_at,
                    confirmed_at=event.confirmed_at,
                    formed_index=event.formed_index,
                    confirmed_index=event.confirmed_index,
                    classification=label,
                )
            )
        return tuple(classified)

    @staticmethod
    def _infer_initial_trend(high, low):
        if high is not None and low is not None:
            if high.classification == "HH" and low.classification == "HL":
                return BULLISH
            if high.classification == "LH" and low.classification == "LL":
                return BEARISH
        return NEUTRAL

    def _break_event(
        self,
        kind,
        direction,
        level,
        confirmed_at,
        close,
    ):
        return StructureBreakEvent(
            event=kind,
            direction=direction,
            level=level.price,
            level_formed_at=level.formed_at,
            confirmed_at=confirmed_at,
            close=float(close),
            reason_code=f"{direction}_{kind}",
        )

    def state(self, df, decision_time=None, timeframe=None):
        """Return the complete structure state known at ``decision_time``."""

        frame, times = self._prepare(df, decision_time, timeframe)
        swings = self.swing_events(
            frame,
            decision_time=None,
            timeframe=timeframe,
        )
        if frame.empty:
            return StructureState(
                trend=NEUTRAL,
                swings=(),
                protected_high=None,
                protected_low=None,
                breaks=(),
                latest_bos=None,
                latest_choch=None,
                false_breakout="NONE",
                quality_score=0.0,
                decision_time=None,
            )

        swings_by_confirmation = {}
        for event in swings:
            swings_by_confirmation.setdefault(
                event.confirmed_index, []
            ).append(event)

        trend = NEUTRAL
        protected_high = None
        protected_low = None
        breaks = []
        broken_levels = set()

        for index, row in enumerate(frame.itertuples(index=False)):
            for event in swings_by_confirmation.get(index, ()):
                if event.type == SWING_HIGH:
                    protected_high = event
                else:
                    protected_low = event

            if trend == NEUTRAL:
                trend = self._infer_initial_trend(
                    protected_high,
                    protected_low,
                )

            close = float(row.close)
            confirmed_at = times[index]

            if trend == BULLISH and protected_low is not None:
                level_key = ("LOW", protected_low.formed_index)
                if (
                    close
                    < protected_low.price - self.break_buffer
                    and level_key not in broken_levels
                ):
                    breaks.append(
                        self._break_event(
                            "CHOCH",
                            BEARISH,
                            protected_low,
                            confirmed_at,
                            close,
                        )
                    )
                    broken_levels.add(level_key)
                    trend = BEARISH
                    continue

            if trend == BEARISH and protected_high is not None:
                level_key = ("HIGH", protected_high.formed_index)
                if (
                    close
                    > protected_high.price + self.break_buffer
                    and level_key not in broken_levels
                ):
                    breaks.append(
                        self._break_event(
                            "CHOCH",
                            BULLISH,
                            protected_high,
                            confirmed_at,
                            close,
                        )
                    )
                    broken_levels.add(level_key)
                    trend = BULLISH
                    continue

            if (
                trend == BULLISH
                and protected_high is not None
            ):
                level_key = ("HIGH", protected_high.formed_index)
                if (
                    close
                    > protected_high.price + self.break_buffer
                    and level_key not in broken_levels
                ):
                    breaks.append(
                        self._break_event(
                            "BOS",
                            BULLISH,
                            protected_high,
                            confirmed_at,
                            close,
                        )
                    )
                    broken_levels.add(level_key)
            elif (
                trend == BEARISH
                and protected_low is not None
            ):
                level_key = ("LOW", protected_low.formed_index)
                if (
                    close
                    < protected_low.price - self.break_buffer
                    and level_key not in broken_levels
                ):
                    breaks.append(
                        self._break_event(
                            "BOS",
                            BEARISH,
                            protected_low,
                            confirmed_at,
                            close,
                        )
                    )
                    broken_levels.add(level_key)

        latest_time = times[-1]
        latest_bos = next(
            (
                event
                for event in reversed(breaks)
                if event.event == "BOS"
                and event.confirmed_at == latest_time
            ),
            None,
        )
        latest_choch = next(
            (
                event
                for event in reversed(breaks)
                if event.event == "CHOCH"
                and event.confirmed_at == latest_time
            ),
            None,
        )
        false_breakout = self._false_breakout(
            frame.iloc[-1],
            trend,
            protected_high,
            protected_low,
        )
        return StructureState(
            trend=trend,
            swings=swings,
            protected_high=protected_high,
            protected_low=protected_low,
            breaks=tuple(breaks),
            latest_bos=latest_bos,
            latest_choch=latest_choch,
            false_breakout=false_breakout,
            quality_score=self._quality(swings, trend),
            decision_time=latest_time,
        )

    def _false_breakout(self, latest, trend, protected_high, protected_low):
        if (
            protected_high is not None
            and float(latest["high"])
            > protected_high.price + self.break_buffer
            and float(latest["close"])
            <= protected_high.price + self.break_buffer
        ):
            return "BULLISH FALSE BREAKOUT"
        if (
            protected_low is not None
            and float(latest["low"])
            < protected_low.price - self.break_buffer
            and float(latest["close"])
            >= protected_low.price - self.break_buffer
        ):
            return "BEARISH FALSE BREAKOUT"
        return "NONE"

    @staticmethod
    def _quality(swings, trend):
        if trend == NEUTRAL:
            return 0.0
        expected = (
            {"HH", "HL"}
            if trend == BULLISH
            else {"LH", "LL"}
        )
        labels = [
            event.classification
            for event in swings[-6:]
            if event.classification
        ]
        if not labels:
            return 0.0
        aligned = sum(label in expected for label in labels)
        return round(100.0 * aligned / len(labels), 6)

    # Compatibility wrappers -------------------------------------------------
    def find_swings(self, df):
        events = self.swing_events(df)

        def record(event):
            return {
                "index": event.formed_index,
                "price": event.price,
                "type": event.type,
                "formed_at": event.formed_at,
                "confirmed_at": event.confirmed_at,
                "classification": event.classification,
            }

        highs = [
            record(event)
            for event in events
            if event.type == SWING_HIGH
        ]
        lows = [
            record(event)
            for event in events
            if event.type == SWING_LOW
        ]
        return highs, lows

    def detect_structure(self, df):
        return [
            event.classification
            for event in self.swing_events(df)
            if event.classification
        ]

    def detect_trend(self, df):
        trend = self.state(df).trend
        return "SIDEWAYS" if trend == NEUTRAL else trend

    def trend(self, df):
        return self.detect_trend(df)

    def support_resistance(self, df):
        highs, lows = self.find_swings(df)
        return {
            "support": [event["price"] for event in lows[-5:]],
            "resistance": [event["price"] for event in highs[-5:]],
        }

    def detect_bos(self, df):
        event = self.state(df).latest_bos
        if event is None:
            return "NO BOS"
        return f"{event.direction} BOS"

    def detect_choch(self, df):
        event = self.state(df).latest_choch
        if event is None:
            return "NO CHoCH"
        return f"{event.direction} CHoCH"

    def detect_false_breakout(self, df):
        return self.state(df).false_breakout

    def structure_quality(self, df):
        return self.state(df).quality_score

    def get_structure_summary(self, df):
        state = self.state(df)
        levels = self.support_resistance(df)
        return {
            "trend": (
                "SIDEWAYS"
                if state.trend == NEUTRAL
                else state.trend
            ),
            "bos": self.detect_bos(df),
            "choch": self.detect_choch(df),
            "support": levels["support"],
            "resistance": levels["resistance"],
            "protected_high": (
                state.protected_high.price
                if state.protected_high is not None
                else None
            ),
            "protected_low": (
                state.protected_low.price
                if state.protected_low is not None
                else None
            ),
            "false_breakout": state.false_breakout,
            "quality_score": state.quality_score,
        }
