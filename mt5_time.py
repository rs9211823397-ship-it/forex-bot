"""Explicit conversion between broker-server epochs and real UTC.

Some MT5 brokers expose candle, tick, and deal epochs in server-local time
instead of UTC. AAQTS never guesses that offset: production launchers pin it
explicitly, and a wrong value makes freshness checks fail closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite


MIN_OFFSET_MINUTES = -14 * 60
MAX_OFFSET_MINUTES = 14 * 60


def validate_mt5_server_utc_offset_minutes(value: int) -> int:
    if isinstance(value, bool):
        raise ValueError("MT5 server UTC offset must be an integer number of minutes")
    offset = int(value)
    if offset != value or offset < MIN_OFFSET_MINUTES or offset > MAX_OFFSET_MINUTES:
        raise ValueError(
            "MT5 server UTC offset must be an integer between -840 and 840 minutes"
        )
    return offset


def mt5_epoch_to_utc_seconds(timestamp: float, offset_minutes: int) -> float:
    value = float(timestamp)
    if not isfinite(value) or value <= 0:
        raise ValueError("MT5 timestamp must be finite and positive")
    offset = validate_mt5_server_utc_offset_minutes(offset_minutes)
    return value - (offset * 60.0)


def mt5_epoch_to_utc_datetime(timestamp: float, offset_minutes: int) -> datetime:
    return datetime.fromtimestamp(
        mt5_epoch_to_utc_seconds(timestamp, offset_minutes),
        timezone.utc,
    )


def utc_datetime_to_mt5_server_time(value: datetime, offset_minutes: int) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC conversion requires a timezone-aware datetime")
    offset = validate_mt5_server_utc_offset_minutes(offset_minutes)
    return value.astimezone(timezone.utc) + timedelta(minutes=offset)
