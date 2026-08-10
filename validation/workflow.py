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


def chronological_holdout_report(
    trades,
    data,
    *,
    initial_equity,
    training_fraction=0.70,
) -> dict:
    """Return a deterministic chronological holdout performance report."""

    if not 0.0 < float(training_fraction) < 1.0:
        raise ValidationError("training_fraction must be between zero and one")
    frame = _frame(data)
    if len(frame) < 2:
        raise ValidationError("holdout reporting requires at least two candles")
    if "close_time" in frame.columns:
        close_times = pd.to_datetime(frame["close_time"], utc=True, errors="coerce")
    elif isinstance(frame.index, pd.DatetimeIndex):
        close_times = pd.Series(pd.to_datetime(frame.index, utc=True), index=frame.index)
    else:
        raise ValidationError("holdout data requires close_time or a DatetimeIndex")
    if close_times.isna().any() or not close_times.is_monotonic_increasing:
        raise ValidationError("holdout close times must be valid and monotonic")

    split_position = max(
        1,
        min(len(frame) - 1, int(len(frame) * float(training_fraction))),
    )
    split_time = pd.Timestamp(close_times.iloc[split_position])
    completed = [trade for trade in trades if trade.get("type") == "EXIT"]
    try:
        timed = [
            (trade, pd.to_datetime(trade["exit_time"], utc=True, errors="raise"))
            for trade in completed
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("completed trades require valid exit_time values") from exc
    pre_split = [trade for trade, exit_time in timed if exit_time < split_time]
    out_of_sample = [trade for trade, exit_time in timed if exit_time >= split_time]
    holdout_starting_equity = float(initial_equity) + sum(
        float(trade["profit"]) for trade in pre_split
    )

    from backtesting.performance import PerformanceReport

    return {
        "out_of_sample": PerformanceReport(
            out_of_sample,
            initial_equity=holdout_starting_equity,
        ).summary(),
        "split": {
            "method": "chronological_70_30_holdout",
            "split_close_time_utc": split_time.isoformat(),
            "training_rows": split_position,
            "out_of_sample_rows": len(frame) - split_position,
            "out_of_sample_starting_equity": round(
                holdout_starting_equity,
                4,
            ),
        },
    }


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


def _max_drawdown_percent(profits, starting_equity) -> float | None:
    if starting_equity is None:
        return None
    starting_equity = float(starting_equity)
    if not isfinite(starting_equity) or starting_equity <= 0:
        raise ValidationError("starting_equity must be finite and greater than zero")
    equity = starting_equity
    peak = starting_equity
    maximum_percent = 0.0
    for profit in profits:
        equity += float(profit)
        peak = max(peak, equity)
        if peak > 0:
            maximum_percent = max(
                maximum_percent,
                (peak - equity) / peak * 100.0,
            )
    return maximum_percent


def _performance(frame: pd.DataFrame, starting_equity=None) -> dict:
    wins = frame[frame["profit"] > 0]
    losses = frame[frame["profit"] < 0]
    gross_profit = float(wins["profit"].sum())
    gross_loss = abs(float(losses["profit"].sum()))
    factor = inf if gross_loss == 0 and gross_profit > 0 else (
        gross_profit / gross_loss if gross_loss else 0.0
    )
    drawdown_percent = _max_drawdown_percent(frame["profit"], starting_equity)
    total = len(frame)
    return {
        "closed_trades": int(total),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_percent": round(len(wins) / total * 100.0, 4) if total else 0.0,
        "net_profit": round(float(frame["profit"].sum()), 4),
        "profit_factor": "Infinity" if factor == inf else round(factor, 4),
        "expectancy": round(float(frame["profit"].mean()), 4) if total else 0.0,
        "max_drawdown": round(_max_drawdown(frame["profit"]), 4),
        "max_drawdown_percent": None if drawdown_percent is None else round(drawdown_percent, 4),
        "first_deal_utc": None if not total else frame.iloc[0]["timestamp"].isoformat(),
        "last_deal_utc": None if not total else frame.iloc[-1]["timestamp"].isoformat(),
    }


def _calendar_eta(frame, minimum, as_of) -> dict:
    instant = pd.Timestamp.now(tz="UTC") if as_of is None else pd.to_datetime(as_of, utc=True, errors="coerce")
    if pd.isna(instant):
        raise ValidationError("as_of must be a valid timestamp")
    remaining = max(0, int(minimum) - len(frame))
    rates = {}
    for days in (7, 30):
        count = int(((frame["timestamp"] > instant - pd.Timedelta(days=days)) & (frame["timestamp"] <= instant)).sum())
        rates[f"closed_trades_{days}d"] = count
        rates[f"trades_per_day_{days}d"] = round(count / days, 6)
    chosen = rates["trades_per_day_30d"] or rates["trades_per_day_7d"]
    days_remaining = 0.0 if remaining == 0 else (remaining / chosen if chosen > 0 else None)
    completion = None if days_remaining is None else instant + pd.Timedelta(days=days_remaining)
    return {
        **rates,
        "remaining_trades": remaining,
        "rate_basis": "observed_closed_aaqts_deals",
        "estimated_days_remaining": None if days_remaining is None else round(days_remaining, 2),
        "estimated_completion_utc": None if completion is None else completion.isoformat(),
        "note": "Backtest and parity run historically/in parallel; only the demo-forward stage waits on calendar time.",
    }


def forward_test_report(
    deals,
    *,
    min_closed_trades=100,
    starting_equity=None,
    expected_symbols=None,
    min_symbol_trades=10,
    as_of=None,
) -> dict:
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
    if isinstance(min_symbol_trades, bool) or int(min_symbol_trades) < 1:
        raise ValidationError("min_symbol_trades must be a positive integer")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["profit"] = pd.to_numeric(frame["profit"], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    if frame[["timestamp", "profit"]].isna().any().any():
        raise ValidationError("Forward ledger contains invalid timestamp/profit values")
    if not all(isfinite(float(value)) for value in frame["profit"]):
        raise ValidationError("Forward ledger profits must be finite")
    frame = frame.sort_values("timestamp", kind="stable")
    total = len(frame)
    overall = _performance(frame, starting_equity)
    configured = (
        sorted({str(symbol).strip().upper() for symbol in expected_symbols if str(symbol).strip()})
        if expected_symbols is not None
        else sorted(frame["symbol"].unique().tolist())
    )
    per_symbol = {}
    for symbol in configured:
        subset = frame[frame["symbol"] == symbol].reset_index(drop=True)
        metrics = _performance(subset, starting_equity)
        metrics["minimum_required"] = int(min_symbol_trades)
        metrics["sample_complete"] = len(subset) >= int(min_symbol_trades)
        per_symbol[symbol] = metrics
    return {
        **overall,
        "minimum_required": int(min_closed_trades),
        "sample_complete": bool(total >= int(min_closed_trades)),
        "per_symbol_minimum_required": int(min_symbol_trades),
        "per_symbol_sample_complete": bool(configured) and all(item["sample_complete"] for item in per_symbol.values()),
        "expected_symbols": configured,
        "per_symbol": per_symbol,
        "calendar_eta": _calendar_eta(frame, int(min_closed_trades), as_of),
        "starting_equity": (
            None if starting_equity is None else round(float(starting_equity), 4)
        ),
        "ending_equity": (
            None
            if starting_equity is None
            else round(float(starting_equity) + float(frame["profit"].sum()), 4)
        ),
    }


def promotion_report(
    *,
    backtest_metrics,
    parity_metrics,
    forward_metrics,
    context_parity_metrics=None,
    slippage_metrics=None,
    restart_metrics=None,
    min_backtest_trades=100,
    min_out_of_sample_trades=20,
    min_profit_factor=1.2,
    max_drawdown_percent=10.0,
    min_parity_percent=99.0,
) -> dict:
    """Create a fail-closed, human-reviewed promotion recommendation."""

    if int(min_backtest_trades) < 1 or int(min_out_of_sample_trades) < 1:
        raise ValidationError("promotion trade minimums must be positive")
    if not isfinite(float(min_profit_factor)) or float(min_profit_factor) <= 0:
        raise ValidationError("minimum profit factor must be positive and finite")
    if not 0 <= float(max_drawdown_percent) <= 100:
        raise ValidationError("maximum drawdown percent must be between 0 and 100")
    if not 0 <= float(min_parity_percent) <= 100:
        raise ValidationError("minimum parity percent must be between 0 and 100")

    full_backtest = backtest_metrics.get("full", backtest_metrics)
    out_of_sample = backtest_metrics.get("out_of_sample", {})

    def number(value, fallback=0.0):
        if value == "Infinity":
            return inf
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return float(fallback)
        return parsed if isfinite(parsed) else parsed

    backtest_profit_factor = number(full_backtest.get("Profit Factor", 0))
    oos_profit_factor = number(out_of_sample.get("Profit Factor", 0))
    forward_profit_factor = number(forward_metrics.get("profit_factor", 0))
    backtest_drawdown = number(
        full_backtest.get("Max Drawdown %"),
        fallback=inf,
    )
    oos_drawdown = number(
        out_of_sample.get("Max Drawdown %"),
        fallback=inf,
    )
    forward_drawdown = number(
        forward_metrics.get("max_drawdown_percent"),
        fallback=inf,
    )
    symbol_metrics = forward_metrics.get("per_symbol", {})
    symbol_quality = bool(symbol_metrics) and all(
        bool(item.get("sample_complete", False))
        and number(item.get("profit_factor", 0)) >= float(min_profit_factor)
        and number(item.get("expectancy", 0)) > 0
        and number(item.get("max_drawdown_percent"), fallback=inf) <= float(max_drawdown_percent)
        for item in symbol_metrics.values()
    )
    checks = {
        "backtest_sample": int(full_backtest.get("Completed Trades", 0))
        >= int(min_backtest_trades),
        "backtest_profit_factor": backtest_profit_factor
        >= float(min_profit_factor),
        "backtest_expectancy": number(full_backtest.get("Expectancy", 0)) > 0,
        "backtest_drawdown": backtest_drawdown <= float(max_drawdown_percent),
        "out_of_sample_sample": int(out_of_sample.get("Completed Trades", 0))
        >= int(min_out_of_sample_trades),
        "out_of_sample_profit_factor": oos_profit_factor
        >= float(min_profit_factor),
        "out_of_sample_expectancy": number(out_of_sample.get("Expectancy", 0)) > 0,
        "out_of_sample_drawdown": oos_drawdown <= float(max_drawdown_percent),
        "tradingview_parity": number(
            parity_metrics.get("actionable_agreement_percent", 0)
        )
        >= float(min_parity_percent),
        "tradingview_coverage": (
            int(parity_metrics.get("missing_in_tradingview", 0)) == 0
            and int(parity_metrics.get("missing_in_aaqts", 0)) == 0
        ),
        "context_structure_parity": bool(
            context_parity_metrics
            and context_parity_metrics.get("passed", False)
            and context_parity_metrics.get("sample_complete", False)
        ),
        "forward_sample": bool(forward_metrics.get("sample_complete", False)),
        "forward_per_symbol_sample": bool(
            forward_metrics.get("per_symbol_sample_complete", False)
        ),
        "forward_per_symbol_quality": symbol_quality,
        "forward_expectancy": number(forward_metrics.get("expectancy", 0)) > 0,
        "forward_profit_factor": forward_profit_factor >= float(min_profit_factor),
        "forward_drawdown": forward_drawdown <= float(max_drawdown_percent),
        "slippage_calibration": bool(
            slippage_metrics
            and slippage_metrics.get("sample_complete", False)
            and slippage_metrics.get("within_assumption", False)
        ),
        "restart_soak": bool(restart_metrics and restart_metrics.get("passed", False)),
    }
    return {
        "checks": checks,
        "thresholds": {
            "minimum_backtest_trades": int(min_backtest_trades),
            "minimum_out_of_sample_trades": int(min_out_of_sample_trades),
            "minimum_profit_factor": float(min_profit_factor),
            "maximum_drawdown_percent": float(max_drawdown_percent),
            "minimum_parity_percent": float(min_parity_percent),
        },
        "eligible_for_human_review": all(checks.values()),
        "automatic_live_enable": False,
    }
