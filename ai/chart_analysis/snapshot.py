from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass
from datetime import timezone
from typing import Any

import pandas as pd

LOWER_INDICATORS = (
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "RSI",
    "STOCH_RSI",
    "MACD",
    "MACD_SIGNAL",
    "ATR",
    "ADX",
    "BB_MIDDLE",
    "BB_UPPER",
    "BB_LOWER",
    "VOL_SMA20",
    "OBV",
    "SUPERTREND",
)

HIGHER_INDICATORS = (
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "RSI",
    "ATR",
    "ADX",
    "BB_MIDDLE",
    "BB_UPPER",
    "BB_LOWER",
    "SUPERTREND",
)


def _utc_iso(value: object) -> str:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.to_pydatetime().astimezone(timezone.utc).isoformat()


def _finite(value: object) -> float | bool | None:
    if isinstance(value, (bool,)):
        return bool(value)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _causal_frame(frame: pd.DataFrame, as_of: object) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("AI chart snapshot requires non-empty market data")
    if "close_time" not in frame.columns:
        raise ValueError("AI chart snapshot requires close_time for causal alignment")

    cutoff = pd.Timestamp(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    close_times = pd.to_datetime(frame["close_time"], utc=True, errors="raise")
    causal = frame.loc[close_times <= cutoff].copy()
    if causal.empty:
        raise ValueError("No completed candles exist at or before snapshot as_of")
    causal.attrs.update(dict(getattr(frame, "attrs", {}) or {}))
    return causal


def _compact_bars(frame: pd.DataFrame, count: int) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for index, row in frame.tail(int(count)).iterrows():
        result.append(
            {
                "open_time": _utc_iso(index),
                "close_time": _utc_iso(row["close_time"]),
                "open": _finite(row.get("open")),
                "high": _finite(row.get("high")),
                "low": _finite(row.get("low")),
                "close": _finite(row.get("close")),
                "volume": _finite(row.get("volume")),
            }
        )
    return tuple(result)


def _latest_indicators(
    frame: pd.DataFrame,
    names: tuple[str, ...],
) -> dict[str, float | bool | None]:
    latest = frame.iloc[-1]
    return {name: _finite(latest.get(name)) for name in names if name in frame.columns}


@dataclass(frozen=True)
class MarketSnapshot:
    schema_version: str
    snapshot_id: str
    symbol: str
    as_of_utc: str
    lower_timeframe: str
    higher_timeframe: str
    source: str
    broker_symbol: str | None
    lower_bars: tuple[dict[str, Any], ...]
    higher_bars: tuple[dict[str, Any], ...]
    lower_indicators: dict[str, float | bool | None]
    higher_indicators: dict[str, float | bool | None]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["lower_bars"] = list(self.lower_bars)
        result["higher_bars"] = list(self.higher_bars)
        return result


def build_market_snapshot(
    *,
    symbol: str,
    lower_frame: pd.DataFrame,
    higher_frame: pd.DataFrame,
    lower_timeframe: str,
    higher_timeframe: str,
    numeric_bars: int = 24,
    schema_version: str = "1.0",
) -> MarketSnapshot:
    if lower_frame is None or lower_frame.empty:
        raise ValueError("Lower-timeframe frame is empty")
    if "close_time" not in lower_frame.columns:
        raise ValueError("Lower-timeframe frame is missing close_time")

    # The newest completed lower-timeframe candle is the authoritative decision
    # timestamp. Both timeframes are then truncated to this exact cutoff so the
    # observer cannot see a higher-timeframe candle that closed in the future.
    as_of = pd.to_datetime(
        lower_frame["close_time"].iloc[-1],
        utc=True,
        errors="raise",
    )
    lower = _causal_frame(lower_frame, as_of)
    higher = _causal_frame(higher_frame, as_of)

    as_of_utc = _utc_iso(as_of)
    safe_symbol = re.sub(r"[^A-Za-z0-9]+", "_", str(symbol)).strip("_") or "symbol"
    identity = (
        f"{symbol}|{as_of_utc}|{lower_timeframe}|{higher_timeframe}|"
        f"{float(lower['close'].iloc[-1]):.12g}|{len(lower)}|{len(higher)}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    timestamp = pd.Timestamp(as_of).strftime("%Y%m%dT%H%M%SZ")
    snapshot_id = f"{safe_symbol}_{timestamp}_{digest}"

    attrs = dict(getattr(lower_frame, "attrs", {}) or {})
    source = str(attrs.get("source", "UNKNOWN"))
    broker_symbol = attrs.get("broker_symbol")

    return MarketSnapshot(
        schema_version=str(schema_version),
        snapshot_id=snapshot_id,
        symbol=str(symbol),
        as_of_utc=as_of_utc,
        lower_timeframe=str(lower_timeframe),
        higher_timeframe=str(higher_timeframe),
        source=source,
        broker_symbol=(str(broker_symbol) if broker_symbol else None),
        lower_bars=_compact_bars(lower, numeric_bars),
        higher_bars=_compact_bars(higher, numeric_bars),
        lower_indicators=_latest_indicators(lower, LOWER_INDICATORS),
        higher_indicators=_latest_indicators(higher, HIGHER_INDICATORS),
    )


def causal_render_frame(
    frame: pd.DataFrame,
    *,
    as_of_utc: str,
    bars: int,
) -> pd.DataFrame:
    """Return only completed candles visible at snapshot time for rendering."""

    return _causal_frame(frame, as_of_utc).tail(int(bars)).copy()
