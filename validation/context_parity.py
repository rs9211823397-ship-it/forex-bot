"""Independent parity checks for Python-only directional/context gates.

The reference implementation in this module intentionally does not import the
production structure, context, liquidity, indicator, or timeframe modules.
That separation lets validation catch a regression in those production paths
instead of repeating it through a shared helper.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

import pandas as pd


PARITY_FIELDS = (
    "htf_direction",
    "structure_trend",
    "bos_direction",
    "choch_direction",
    "protected_high",
    "protected_low",
    "context_location",
    "liquidity_event",
    "htf_allows",
    "structure_allows",
    "location_allows",
)


@dataclass(frozen=True)
class _Swing:
    price: float
    kind: str
    formed_index: int
    confirmed_index: int
    classification: str = ""


def _closed_frame(data, decision_time) -> pd.DataFrame:
    frame = data.copy() if isinstance(data, pd.DataFrame) else pd.read_csv(data)
    frame.columns = [str(column).lower() for column in frame.columns]
    required = {"open", "high", "low", "close", "close_time"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("Parity candles missing columns: " + ", ".join(sorted(missing)))
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True, errors="coerce")
    decision = pd.to_datetime(decision_time, utc=True, errors="coerce")
    if pd.isna(decision) or frame["close_time"].isna().any():
        raise ValueError("Parity candles/decision require valid UTC timestamps")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("Parity OHLC values must be numeric")
    frame = frame.loc[frame["close_time"] <= decision].sort_values("close_time")
    if frame.empty:
        raise ValueError("No closed candles exist at the parity decision time")
    return frame.tail(300).reset_index(drop=True)


def _ema(values: pd.Series, span: int) -> float:
    return float(values.ewm(span=span, adjust=False).mean().iloc[-1])


def _htf_direction(frame: pd.DataFrame) -> str:
    close = frame["close"].astype(float)
    if close.empty:
        return "NEUTRAL"
    ema20, ema50, ema200 = (_ema(close, span) for span in (20, 50, 200))
    if ema20 > ema50 > ema200:
        return "BULLISH"
    if ema20 < ema50 < ema200:
        return "BEARISH"
    return "NEUTRAL"


def _swings(frame: pd.DataFrame, radius: int = 3) -> tuple[_Swing, ...]:
    highs = frame["high"].to_numpy(float)
    lows = frame["low"].to_numpy(float)
    candidates: list[_Swing] = []
    for index in range(radius, len(frame) - radius):
        if highs[index] > highs[index - radius:index].max() and highs[index] > highs[index + 1:index + radius + 1].max():
            candidates.append(_Swing(float(highs[index]), "HIGH", index, index + radius))
        if lows[index] < lows[index - radius:index].min() and lows[index] < lows[index + 1:index + radius + 1].min():
            candidates.append(_Swing(float(lows[index]), "LOW", index, index + radius))
    candidates.sort(key=lambda item: (item.confirmed_index, item.formed_index, item.kind))
    alternating: list[_Swing] = []
    for event in candidates:
        if not alternating or alternating[-1].kind != event.kind:
            alternating.append(event)
        elif (event.kind == "HIGH" and event.price > alternating[-1].price) or (
            event.kind == "LOW" and event.price < alternating[-1].price
        ):
            alternating[-1] = event
    previous = {"HIGH": None, "LOW": None}
    classified: list[_Swing] = []
    for event in alternating:
        earlier = previous[event.kind]
        if earlier is None:
            label = ""
        elif event.kind == "HIGH":
            label = "HH" if event.price > earlier else "LH" if event.price < earlier else "EH"
        else:
            label = "HL" if event.price > earlier else "LL" if event.price < earlier else "EL"
        previous[event.kind] = event.price
        classified.append(replace(event, classification=label))
    return tuple(classified)


def _structure(frame: pd.DataFrame) -> dict:
    swings = _swings(frame)
    by_confirmation: dict[int, list[_Swing]] = {}
    for event in swings:
        by_confirmation.setdefault(event.confirmed_index, []).append(event)
    trend = "NEUTRAL"
    high = low = None
    broken: set[tuple[str, int]] = set()
    latest_bos = latest_choch = "NONE"
    final_index = len(frame) - 1
    for index, row in frame.iterrows():
        for event in by_confirmation.get(index, ()): 
            if event.kind == "HIGH":
                high = event
            else:
                low = event
        if trend == "NEUTRAL" and high is not None and low is not None:
            if high.classification == "HH" and low.classification == "HL":
                trend = "BULLISH"
            elif high.classification == "LH" and low.classification == "LL":
                trend = "BEARISH"
        close = float(row["close"])
        if trend == "BULLISH" and low is not None and close < low.price and ("LOW", low.formed_index) not in broken:
            broken.add(("LOW", low.formed_index))
            trend = "BEARISH"
            if index == final_index:
                latest_choch = "BEARISH"
            continue
        if trend == "BEARISH" and high is not None and close > high.price and ("HIGH", high.formed_index) not in broken:
            broken.add(("HIGH", high.formed_index))
            trend = "BULLISH"
            if index == final_index:
                latest_choch = "BULLISH"
            continue
        if trend == "BULLISH" and high is not None and close > high.price and ("HIGH", high.formed_index) not in broken:
            broken.add(("HIGH", high.formed_index))
            if index == final_index:
                latest_bos = "BULLISH"
        elif trend == "BEARISH" and low is not None and close < low.price and ("LOW", low.formed_index) not in broken:
            broken.add(("LOW", low.formed_index))
            if index == final_index:
                latest_bos = "BEARISH"
    return {
        "trend": trend,
        "high": None if high is None else high.price,
        "low": None if low is None else low.price,
        "bos": latest_bos,
        "choch": latest_choch,
    }


def _location(high, low, price) -> str:
    if high is None or low is None or high <= low:
        return "UNAVAILABLE"
    equilibrium = low + (high - low) * 0.5
    lower = low + (high - low) * 0.382
    upper = low + (high - low) * 0.618
    if price == equilibrium:
        return "EQUILIBRIUM"
    if lower <= price < equilibrium:
        return "BULLISH_PULLBACK"
    if equilibrium < price <= upper:
        return "BEARISH_PULLBACK"
    return "DISCOUNT" if price < equilibrium else "PREMIUM"


def _liquidity(frame: pd.DataFrame, high, low) -> str:
    current = frame.iloc[-1]
    previous = frame.iloc[-2] if len(frame) > 1 else None
    high_sweep = high is not None and float(current.high) > high
    low_sweep = low is not None and float(current.low) < low
    previous_high = previous is not None and high is not None and float(previous.high) > high
    previous_low = previous is not None and low is not None and float(previous.low) < low
    high_rejection = high is not None and ((high_sweep and float(current.close) <= high) or (previous_high and float(current.close) <= high and float(current.close) < float(current.open)))
    low_rejection = low is not None and ((low_sweep and float(current.close) >= low) or (previous_low and float(current.close) >= low and float(current.close) > float(current.open)))
    if high_rejection and low_rejection:
        return "DUAL_SWEEP_REJECTION"
    if high_rejection:
        return "SWING_HIGH_SWEEP_REJECTION"
    if low_rejection:
        return "SWING_LOW_SWEEP_REJECTION"
    if high_sweep and low_sweep:
        return "DUAL_SWEEP"
    if high_sweep:
        return "SWING_HIGH_SWEEP"
    if low_sweep:
        return "SWING_LOW_SWEEP"
    return "NONE"


def independent_context_snapshot(lower, higher, *, decision_time, direction) -> dict:
    """Recompute directional/context gates directly from raw closed candles."""

    side = str(direction).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("direction must be BUY or SELL")
    lower_frame = _closed_frame(lower, decision_time)
    higher_frame = _closed_frame(higher, decision_time)
    structure = _structure(lower_frame)
    htf = _htf_direction(higher_frame)
    location = _location(structure["high"], structure["low"], float(lower_frame.iloc[-1].close))
    expected = "BULLISH" if side == "BUY" else "BEARISH"
    return {
        "htf_direction": htf,
        "structure_trend": structure["trend"],
        "bos_direction": structure["bos"],
        "choch_direction": structure["choch"],
        "protected_high": structure["high"],
        "protected_low": structure["low"],
        "context_location": location,
        "liquidity_event": _liquidity(lower_frame, structure["high"], structure["low"]),
        "htf_allows": htf in {expected, "NEUTRAL"},
        "structure_allows": structure["trend"] in {expected, "NEUTRAL"},
        "location_allows": location in ({"DISCOUNT", "BULLISH_PULLBACK"} if side == "BUY" else {"PREMIUM", "BEARISH_PULLBACK"}),
    }


def production_context_snapshot(lower, higher, *, decision_time, direction, lower_timeframe="15m", higher_timeframe="1h") -> dict:
    """Read the same snapshot through the production gate implementations."""

    from data.timeframes import select_closed_candles
    from price_action.liquidity import LiquidityDetector
    from price_action.zones import calculate_zones
    from strategy.multi_timeframe import MultiTimeframeAnalyzer
    from structure.market_structure import MarketStructure

    side = str(direction).strip().upper()
    lower_closed = select_closed_candles(lower, decision_time, lower_timeframe).tail(300)
    state = MarketStructure().state(lower, decision_time, lower_timeframe)
    high = None if state.protected_high is None else float(state.protected_high.price)
    low = None if state.protected_low is None else float(state.protected_low.price)
    zones = calculate_zones(high, low, float(lower_closed.iloc[-1]["close"]))
    liquidity = LiquidityDetector().detect(lower, decision_time, high, low)
    htf = MultiTimeframeAnalyzer.production(higher_timeframe, lower_timeframe).get_regime(higher, decision_time, higher_timeframe)
    expected = "BULLISH" if side == "BUY" else "BEARISH"
    return {
        "htf_direction": htf,
        "structure_trend": state.trend,
        "bos_direction": "NONE" if state.latest_bos is None else state.latest_bos.direction,
        "choch_direction": "NONE" if state.latest_choch is None else state.latest_choch.direction,
        "protected_high": high,
        "protected_low": low,
        "context_location": zones.location,
        "liquidity_event": liquidity.event,
        "htf_allows": htf in {expected, "NEUTRAL"},
        "structure_allows": state.trend in {expected, "NEUTRAL"},
        "location_allows": zones.valid_for_direction(side),
    }


def compare_context_snapshots(production: dict, independent: dict, *, price_tolerance=1e-9) -> dict:
    mismatches = []
    for field in PARITY_FIELDS:
        left, right = production.get(field), independent.get(field)
        if field in {"protected_high", "protected_low"} and left is not None and right is not None:
            matched = isfinite(float(left)) and isfinite(float(right)) and abs(float(left) - float(right)) <= float(price_tolerance)
        else:
            matched = left == right
        if not matched:
            mismatches.append({"field": field, "production": left, "independent": right})
    return {
        "checked_fields": len(PARITY_FIELDS),
        "matched_fields": len(PARITY_FIELDS) - len(mismatches),
        "parity_percent": round((len(PARITY_FIELDS) - len(mismatches)) / len(PARITY_FIELDS) * 100.0, 4),
        "passed": not mismatches,
        "mismatches": mismatches,
    }
