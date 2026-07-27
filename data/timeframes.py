"""Shared causal timestamp and timeframe contracts."""

from __future__ import annotations

import re

import pandas as pd


class TimeframeError(ValueError):
    """Raised when candle timestamps cannot satisfy a causal contract."""


_TIMEFRAME_PATTERN = re.compile(
    r"^(?P<count>[1-9]\d*)\s*(?P<unit>[mhdw])$",
    re.IGNORECASE
)
_UNIT_SECONDS = {
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60
}


def normalize_timeframe(value):
    """Return a canonical timeframe label such as ``15m`` or ``4h``."""

    if not isinstance(value, str):
        raise TimeframeError("Timeframe must be a string")

    normalized = value.strip().lower()
    match = _TIMEFRAME_PATTERN.fullmatch(normalized)

    if match is None:
        raise TimeframeError(
            f"Unsupported timeframe {value!r}; use m, h, d, or w"
        )

    return (
        f"{int(match.group('count'))}"
        f"{match.group('unit').lower()}"
    )


def timeframe_delta(value):
    """Convert a supported timeframe label to ``pandas.Timedelta``."""

    normalized = normalize_timeframe(value)
    count = int(normalized[:-1])
    unit = normalized[-1]
    return pd.Timedelta(
        seconds=count * _UNIT_SECONDS[unit]
    )


def normalize_timestamp(value, name="timestamp"):
    """Normalize one timestamp to a timezone-aware UTC ``Timestamp``."""

    if value is None:
        raise TimeframeError(f"{name} is required")

    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise TimeframeError(
            f"{name} must be a valid timestamp"
        ) from exc

    if pd.isna(timestamp):
        raise TimeframeError(f"{name} cannot be missing")

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")


def _normalize_timestamp_values(values, name):
    try:
        timestamps = pd.DatetimeIndex(
            pd.to_datetime(values, utc=True, errors="raise")
        )
    except (TypeError, ValueError) as exc:
        raise TimeframeError(
            f"{name} must contain valid timestamps"
        ) from exc

    if timestamps.hasnans:
        raise TimeframeError(
            f"{name} cannot contain missing timestamps"
        )

    if timestamps.has_duplicates:
        raise TimeframeError(
            f"{name} timestamps must be unique"
        )

    if not timestamps.is_monotonic_increasing:
        raise TimeframeError(
            f"{name} timestamps must be monotonic increasing"
        )

    return timestamps


def _infer_delta(index):
    if len(index) < 2:
        raise TimeframeError(
            "Timeframe is required when fewer than two candles exist"
        )

    differences = index[1:].asi8 - index[:-1].asi8

    if (differences <= 0).any():
        raise TimeframeError(
            "Candle timestamps must be strictly increasing"
        )

    counts = pd.Series(differences).value_counts()
    inferred_ns = int(counts.index[0])
    return pd.Timedelta(inferred_ns, unit="ns")


def _resolve_delta(frame, timeframe, index=None):
    declared = timeframe or frame.attrs.get("timeframe")

    if declared is not None:
        return timeframe_delta(declared)

    if index is None:
        raise TimeframeError(
            "Timeframe is required when candle opens are unavailable"
        )

    return _infer_delta(index)


def _validate_spacing(timestamps, delta, name):
    if len(timestamps) < 2:
        return

    differences = timestamps[1:].asi8 - timestamps[:-1].asi8
    duration_ns = int(delta.value)

    if duration_ns <= 0:
        raise TimeframeError("Timeframe duration must be positive")

    if (differences % duration_ns != 0).any():
        raise TimeframeError(
            f"{name} timestamps are not aligned to the timeframe"
        )


def candle_open_times(frame, timeframe=None):
    """Return validated UTC candle-open timestamps."""

    if "open_time" in frame.columns:
        opens = _normalize_timestamp_values(
            frame["open_time"],
            "open_time"
        )
    elif isinstance(frame.index, pd.DatetimeIndex):
        opens = _normalize_timestamp_values(
            frame.index,
            "candle index"
        )
    else:
        raise TimeframeError(
            "Candle data requires open_time or a DatetimeIndex"
        )

    delta = _resolve_delta(frame, timeframe, opens)
    _validate_spacing(opens, delta, "Candle open")
    return opens


def candle_close_times(frame, timeframe=None):
    """
    Return validated close timestamps.

    Explicit ``close_time`` values are preferred. Otherwise the index or
    ``open_time`` is treated as candle-open time and the declared/inferred
    timeframe is added.
    """

    if "close_time" in frame.columns:
        closes = _normalize_timestamp_values(
            frame["close_time"],
            "close_time"
        )

        declared = timeframe or frame.attrs.get("timeframe")

        if declared is not None:
            delta = timeframe_delta(declared)
            _validate_spacing(closes, delta, "Candle close")

            if (
                "open_time" in frame.columns
                or isinstance(frame.index, pd.DatetimeIndex)
            ):
                opens = candle_open_times(frame, declared)
                expected = opens + delta

                if not expected.equals(closes):
                    raise TimeframeError(
                        "Candle close_time must equal open_time "
                        "plus timeframe"
                    )

        return closes

    opens = candle_open_times(frame, timeframe)
    delta = _resolve_delta(frame, timeframe, opens)
    return opens + delta


def select_closed_candles(
    frame,
    decision_time,
    timeframe=None
):
    """
    Return only candles closed at or before ``decision_time``.

    The result receives an explicit ``close_time`` column, making the
    point-in-time contract visible to downstream code.
    """

    decision = normalize_timestamp(
        decision_time,
        "decision_time"
    )
    closes = candle_close_times(frame, timeframe)
    mask = closes <= decision
    selected = frame.loc[mask].copy()
    selected_closes = closes[mask]
    selected["close_time"] = selected_closes

    if timeframe is not None:
        selected.attrs["timeframe"] = normalize_timeframe(
            timeframe
        )
    elif frame.attrs.get("timeframe") is not None:
        selected.attrs["timeframe"] = normalize_timeframe(
            frame.attrs["timeframe"]
        )

    return selected


def frame_decision_time(frame, timeframe=None):
    """Return the close time of the latest candle in a frame."""

    if frame.empty:
        raise TimeframeError(
            "Cannot derive decision_time from an empty candle frame"
        )

    return candle_close_times(frame, timeframe)[-1]
