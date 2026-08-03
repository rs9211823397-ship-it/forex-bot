"""Deterministic, offline backtest smoke test used by CI and release checks."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from config.instruments import get_instrument_spec
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine


SYMBOL = "ETH-USD"
LOWER_TIMEFRAME = "15m"
HIGHER_TIMEFRAME = "1h"


def synthetic_frames(rows: int = 600) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build repeatable closed-candle lower and higher-timeframe frames."""

    rng = np.random.default_rng(20260803)
    open_times = pd.date_range(
        "2024-01-01T00:00:00Z", periods=rows, freq="15min"
    )
    drift = np.linspace(0.0, 12.0, rows)
    cycle = np.sin(np.linspace(0.0, 16.0 * np.pi, rows)) * 2.0
    noise = rng.normal(0.0, 0.18, rows).cumsum()
    close = 1_800.0 + drift + cycle + noise
    open_price = np.r_[close[0], close[:-1]]
    spread = 0.6 + rng.uniform(0.0, 0.5, rows)

    lower = pd.DataFrame(
        {
            "open_time": open_times,
            "close_time": open_times + pd.Timedelta(minutes=15),
            "open": open_price,
            "high": np.maximum(open_price, close) + spread,
            "low": np.minimum(open_price, close) - spread,
            "close": close,
            "volume": rng.integers(800, 1_600, rows).astype(float),
        },
        index=open_times,
    )

    groups = np.arange(rows) // 4
    higher = lower.groupby(groups, sort=True).agg(
        open_time=("open_time", "first"),
        close_time=("close_time", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return lower, higher.reset_index(drop=True)


def run() -> dict:
    lower, higher = synthetic_frames()
    data = TechnicalIndicators().add_indicators(lower).dropna().tail(500)
    engine = SignalEngine.production(
        higher_timeframe=HIGHER_TIMEFRAME,
        lower_timeframe=LOWER_TIMEFRAME,
    )
    signals = []

    for index in range(len(data)):
        if index < 100:
            signals.append("HOLD")
            continue
        window = data.iloc[max(0, index - 250):index + 1]
        result = engine.generate_signal(window, SYMBOL, higher)
        signals.append(result["signal"])

    directional_signals = sum(
        signal in {"BUY", "SELL"} for signal in signals
    )
    smoke_fallback_used = directional_signals == 0
    execution_signals = list(signals)
    if smoke_fallback_used:
        # The strategy is intentionally selective. Exercise next-bar fills and
        # cost accounting even when this synthetic sample has no qualified
        # setup; this is a release smoke test, not a profitability claim.
        execution_signals[100] = "BUY"

    backtest = BacktestEngine(
        data,
        lambda index: execution_signals[index],
        instrument=get_instrument_spec(SYMBOL),
        force_close=True,
    )
    trades = backtest.run()
    report = PerformanceReport(
        trades,
        initial_equity=backtest.initial_equity,
        equity_curve=backtest.equity_history,
    )
    summary = report.summary()
    summary["Generated Strategy Signals"] = directional_signals
    summary["Smoke Fallback Used"] = smoke_fallback_used
    print("FAST BACKTEST REPORT")
    print(summary)
    return summary


if __name__ == "__main__":
    run()
