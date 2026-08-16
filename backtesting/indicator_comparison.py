"""Causal indicator-strategy comparison for AAQTS research.

The module intentionally stays outside the production decision engine.  It is
used to compare small, explicit indicator rules without regime, contextual,
portfolio, or AI gates changing the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

import numpy as np
import pandas as pd


BUY = "BUY"
SELL = "SELL"
VALID_SIDES = {BUY, SELL}


@dataclass(frozen=True)
class IndicatorEvent:
    """One closed-candle event and whether it may open a new position."""

    side: str
    entry_allowed: bool = True

    def __post_init__(self) -> None:
        normalized = str(self.side).strip().upper()
        if normalized not in VALID_SIDES:
            raise ValueError("IndicatorEvent side must be BUY or SELL")
        object.__setattr__(self, "side", normalized)


@dataclass(frozen=True)
class ComparisonConfig:
    """Shared execution assumptions applied to both candidate strategies."""

    initial_equity: float = 1_000.0
    catastrophe_stop_percent: float = 1.0
    round_trip_cost_bps: float = 5.0

    def __post_init__(self) -> None:
        values = {
            "initial_equity": self.initial_equity,
            "catastrophe_stop_percent": self.catastrophe_stop_percent,
            "round_trip_cost_bps": self.round_trip_cost_bps,
        }
        for name, value in values.items():
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be greater than zero")
        if not 0 < self.catastrophe_stop_percent <= 20:
            raise ValueError(
                "catastrophe_stop_percent must be greater than zero and at most 20"
            )
        if not 0 <= self.round_trip_cost_bps <= 1_000:
            raise ValueError("round_trip_cost_bps must be between zero and 1000")


def _validated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(
            "Indicator comparison data missing columns: "
            + ", ".join(sorted(missing))
        )
    if frame.empty:
        raise ValueError("Indicator comparison data cannot be empty")

    result = frame.copy()
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result[list(required)].isna().any().any():
        raise ValueError("OHLCV values must be numeric and non-missing")
    numeric = result[list(required)].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("OHLCV values must be finite")
    if (result["high"] < result[["open", "close"]].max(axis=1)).any():
        raise ValueError("Candle high cannot be below open or close")
    if (result["low"] > result[["open", "close"]].min(axis=1)).any():
        raise ValueError("Candle low cannot be above open or close")
    if (result["high"] < result["low"]).any():
        raise ValueError("Candle high cannot be below low")

    timestamps = _timestamps(result)
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("Candle timestamps must be unique and increasing")
    return result


def _timestamps(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "open_time" in frame.columns:
        values = frame["open_time"]
    elif isinstance(frame.index, pd.DatetimeIndex):
        values = frame.index
    else:
        raise ValueError("Data requires open_time or a DatetimeIndex")
    timestamps = pd.DatetimeIndex(pd.to_datetime(values, utc=True, errors="raise"))
    if timestamps.hasnans:
        raise ValueError("Candle timestamps cannot be missing")
    return timestamps


def _rma(values: pd.Series, period: int) -> pd.Series:
    """TradingView-compatible Wilder moving average used by ``ta.atr``."""

    if period < 1:
        raise ValueError("period must be positive")
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


def atr(frame: pd.DataFrame, period: int = 10) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return _rma(true_range, period)


def ut_bot_ema200_events(
    frame: pd.DataFrame,
    *,
    key_value: float = 3.0,
    atr_period: int = 10,
    ema_period: int = 200,
) -> tuple[list[IndicatorEvent | None], pd.DataFrame]:
    """Return confirmed UT Bot crosses filtered by EMA200 for new entries.

    A raw opposite UT Bot cross always closes an existing position.  The cross
    may reverse into a new position only when the close is on the permitted side
    of EMA200.
    """

    data = _validated_frame(frame)
    if not isfinite(float(key_value)) or key_value <= 0:
        raise ValueError("key_value must be finite and positive")
    if atr_period < 1 or ema_period < 1:
        raise ValueError("ATR and EMA periods must be positive")

    close = data["close"].astype(float)
    atr_values = atr(data, atr_period)
    ema200 = close.ewm(
        span=ema_period,
        adjust=False,
        min_periods=ema_period,
    ).mean()
    trailing = np.full(len(data), np.nan, dtype=float)
    events: list[IndicatorEvent | None] = [None] * len(data)

    for index in range(len(data)):
        current_atr = float(atr_values.iloc[index])
        if not isfinite(current_atr):
            continue
        current_close = float(close.iloc[index])
        loss = float(key_value) * current_atr
        previous_stop = trailing[index - 1] if index > 0 else np.nan

        if not isfinite(float(previous_stop)):
            trailing[index] = current_close - loss
            continue

        previous_close = float(close.iloc[index - 1])
        if current_close > previous_stop and previous_close > previous_stop:
            trailing[index] = max(previous_stop, current_close - loss)
        elif current_close < previous_stop and previous_close < previous_stop:
            trailing[index] = min(previous_stop, current_close + loss)
        elif current_close > previous_stop:
            trailing[index] = current_close - loss
        else:
            trailing[index] = current_close + loss

        buy_cross = previous_close <= previous_stop and current_close > trailing[index]
        sell_cross = previous_close >= previous_stop and current_close < trailing[index]
        current_ema = float(ema200.iloc[index])
        if buy_cross:
            events[index] = IndicatorEvent(
                BUY,
                entry_allowed=isfinite(current_ema) and current_close > current_ema,
            )
        elif sell_cross:
            events[index] = IndicatorEvent(
                SELL,
                entry_allowed=isfinite(current_ema) and current_close < current_ema,
            )

    diagnostics = pd.DataFrame(
        {
            "ATR": atr_values,
            "EMA_200": ema200,
            "UT_TRAILING_STOP": trailing,
        },
        index=data.index,
    )
    return events, diagnostics


def vwap_ema9_events(
    frame: pd.DataFrame,
    *,
    ema_period: int = 9,
) -> tuple[list[IndicatorEvent | None], pd.DataFrame]:
    """Return daily-reset VWAP/EMA9 crossover events from closed candles."""

    data = _validated_frame(frame)
    if ema_period < 1:
        raise ValueError("ema_period must be positive")
    close = data["close"].astype(float)
    typical = (
        data["high"].astype(float)
        + data["low"].astype(float)
        + close
    ) / 3.0
    volume = data["volume"].astype(float).clip(lower=0.0)
    weights = volume.where(volume > 0.0, 1.0)
    timestamps = _timestamps(data)
    sessions = pd.Series(timestamps.floor("D"), index=data.index)
    numerator = (typical * weights).groupby(sessions).cumsum()
    denominator = weights.groupby(sessions).cumsum()
    vwap = numerator / denominator
    ema9 = close.ewm(
        span=ema_period,
        adjust=False,
        min_periods=ema_period,
    ).mean()
    events: list[IndicatorEvent | None] = [None] * len(data)

    for index in range(1, len(data)):
        # A new daily anchor must not manufacture a crossover against the
        # previous session's final VWAP.
        if sessions.iloc[index] != sessions.iloc[index - 1]:
            continue
        current_ema = float(ema9.iloc[index])
        previous_ema = float(ema9.iloc[index - 1])
        current_vwap = float(vwap.iloc[index])
        previous_vwap = float(vwap.iloc[index - 1])
        if not all(
            isfinite(value)
            for value in (current_ema, previous_ema, current_vwap, previous_vwap)
        ):
            continue
        if previous_ema <= previous_vwap and current_ema > current_vwap:
            events[index] = IndicatorEvent(BUY)
        elif previous_ema >= previous_vwap and current_ema < current_vwap:
            events[index] = IndicatorEvent(SELL)

    diagnostics = pd.DataFrame(
        {"EMA_9": ema9, "VWAP": vwap, "VWAP_SESSION": sessions},
        index=data.index,
    )
    return events, diagnostics


def _maximum_drawdown_percent(equity: Iterable[float]) -> float:
    values = list(float(value) for value in equity)
    if not values:
        return 0.0
    peak = values[0]
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, (peak - value) / peak * 100.0)
    return maximum


def _trade_metrics(
    trades: list[dict[str, object]],
    *,
    initial_equity: float,
) -> dict[str, float | int | None]:
    returns = [float(trade["net_return"]) for trade in trades]
    profits = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    equity = [float(initial_equity)]
    for value in returns:
        equity.append(equity[-1] * (1.0 + value))
    gross_profit = sum(profits)
    gross_loss = abs(sum(losses))
    profit_factor: float | None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = None
    else:
        profit_factor = 0.0
    return {
        "completed_trades": len(trades),
        "winning_trades": len(profits),
        "losing_trades": len(losses),
        "win_rate_percent": (len(profits) / len(trades) * 100.0) if trades else 0.0,
        "net_return_percent": (equity[-1] / initial_equity - 1.0) * 100.0,
        "profit_factor": profit_factor,
        "expectancy_percent": (sum(returns) / len(returns) * 100.0) if returns else 0.0,
        "max_drawdown_percent": _maximum_drawdown_percent(equity),
        "average_holding_bars": (
            sum(int(trade["holding_bars"]) for trade in trades) / len(trades)
            if trades
            else 0.0
        ),
        "ending_equity": equity[-1],
    }


def simulate_indicator_strategy(
    frame: pd.DataFrame,
    events: list[IndicatorEvent | None],
    *,
    strategy_name: str,
    symbol: str,
    config: ComparisonConfig | None = None,
) -> tuple[list[dict[str, object]], dict[str, float | int | None]]:
    """Execute confirmed events at the next candle open with one position."""

    data = _validated_frame(frame)
    if len(events) != len(data):
        raise ValueError("events length must equal candle count")
    settings = config or ComparisonConfig()
    timestamps = _timestamps(data)
    cost_rate = settings.round_trip_cost_bps / 10_000.0
    stop_fraction = settings.catastrophe_stop_percent / 100.0
    position: dict[str, object] | None = None
    pending: IndicatorEvent | None = None
    trades: list[dict[str, object]] = []

    def close_position(
        *,
        reference_price: float,
        exit_index: int,
        reason: str,
    ) -> None:
        nonlocal position
        assert position is not None
        entry_price = float(position["entry_price"])
        side = str(position["side"])
        direction = 1.0 if side == BUY else -1.0
        gross_return = direction * (float(reference_price) / entry_price - 1.0)
        net_return = gross_return - cost_rate
        trades.append(
            {
                "symbol": str(symbol),
                "strategy": str(strategy_name),
                "side": side,
                "entry_time": position["entry_time"],
                "exit_time": timestamps[exit_index],
                "entry_price": entry_price,
                "exit_price": float(reference_price),
                "gross_return": gross_return,
                "cost_return": cost_rate,
                "net_return": net_return,
                "net_return_percent": net_return * 100.0,
                "holding_bars": exit_index - int(position["entry_index"]),
                "exit_reason": str(reason),
            }
        )
        position = None

    for index, row in enumerate(data.itertuples(index=False)):
        open_price = float(row.open)

        # The prior candle's confirmed signal is actionable only now.
        if pending is not None:
            if position is not None and str(position["side"]) != pending.side:
                close_position(
                    reference_price=open_price,
                    exit_index=index,
                    reason="OPPOSITE_SIGNAL",
                )
            if position is None and pending.entry_allowed:
                side = pending.side
                stop = (
                    open_price * (1.0 - stop_fraction)
                    if side == BUY
                    else open_price * (1.0 + stop_fraction)
                )
                position = {
                    "side": side,
                    "entry_price": open_price,
                    "entry_index": index,
                    "entry_time": timestamps[index],
                    "stop": stop,
                }
            pending = None

        if position is not None:
            side = str(position["side"])
            stop = float(position["stop"])
            high = float(row.high)
            low = float(row.low)
            # A gap through the stop fills at the less favorable candle open;
            # an intrabar touch fills at the stop.  Assuming a stop fill above
            # the market after a gap would systematically overstate results.
            if side == BUY and open_price <= stop:
                close_position(
                    reference_price=open_price,
                    exit_index=index,
                    reason="CATASTROPHE_STOP_GAP",
                )
            elif side == BUY and low <= stop:
                close_position(
                    reference_price=stop,
                    exit_index=index,
                    reason="CATASTROPHE_STOP",
                )
            elif side == SELL and open_price >= stop:
                close_position(
                    reference_price=open_price,
                    exit_index=index,
                    reason="CATASTROPHE_STOP_GAP",
                )
            elif side == SELL and high >= stop:
                close_position(
                    reference_price=stop,
                    exit_index=index,
                    reason="CATASTROPHE_STOP",
                )

        if index + 1 < len(data) and events[index] is not None:
            pending = events[index]

    if position is not None:
        close_position(
            reference_price=float(data["close"].iloc[-1]),
            exit_index=len(data) - 1,
            reason="END_OF_DATA",
        )

    return trades, _trade_metrics(
        trades,
        initial_equity=settings.initial_equity,
    )


def strategy_metrics_with_holdout(
    frame: pd.DataFrame,
    events: list[IndicatorEvent | None],
    *,
    strategy_name: str,
    symbol: str,
    config: ComparisonConfig | None = None,
    holdout_fraction: float = 0.30,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between zero and one")
    data = _validated_frame(frame)
    settings = config or ComparisonConfig()
    trades, full = simulate_indicator_strategy(
        data,
        events,
        strategy_name=strategy_name,
        symbol=symbol,
        config=settings,
    )
    split_position = max(1, min(len(data) - 1, int(len(data) * (1.0 - holdout_fraction))))
    split_time = _timestamps(data)[split_position]
    out_of_sample_trades = [
        trade
        for trade in trades
        if pd.Timestamp(trade["entry_time"]) >= split_time
    ]
    out_of_sample = _trade_metrics(
        out_of_sample_trades,
        initial_equity=settings.initial_equity,
    )
    return trades, {
        "full": full,
        "out_of_sample": out_of_sample,
        "split_time": split_time.isoformat(),
        "candles": len(data),
    }


__all__ = [
    "BUY",
    "SELL",
    "ComparisonConfig",
    "IndicatorEvent",
    "atr",
    "simulate_indicator_strategy",
    "strategy_metrics_with_holdout",
    "ut_bot_ema200_events",
    "vwap_ema9_events",
]
