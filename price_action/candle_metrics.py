"""Causal candle selection and ATR-normalized candle measurements."""

from dataclasses import dataclass
from math import isfinite

import pandas as pd


def normalize_timestamp(value):
    """Normalize timestamps to UTC, interpreting naive values as UTC."""

    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")


def closed_candles_as_of(data, decision_time):
    """Return a stable copy containing only candles closed by decision time."""

    frame = data.copy()
    frame.columns = [
        str(column).lower()
        for column in frame.columns
    ]

    if "close_time" not in frame.columns:
        if (
            isinstance(frame.index, pd.DatetimeIndex)
            and str(frame.index.name).lower() == "close_time"
        ):
            frame["close_time"] = frame.index
        else:
            raise ValueError(
                "Explicit close_time column or named DatetimeIndex required"
            )

    frame["close_time"] = pd.to_datetime(
        frame["close_time"],
        utc=True,
        errors="raise"
    )
    decision_timestamp = normalize_timestamp(decision_time)
    frame = frame.loc[
        frame["close_time"] <= decision_timestamp
    ].copy()
    frame.sort_values(
        "close_time",
        kind="mergesort",
        inplace=True
    )

    if frame.empty:
        raise ValueError(
            "No closed candles are available at decision_time"
        )

    return frame


@dataclass(frozen=True)
class CandleSnapshot:
    open: float
    high: float
    low: float
    close: float
    close_time: pd.Timestamp


@dataclass(frozen=True)
class CandleMetrics:
    body_atr: float
    range_atr: float
    upper_wick_ratio: float
    lower_wick_ratio: float
    close_location: float
    direction: str

    def to_dict(self):
        return {
            "body_atr": self.body_atr,
            "range_atr": self.range_atr,
            "upper_wick_ratio": self.upper_wick_ratio,
            "lower_wick_ratio": self.lower_wick_ratio,
            "close_location": self.close_location,
            "direction": self.direction
        }


def candle_snapshot(row):
    snapshot = CandleSnapshot(
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        close_time=normalize_timestamp(row["close_time"])
    )

    values = (
        snapshot.open,
        snapshot.high,
        snapshot.low,
        snapshot.close
    )

    if not all(isfinite(value) for value in values):
        raise ValueError("OHLC values must be finite")

    if (
        snapshot.low > min(snapshot.open, snapshot.close)
        or snapshot.high < max(snapshot.open, snapshot.close)
        or snapshot.high < snapshot.low
    ):
        raise ValueError("Invalid OHLC geometry")

    return snapshot


def calculate_candle_metrics(candle, atr):
    atr_value = float(atr)

    if not isfinite(atr_value) or atr_value <= 0:
        raise ValueError("ATR must be finite and greater than zero")

    total_range = candle.high - candle.low
    body = abs(candle.close - candle.open)

    if total_range == 0:
        upper_wick_ratio = 0.0
        lower_wick_ratio = 0.0
        close_location = 0.5
    else:
        upper_wick = (
            candle.high - max(candle.open, candle.close)
        )
        lower_wick = (
            min(candle.open, candle.close) - candle.low
        )
        upper_wick_ratio = upper_wick / total_range
        lower_wick_ratio = lower_wick / total_range
        close_location = (
            candle.close - candle.low
        ) / total_range

    if candle.close > candle.open:
        direction = "BULLISH"
    elif candle.close < candle.open:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return CandleMetrics(
        body_atr=body / atr_value,
        range_atr=total_range / atr_value,
        upper_wick_ratio=upper_wick_ratio,
        lower_wick_ratio=lower_wick_ratio,
        close_location=close_location,
        direction=direction
    )
