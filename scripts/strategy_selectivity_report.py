#!/usr/bin/env python3
"""Reproducible strategy-only HOLD/action selectivity report.

This is not a profitability backtest. It uses deterministic mixed-regime
candles to expose mutually exclusive primary HOLD gates in the current policy.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from indicators.technical import TechnicalIndicators
from strategy.regime_router import RegimeStrategyRouter
from strategy.signal_engine import SignalEngine


def _frames(rows: int = 1000) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(20260810)
    times = pd.date_range("2025-01-01T00:00:00Z", periods=rows, freq="15min")
    segment = rows // 4
    returns = np.empty(rows)
    returns[:segment] = rng.normal(0.00030, 0.00045, segment)
    returns[segment : 2 * segment] = (
        np.sin(np.linspace(0, 12 * np.pi, segment)) * 0.00025
        + rng.normal(0, 0.00028, segment)
    )
    returns[2 * segment : 3 * segment] = rng.normal(-0.00030, 0.00045, segment)
    returns[3 * segment :] = rng.normal(0, 0.00125, rows - 3 * segment)
    close = 1800.0 * np.exp(np.cumsum(returns))
    open_price = np.r_[close[0], close[:-1]]
    body = np.abs(close - open_price)
    wick = np.maximum(close * rng.uniform(0.00015, 0.00065, rows), body * 0.25)
    lower = pd.DataFrame(
        {
            "open_time": times,
            "close_time": times + pd.Timedelta(minutes=15),
            "open": open_price,
            "high": np.maximum(open_price, close) + wick,
            "low": np.minimum(open_price, close) - wick,
            "close": close,
            "volume": rng.integers(600, 1800, rows).astype(float),
        },
        index=times,
    )
    higher = lower.groupby(np.arange(rows) // 4, sort=True).agg(
        open_time=("open_time", "first"),
        close_time=("close_time", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    return lower, higher.reset_index(drop=True)


def _hold_bucket(result: dict) -> str:
    strategy = str(result.get("strategy", ""))
    if strategy == "NO_TRADE":
        return "regime_gate"
    if strategy == "BREAKOUT":
        return "breakout_confirmation"
    report = result.get("decision_report") or {}
    primary = str(report.get("primary_reason") or "").lower()
    if "contextual" in primary or "invalid_location" in primary:
        return "contextual_gate"
    if "higher timeframe" in primary:
        return "htf_gate"
    if "market structure" in primary:
        return "structure_gate"
    if "rsi" in primary and ("conflict" in primary or "blocks" in primary):
        return "rsi_extreme_gate"
    if "trade quality" in primary:
        return "quality_gate"
    if "no directional setup" in primary:
        return "setup_direction_gate"
    return "other_hold"


def _percentages(values: Counter, denominator: int) -> dict[str, dict[str, float]]:
    return {
        key: {"count": count, "percent": round(100.0 * count / denominator, 2)}
        for key, count in sorted(values.items())
    }


def main() -> None:
    lower, higher = _frames()
    data = TechnicalIndicators().add_indicators(lower).dropna()
    engine = RegimeStrategyRouter(
        SignalEngine.production(higher_timeframe="1h", lower_timeframe="15m"),
        higher_timeframe="1h",
        lower_timeframe="15m",
    )
    results = []
    for index in range(max(250, len(data) - 700), len(data)):
        window = data.iloc[max(0, index - 250) : index + 1]
        results.append(engine.generate_analysis(window, "ETH-USD", higher))

    signals = Counter(str(item.get("signal", "UNKNOWN")) for item in results)
    holds = [item for item in results if item.get("signal") == "HOLD"]
    candidates = [
        item
        for item in results
        if (item.get("decision_report") or {}).get("candidate_direction") in {"BUY", "SELL"}
    ]
    report = {
        "decisions": len(results),
        "signals": _percentages(signals, len(results)),
        "hold_rate_percent": round(100.0 * len(holds) / len(results), 2),
        "action_rate_percent": round(100.0 * (len(results) - len(holds)) / len(results), 2),
        "candidate_decisions": len(candidates),
        "candidate_acceptance_percent": round(
            100.0 * sum(item.get("signal") in {"BUY", "SELL"} for item in candidates)
            / len(candidates),
            2,
        ) if candidates else 0.0,
        "exclusive_primary_hold_bucket": _percentages(
            Counter(_hold_bucket(item) for item in holds),
            len(holds),
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
