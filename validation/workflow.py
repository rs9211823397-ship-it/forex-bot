"""Deterministic backtest, TradingView parity, and forward-test evidence.

This module never enables live execution.  It only produces reproducible
artifacts that a human can review before changing an execution mode.
"""

from __future__ import annotations

from math import inf, isfinite
from pathlib import Path

import pandas as pd


class ValidationError(ValueError):
    """Raised when validation evidence is incomplete or malformed."""


LEDGER_COLUMNS = ("timestamp", "symbol", "signal")
VALID_SIGNALS = {"BUY", "SELL", "HOLD"}


def write_signal_ledger(records, output) -> Path:
    """Validate and atomically write AAQTS close-confirmed decisions."""

    frame = _ledger(pd.DataFrame(list(records)), "AAQTS")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    temporary.replace(path)
    return path


def _frame(value) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return pd.read_csv(Path(value))


def _ledger(value, label) -> pd.DataFrame:
    frame = _frame(value)
    missing = set(LEDGER_COLUMNS).difference(frame.columns)
    if missing:
        raise ValidationError(
            f"{label} ledger missing columns: {', '.join(sorted(missing))}"
        )
    frame = frame.loc[:, LEDGER_COLUMNS].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if frame["timestamp"].isna().any():
        raise ValidationError(f"{label} ledger contains invalid timestamps")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["signal"] = frame["signal"].astype(str).str.strip().str.upper()
    invalid = sorted(set(frame["signal"]).difference(VALID_SIGNALS))
    if invalid:
        raise ValidationError(f"{label} ledger contains invalid signals: {invalid}")
    if frame.duplicated(["timestamp", "symbol"]).any():
        raise ValidationError(f"{label} ledger has duplicate timestamp/symbol rows")
    return frame.sort_values(["timestamp", "symbol"], kind="stable").reset_index(drop=True)


def compare_signal_ledgers(aaqts, tradingview) -> dict:
    """Compare close-confirmed AAQTS and TradingView signal ledgers exactly."""

    left = _ledger(aaqts, "AAQTS").rename(columns={"signal": "aaqts_signal"})
    right = _ledger(tradingview, "TradingView").rename(
        columns={"signal": "tradingview_signal"}
    )
    merged = left.merge(right, on=["timestamp", "symbol"], how="outer", indicator=True)
    common = merged[merged["_merge"] == "both"].copy()
    common["matched"] = common["aaqts_signal"] == common["tradingview_signal"]
    actionable = common[
        (common["aaqts_signal"] != "HOLD")
        | (common["tradingview_signal"] != "HOLD")
    ]
    matches = int(common["matched"].sum())
    actionable_matches = int(actionable["matched"].sum()) if len(actionable) else 0
    mismatches = common[~common["matched"]]
    return {
        "aaqts_rows": int(len(left)),
        "tradingview_rows": int(len(right)),
        "common_rows": int(len(common)),
        "matched_rows": matches,
        "mismatched_rows": int(len(mismatches)),
        "missing_in_tradingview": int((merged["_merge"] == "left_only").sum()),
        "missing_in_aaqts": int((merged["_merge"] == "right_only").sum()),
        "agreement_percent": round(matches / len(common) * 100.0, 4) if len(common) else 0.0,
        "actionable_rows": int(len(actionable)),
        "actionable_agreement_percent": (
            round(actionable_matches / len(actionable) * 100.0, 4)
            if len(actionable)
            else 0.0
        ),
        "mismatches": mismatches.drop(columns=["_merge", "matched"]).assign(
            timestamp=lambda item: item["timestamp"].astype(str)
        ).to_dict("records"),
    }


def _max_drawdown(profits) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for profit in profits:
        equity += float(profit)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def forward_test_report(deals, *, min_closed_trades=100) -> dict:
    """Summarize closed AAQTS broker deals exported from MT5."""

    frame = _frame(deals)
    required = {"timestamp", "symbol", "profit"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValidationError(
            "Forward ledger missing columns: " + ", ".join(sorted(missing))
        )
    if isinstance(min_closed_trades, bool) or int(min_closed_trades) < 1:
        raise ValidationError("min_closed_trades must be a positive integer")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["profit"] = pd.to_numeric(frame["profit"], errors="coerce")
    if frame[["timestamp", "profit"]].isna().any().any():
        raise ValidationError("Forward ledger contains invalid timestamp/profit values")
    if not all(isfinite(float(value)) for value in frame["profit"]):
        raise ValidationError("Forward ledger profits must be finite")
    frame = frame.sort_values("timestamp", kind="stable")
    wins = frame[frame["profit"] > 0]
    losses = frame[frame["profit"] < 0]
    gross_profit = float(wins["profit"].sum())
    gross_loss = abs(float(losses["profit"].sum()))
    profit_factor = inf if gross_loss == 0 and gross_profit > 0 else (
        gross_profit / gross_loss if gross_loss else 0.0
    )
    total = len(frame)
    return {
        "closed_trades": int(total),
        "minimum_required": int(min_closed_trades),
        "sample_complete": bool(total >= int(min_closed_trades)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_percent": round(len(wins) / total * 100.0, 4) if total else 0.0,
        "net_profit": round(float(frame["profit"].sum()), 4),
        "profit_factor": "Infinity" if profit_factor == inf else round(profit_factor, 4),
        "expectancy": round(float(frame["profit"].mean()), 4) if total else 0.0,
        "max_drawdown": round(_max_drawdown(frame["profit"]), 4),
        "first_deal_utc": None if not total else frame.iloc[0]["timestamp"].isoformat(),
        "last_deal_utc": None if not total else frame.iloc[-1]["timestamp"].isoformat(),
    }


def promotion_report(
    *,
    backtest_metrics,
    parity_metrics,
    forward_metrics,
    min_backtest_trades=100,
    min_profit_factor=1.1,
    min_parity_percent=99.0,
) -> dict:
    """Create a fail-closed, human-reviewed promotion recommendation."""

    profit_factor = backtest_metrics.get("Profit Factor", 0)
    if profit_factor == "Infinity":
        profit_factor = inf
    checks = {
        "backtest_sample": int(backtest_metrics.get("Completed Trades", 0))
        >= int(min_backtest_trades),
        "backtest_profit_factor": float(profit_factor) >= float(min_profit_factor),
        "backtest_expectancy": float(backtest_metrics.get("Expectancy", 0)) > 0,
        "tradingview_parity": float(parity_metrics.get("actionable_agreement_percent", 0))
        >= float(min_parity_percent),
        "tradingview_coverage": (
            int(parity_metrics.get("missing_in_tradingview", 0)) == 0
            and int(parity_metrics.get("missing_in_aaqts", 0)) == 0
        ),
        "forward_sample": bool(forward_metrics.get("sample_complete", False)),
        "forward_expectancy": float(forward_metrics.get("expectancy", 0)) > 0,
    }
    return {
        "checks": checks,
        "eligible_for_human_review": all(checks.values()),
        "automatic_live_enable": False,
    }
