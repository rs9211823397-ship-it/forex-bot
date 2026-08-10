"""Compare broker-observed entry slippage with backtest assumptions."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

import pandas as pd


def _records(value):
    if isinstance(value, pd.DataFrame):
        return value.copy()
    path = Path(value)
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid fill-audit JSON on line {line_number}") from exc
    return pd.DataFrame(rows)


def slippage_report(fills, *, min_fills=20, min_symbol_fills=3, max_p95_assumption_ratio=1.0, expected_symbols=None):
    if int(min_fills) < 1 or int(min_symbol_fills) < 1:
        raise ValueError("slippage sample minimums must be positive")
    if not isfinite(float(max_p95_assumption_ratio)) or float(max_p95_assumption_ratio) <= 0:
        raise ValueError("max_p95_assumption_ratio must be positive and finite")
    frame = _records(fills)
    required = {
        "timestamp", "source_symbol", "request_price", "fill_price",
        "fill_price_source", "adverse_slippage_price", "assumed_slippage_price",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError("Fill audit missing columns: " + ", ".join(sorted(missing)))
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["source_symbol"] = frame["source_symbol"].astype(str).str.strip().str.upper()
    for column in ("request_price", "fill_price", "adverse_slippage_price", "assumed_slippage_price"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    fallback_rows = int((frame["fill_price_source"] != "broker_result").sum())
    frame = frame[frame["fill_price_source"] == "broker_result"].copy()
    valid = frame.dropna(subset=["timestamp", "request_price", "fill_price", "adverse_slippage_price", "assumed_slippage_price"])
    valid = valid[(valid["request_price"] > 0) & (valid["assumed_slippage_price"] >= 0)]
    per_symbol = {}
    configured = sorted(
        {str(item).strip().upper() for item in expected_symbols if str(item).strip()}
        if expected_symbols is not None
        else set(valid["source_symbol"].unique())
    )
    for symbol in configured:
        subset = valid[valid["source_symbol"] == symbol]
        if subset.empty:
            per_symbol[symbol] = {
                "fills": 0,
                "minimum_required": int(min_symbol_fills),
                "sample_complete": False,
                "mean_adverse_slippage_price": None,
                "p50_adverse_slippage_price": None,
                "p95_adverse_slippage_price": None,
                "backtest_assumed_slippage_price": None,
                "p95_to_assumption_ratio": None,
                "within_assumption": False,
            }
            continue
        p95 = float(subset["adverse_slippage_price"].quantile(0.95))
        assumed = float(subset["assumed_slippage_price"].max())
        limit = assumed * float(max_p95_assumption_ratio)
        per_symbol[symbol] = {
            "fills": int(len(subset)),
            "minimum_required": int(min_symbol_fills),
            "sample_complete": len(subset) >= int(min_symbol_fills),
            "mean_adverse_slippage_price": round(float(subset["adverse_slippage_price"].mean()), 10),
            "p50_adverse_slippage_price": round(float(subset["adverse_slippage_price"].quantile(0.5)), 10),
            "p95_adverse_slippage_price": round(p95, 10),
            "backtest_assumed_slippage_price": round(assumed, 10),
            "p95_to_assumption_ratio": None if assumed == 0 else round(p95 / assumed, 6),
            "within_assumption": p95 <= limit + 1e-12,
        }
    complete = len(valid) >= int(min_fills) and bool(per_symbol) and all(item["sample_complete"] for item in per_symbol.values())
    return {
        "captured_rows": int(len(frame)),
        "valid_broker_fill_rows": int(len(valid)),
        "minimum_required": int(min_fills),
        "minimum_per_symbol": int(min_symbol_fills),
        "sample_complete": complete,
        "within_assumption": complete and all(item["within_assumption"] for item in per_symbol.values()),
        "max_p95_assumption_ratio": float(max_p95_assumption_ratio),
        "expected_symbols": configured,
        "excluded_request_fallback_rows": fallback_rows,
        "per_symbol": per_symbol,
    }
