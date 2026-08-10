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

AUDIT_POLICY = {
    "min_adx": 12.0,
    "signal_score_threshold": 35,
    "min_signal_confirmations": 1,
    "min_trade_quality": 35,
    "min_regime_confidence": 35.0,
}

from indicators.technical import TechnicalIndicators
import ai.decision_analyzer as decision_report_policy
import ai.trade_quality as trade_quality_policy
from strategy.regime_detector import MarketRegimeDetector
from strategy.regime_router import RegimeStrategyRouter
from strategy.signal_engine import SignalEngine
import strategy.signal_engine as signal_policy
import strategy.validators as validation_policy


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


def _replay(data, higher, indexes, symbol="ETH-USD"):
    signal_engine = SignalEngine.production(
        higher_timeframe="1h",
        lower_timeframe="15m",
    )
    signal_engine.pipeline.BUY_THRESHOLD = AUDIT_POLICY["signal_score_threshold"]
    signal_engine.pipeline.SELL_THRESHOLD = -AUDIT_POLICY["signal_score_threshold"]
    signal_engine.pipeline.MIN_CONFIRMATIONS = AUDIT_POLICY[
        "min_signal_confirmations"
    ]
    signal_engine.pipeline.HIGH_CONVICTION_QUALITY = AUDIT_POLICY[
        "min_trade_quality"
    ]
    engine = RegimeStrategyRouter(
        signal_engine,
        higher_timeframe="1h",
        lower_timeframe="15m",
        detector=MarketRegimeDetector(
            adx_trend_threshold=AUDIT_POLICY["min_adx"],
            adx_range_threshold=AUDIT_POLICY["min_adx"],
        ),
        minimum_regime_confidence=AUDIT_POLICY["min_regime_confidence"],
    )
    original_policy = {
        "min_adx": validation_policy.MIN_ADX,
        "trade_quality": trade_quality_policy.MIN_TRADE_QUALITY,
        "decision_quality": decision_report_policy.MIN_TRADE_QUALITY,
    }
    try:
        validation_policy.MIN_ADX = AUDIT_POLICY["min_adx"]
        trade_quality_policy.MIN_TRADE_QUALITY = AUDIT_POLICY["min_trade_quality"]
        decision_report_policy.MIN_TRADE_QUALITY = AUDIT_POLICY[
            "min_trade_quality"
        ]
        return [
            engine.generate_analysis(
                data.iloc[max(0, index - 250) : index + 1],
                symbol,
                higher,
            )
            for index in indexes
        ]
    finally:
        validation_policy.MIN_ADX = original_policy["min_adx"]
        trade_quality_policy.MIN_TRADE_QUALITY = original_policy["trade_quality"]
        decision_report_policy.MIN_TRADE_QUALITY = original_policy[
            "decision_quality"
        ]


def _summary(results):
    signals = Counter(str(item.get("signal", "UNKNOWN")) for item in results)
    holds = [item for item in results if item.get("signal") == "HOLD"]
    candidates = [
        item
        for item in results
        if (item.get("decision_report") or {}).get("candidate_direction")
        in {"BUY", "SELL"}
    ]
    return {
        "decisions": len(results),
        "signals": _percentages(signals, len(results)),
        "hold_rate_percent": round(100.0 * len(holds) / len(results), 2),
        "action_rate_percent": round(
            100.0 * (len(results) - len(holds)) / len(results), 2
        ),
        "candidate_decisions": len(candidates),
        "candidate_acceptance_percent": round(
            100.0
            * sum(item.get("signal") in {"BUY", "SELL"} for item in candidates)
            / len(candidates),
            2,
        )
        if candidates
        else 0.0,
        "exclusive_primary_hold_bucket": _percentages(
            Counter(_hold_bucket(item) for item in holds),
            len(holds),
        ),
    }


def _is_strong_trend(item) -> bool:
    return bool(
        item.get("regime") in {"TREND_UP", "TREND_DOWN"}
        and float(item.get("regime_confidence", 0.0)) >= 70.0
    )


def _action_count(results) -> int:
    return sum(item.get("signal") in {"BUY", "SELL"} for item in results)


def _scope(data, indexes) -> dict:
    if not indexes:
        raise ValueError("Selectivity report requires at least one decision")
    first_close = pd.Timestamp(data.iloc[indexes[0]]["close_time"])
    last_close = pd.Timestamp(data.iloc[indexes[-1]]["close_time"])
    elapsed = last_close - first_close
    return {
        "source": "deterministic_synthetic_mixed_regime",
        "symbols": ["ETH-USD"],
        "symbol_count": 1,
        "timeframe": "15m",
        "first_decision_close_utc": first_close.isoformat(),
        "last_decision_close_utc": last_close.isoformat(),
        "elapsed_hours": round(elapsed.total_seconds() / 3600.0, 2),
        "elapsed_days": round(elapsed.total_seconds() / 86400.0, 4),
        "frequency_warning": (
            "Strategy decisions are not broker orders; duplicate-position, "
            "cooldown, portfolio, sizing and execution gates apply later."
        ),
    }


def main() -> None:
    lower, higher = _frames()
    data = TechnicalIndicators().add_indicators(lower).dropna()
    indexes = list(range(max(250, len(data) - 700), len(data)))
    results = _replay(data, higher, indexes)

    original_overbought = signal_policy.RSI_BAND_VETO_OVERBOUGHT
    original_oversold = signal_policy.RSI_BAND_VETO_OVERSOLD
    try:
        signal_policy.RSI_BAND_VETO_OVERBOUGHT = float("inf")
        signal_policy.RSI_BAND_VETO_OVERSOLD = float("-inf")
        without_rsi_veto = _replay(data, higher, indexes)
    finally:
        signal_policy.RSI_BAND_VETO_OVERBOUGHT = original_overbought
        signal_policy.RSI_BAND_VETO_OVERSOLD = original_oversold

    strong_pairs = [
        (current, ablated)
        for current, ablated in zip(results, without_rsi_veto)
        if _is_strong_trend(current)
    ]
    strong_current = [item[0] for item in strong_pairs]
    strong_ablated = [item[1] for item in strong_pairs]

    report = _summary(results)
    report["policy"] = dict(AUDIT_POLICY)
    report["scope"] = _scope(data, indexes)
    report["rsi_strong_trend_ablation"] = {
        "strong_trend_definition": (
            "TREND_UP/TREND_DOWN with regime confidence at least 70"
        ),
        "rsi_veto_policy": (
            f"RSI >= {original_overbought:g} or <= {original_oversold:g} only "
            "with matching Bollinger extreme and opposing reversal candle"
        ),
        "strong_trend_decisions": len(strong_current),
        "current_actionable": _action_count(strong_current),
        "actionable_with_rsi_veto_disabled": _action_count(strong_ablated),
        "continuation_decisions_blocked": sum(
            current.get("signal") != ablated.get("signal")
            for current, ablated in strong_pairs
        ),
        "blocked_percent_of_strong_trend": round(
            100.0
            * sum(
                current.get("signal") != ablated.get("signal")
                for current, ablated in strong_pairs
            )
            / len(strong_pairs),
            4,
        )
        if strong_pairs
        else 0.0,
        "all_decision_changes": sum(
            current.get("signal") != ablated.get("signal")
            for current, ablated in zip(results, without_rsi_veto)
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
