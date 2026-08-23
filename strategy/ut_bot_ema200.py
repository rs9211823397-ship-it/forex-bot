"""Minimal, causal UT Bot production strategy.

The only indicator event that may create an entry is a confirmed UT Bot
trailing-stop crossover on the latest closed candle.

Risk, account, market-data, portfolio, spread and margin controls remain
outside this module.  They are safety controls, not indicator confirmations.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd


BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


@dataclass(frozen=True)
class UTBotConfig:
    key_value: float = 3.0
    atr_period: int = 10
    signal_confidence: int = 80

    def __post_init__(self) -> None:
        if not isfinite(float(self.key_value)) or self.key_value <= 0:
            raise ValueError("UT Bot key value must be finite and positive")
        if self.atr_period < 1:
            raise ValueError("UT Bot ATR period must be positive")
        if not 1 <= int(self.signal_confidence) <= 100:
            raise ValueError("signal confidence must be between 1 and 100")


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("UT Bot requires a non-empty pandas DataFrame")
    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    result = result.loc[:, ~result.columns.duplicated()].copy()
    required = ("open", "high", "low", "close")
    missing = [column for column in required if column not in result.columns]
    if missing:
        raise ValueError("UT Bot data missing: " + ", ".join(missing))
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    values = result.loc[:, list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("UT Bot OHLC values must be finite")
    if (result["high"] < result[["open", "close"]].max(axis=1)).any():
        raise ValueError("Candle high cannot be below open or close")
    if (result["low"] > result[["open", "close"]].min(axis=1)).any():
        raise ValueError("Candle low cannot be above open or close")
    if (result["high"] < result["low"]).any():
        raise ValueError("Candle high cannot be below low")

    timestamps = None
    if "close_time" in result.columns:
        timestamps = pd.to_datetime(result["close_time"], utc=True, errors="coerce")
    elif isinstance(result.index, pd.DatetimeIndex):
        timestamps = pd.Series(pd.to_datetime(result.index, utc=True), index=result.index)
    if timestamps is not None:
        if timestamps.isna().any():
            raise ValueError("UT Bot candle timestamps must be valid")
        if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
            raise ValueError("UT Bot candle timestamps must be unique and increasing")
    result.attrs.update(dict(getattr(frame, "attrs", {}) or {}))
    return result


def _wilder_rma(values: pd.Series, period: int) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    output = np.full(len(numbers), np.nan, dtype=float)
    if len(numbers) < period:
        return pd.Series(output, index=values.index, dtype=float)
    seed = numbers[:period]
    if np.isfinite(seed).all():
        output[period - 1] = float(seed.mean())
    for index in range(period, len(numbers)):
        current = numbers[index]
        previous = output[index - 1]
        if isfinite(current) and isfinite(previous):
            output[index] = ((period - 1) * previous + current) / period
    return pd.Series(output, index=values.index, dtype=float)


class UTBotStrategy:
    """Calculate features and emit one compatible AAQTS strategy decision."""

    requires_higher_timeframe = False

    def __init__(self, config: UTBotConfig | None = None) -> None:
        self.config = config or UTBotConfig()

    def add_indicators(self, frame: pd.DataFrame) -> pd.DataFrame:
        data = _validated_frame(frame)
        close = data["close"].astype(float)
        previous_close = close.shift(1)
        true_range = pd.concat(
            (
                data["high"] - data["low"],
                (data["high"] - previous_close).abs(),
                (data["low"] - previous_close).abs(),
            ),
            axis=1,
        ).max(axis=1)
        atr = _wilder_rma(true_range, self.config.atr_period)
        trailing = np.full(len(data), np.nan, dtype=float)
        signal = np.full(len(data), HOLD, dtype=object)

        for index in range(len(data)):
            current_atr = float(atr.iloc[index])
            if not isfinite(current_atr):
                continue
            current_close = float(close.iloc[index])
            loss = float(self.config.key_value) * current_atr
            previous_stop = trailing[index - 1] if index > 0 else np.nan
            if not isfinite(float(previous_stop)):
                trailing[index] = current_close - loss
                continue

            prior_close = float(close.iloc[index - 1])
            if current_close > previous_stop and prior_close > previous_stop:
                trailing[index] = max(previous_stop, current_close - loss)
            elif current_close < previous_stop and prior_close < previous_stop:
                trailing[index] = min(previous_stop, current_close + loss)
            elif current_close > previous_stop:
                trailing[index] = current_close - loss
            else:
                trailing[index] = current_close + loss

            buy_cross = prior_close <= previous_stop and current_close > trailing[index]
            sell_cross = prior_close >= previous_stop and current_close < trailing[index]
            if buy_cross:
                signal[index] = BUY
            elif sell_cross:
                signal[index] = SELL

        data["ATR"] = atr
        data["UTBOT_TRAILING_STOP"] = trailing
        data["UTBOT_SIGNAL"] = signal
        data.attrs.update(dict(getattr(frame, "attrs", {}) or {}))
        return data

    def generate_signal(
        self,
        data: pd.DataFrame,
        symbol: str,
        higher_tf: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        return self.generate_analysis(data, symbol, higher_tf)

    def generate_analysis(
        self,
        data: pd.DataFrame,
        symbol: str,
        higher_tf: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        del higher_tf
        required = ("close", "ATR", "UTBOT_SIGNAL")
        if not isinstance(data, pd.DataFrame) or data.empty:
            return self._decision(HOLD, 0, ["UT Bot market data is unavailable"])
        missing = [column for column in required if column not in data.columns]
        if missing:
            return self._decision(
                HOLD,
                0,
                ["UT Bot features missing: " + ", ".join(missing)],
            )
        latest = data.iloc[-1]
        if not all(isfinite(float(latest[column])) for column in ("close", "ATR")):
            return self._decision(
                HOLD,
                0,
                [f"UT Bot warm-up incomplete for {symbol}"],
            )

        signal = str(latest["UTBOT_SIGNAL"]).upper()
        if signal in {BUY, SELL}:
            candle_value = (
                latest.get("close_time")
                if "close_time" in data.columns
                else data.index[-1]
            )
            candle_time = pd.to_datetime(candle_value, utc=True, errors="coerce")
            candle_id = (
                candle_time.isoformat()
                if not pd.isna(candle_time)
                else str(candle_value)
            )
            return self._decision(
                signal,
                self.config.signal_confidence,
                [f"Confirmed UT Bot {signal} crossover"],
                signal_id=f"{str(symbol).upper()}|{candle_id}|{signal}",
            )
        return self._decision(
            HOLD,
            0,
            ["No new UT Bot crossover on the latest closed candle"],
        )

    @staticmethod
    def _decision(
        signal: str,
        confidence: int,
        reasons: list[str],
        *,
        signal_id: str | None = None,
        exit_signal: str | None = None,
    ) -> dict[str, Any]:
        actionable = signal in {BUY, SELL}
        score = confidence if signal == BUY else -confidence if signal == SELL else 0
        primary = reasons[0] if reasons else "No UT Bot decision"
        return {
            "signal": signal,
            "confidence": int(confidence),
            "score": int(score),
            "reasons": list(reasons),
            "decision_summary": {
                "positive": list(reasons) if actionable else [],
                "warnings": [] if actionable else list(reasons),
            },
            "decision_report": {
                "primary_reason": primary,
                "candidate_direction": signal if actionable else None,
                "strategy": "UT_BOT",
                "reasons": list(reasons),
            },
            "strategy": "UT_BOT",
            "signal_id": signal_id,
            # Every UT crossover closes an opposite position and opens the
            # newly indicated direction in the same processing cycle.
            "exit_signal": exit_signal or (signal if actionable else None),
            "regime": "NOT_USED",
            "regime_confidence": 0.0,
            "risk_multiplier": 1.0 if actionable else 0.0,
            "higher_timeframe_regime": "NOT_USED",
            "higher_timeframe_bias": "NOT_USED",
        }


# Backward-compatible aliases for imports created by the earlier deployment.
# They execute the UT-only policy and contain no EMA calculation or veto.
UTBotEMA200Config = UTBotConfig
UTBotEMA200Strategy = UTBotStrategy

__all__ = [
    "BUY",
    "SELL",
    "HOLD",
    "UTBotConfig",
    "UTBotStrategy",
    "UTBotEMA200Config",
    "UTBotEMA200Strategy",
]
