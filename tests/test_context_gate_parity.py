import numpy as np
import pandas as pd

from validation.context_parity import (
    compare_context_snapshots,
    independent_context_snapshot,
    production_context_snapshot,
)


def candles(periods, frequency, *, base=100.0, drift=0.02):
    close_time = pd.date_range("2026-01-01", periods=periods, freq=frequency, tz="UTC")
    wave = np.sin(np.arange(periods) / 4.0) * 1.2
    close = base + np.arange(periods) * drift + wave
    open_ = close - np.cos(np.arange(periods) / 5.0) * 0.15
    return pd.DataFrame({
        "close_time": close_time,
        "open": open_,
        "high": np.maximum(open_, close) + 0.35,
        "low": np.minimum(open_, close) - 0.35,
        "close": close,
        "volume": 1000.0,
    })


def test_independent_context_reference_matches_production_snapshot():
    lower = candles(280, "15min")
    higher = candles(240, "1h", drift=0.05)
    decision = lower.iloc[-1]["close_time"]
    independent = independent_context_snapshot(lower, higher, decision_time=decision, direction="BUY")
    production = production_context_snapshot(lower, higher, decision_time=decision, direction="BUY")

    report = compare_context_snapshots(production, independent)

    assert report["passed"] is True
    assert report["parity_percent"] == 100.0


def test_context_parity_reports_one_gate_regression():
    production = {"htf_direction": "BULLISH"}
    independent = {"htf_direction": "BEARISH"}
    report = compare_context_snapshots(production, independent)
    assert report["passed"] is False
    assert any(item["field"] == "htf_direction" for item in report["mismatches"])
