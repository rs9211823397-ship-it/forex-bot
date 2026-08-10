import pandas as pd
import pytest

from validation.workflow import (
    ValidationError,
    compare_signal_ledgers,
    forward_test_report,
    promotion_report,
    write_signal_ledger,
)


def ledger(signals):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=len(signals), freq="15min", tz="UTC"),
        "symbol": ["EURUSD"] * len(signals),
        "signal": signals,
    })


def test_signal_parity_reports_actionable_mismatch_and_coverage():
    report = compare_signal_ledgers(
        ledger(["HOLD", "BUY", "SELL"]),
        ledger(["HOLD", "BUY", "HOLD"]),
    )
    assert report["agreement_percent"] == pytest.approx(66.6667)
    assert report["actionable_rows"] == 2
    assert report["actionable_agreement_percent"] == 50.0
    assert report["mismatched_rows"] == 1


def test_signal_parity_rejects_duplicates():
    duplicate = pd.concat([ledger(["BUY"]), ledger(["BUY"])], ignore_index=True)
    with pytest.raises(ValidationError, match="duplicate"):
        compare_signal_ledgers(duplicate, ledger(["BUY"]))


def test_signal_ledger_writer_is_round_trip_stable(tmp_path):
    path = write_signal_ledger(
        ledger(["HOLD", "BUY"]).to_dict("records"),
        tmp_path / "signals.csv",
    )
    report = compare_signal_ledgers(path, path)
    assert report["agreement_percent"] == 100.0
    assert report["missing_in_tradingview"] == 0


def test_forward_report_requires_real_sample_before_completion():
    deals = pd.DataFrame({
        "timestamp": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
        "symbol": ["EURUSD", "EURUSD"],
        "profit": [2.0, -1.0],
    })
    report = forward_test_report(deals, min_closed_trades=3)
    assert report["closed_trades"] == 2
    assert report["sample_complete"] is False
    assert report["profit_factor"] == 2.0
    assert report["expectancy"] == 0.5


def test_promotion_is_fail_closed_and_never_auto_enables_live():
    report = promotion_report(
        backtest_metrics={
            "Completed Trades": 120,
            "Profit Factor": 1.4,
            "Expectancy": 0.2,
        },
        parity_metrics={
            "actionable_agreement_percent": 100,
            "missing_in_tradingview": 0,
            "missing_in_aaqts": 0,
        },
        forward_metrics={"sample_complete": True, "expectancy": 0.1},
    )
    assert report["eligible_for_human_review"] is True
    assert report["automatic_live_enable"] is False
