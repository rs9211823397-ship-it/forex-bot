import pandas as pd
import pytest

from validation.workflow import (
    ValidationError,
    chronological_holdout_report,
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
    report = forward_test_report(
        deals,
        min_closed_trades=3,
        starting_equity=100.0,
    )
    assert report["closed_trades"] == 2
    assert report["sample_complete"] is False
    assert report["profit_factor"] == 2.0
    assert report["expectancy"] == 0.5
    assert report["max_drawdown_percent"] == pytest.approx(0.9804)
    assert report["ending_equity"] == 101.0
    assert report["per_symbol"]["EURUSD"]["closed_trades"] == 2
    assert report["calendar_eta"]["rate_basis"] == "observed_closed_aaqts_deals"


def test_chronological_holdout_uses_only_tail_exits_and_prior_equity():
    data = pd.DataFrame(
        {
            "close_time": pd.date_range(
                "2026-01-01T00:00:00Z",
                periods=10,
                freq="h",
            )
        }
    )
    trades = [
        {
            "type": "EXIT",
            "exit_time": "2026-01-01T03:00:00Z",
            "profit": 10.0,
            "equity": 110.0,
            "r_multiple": 1.0,
        },
        {
            "type": "EXIT",
            "exit_time": "2026-01-01T08:00:00Z",
            "profit": -5.0,
            "equity": 105.0,
            "r_multiple": -0.5,
        },
    ]

    report = chronological_holdout_report(
        trades,
        data,
        initial_equity=100.0,
    )

    assert report["split"]["training_rows"] == 7
    assert report["split"]["out_of_sample_starting_equity"] == 110.0
    assert report["out_of_sample"]["Completed Trades"] == 1
    assert report["out_of_sample"]["Net Profit"] == -5.0
    assert report["out_of_sample"]["Max Drawdown %"] == pytest.approx(4.5455)


def test_forward_report_without_starting_equity_cannot_claim_drawdown_percent():
    deals = pd.DataFrame({
        "timestamp": ["2026-01-01T00:00:00Z"],
        "symbol": ["EURUSD"],
        "profit": [-2.0],
    })

    report = forward_test_report(deals)

    assert report["max_drawdown_percent"] is None
    assert report["starting_equity"] is None


def test_promotion_is_fail_closed_and_never_auto_enables_live():
    report = promotion_report(
        backtest_metrics={
            "full": {
                "Completed Trades": 120,
                "Profit Factor": 1.4,
                "Expectancy": 0.2,
                "Max Drawdown %": 8.0,
            },
            "out_of_sample": {
                "Completed Trades": 30,
                "Profit Factor": 1.3,
                "Expectancy": 0.1,
                "Max Drawdown %": 9.0,
            },
        },
        parity_metrics={
            "actionable_agreement_percent": 100,
            "missing_in_tradingview": 0,
            "missing_in_aaqts": 0,
        },
        forward_metrics={
            "sample_complete": True,
            "per_symbol_sample_complete": True,
            "expectancy": 0.1,
            "profit_factor": 1.25,
            "max_drawdown_percent": 7.0,
            "per_symbol": {
                "EURUSD": {
                    "sample_complete": True,
                    "profit_factor": 1.25,
                    "expectancy": 0.1,
                    "max_drawdown_percent": 7.0,
                }
            },
        },
        context_parity_metrics={"passed": True, "sample_complete": True},
        slippage_metrics={"sample_complete": True, "within_assumption": True},
        restart_metrics={"passed": True},
    )
    assert report["eligible_for_human_review"] is True
    assert report["automatic_live_enable"] is False
    assert report["thresholds"]["minimum_profit_factor"] == 1.2
    assert report["thresholds"]["maximum_drawdown_percent"] == 10.0


def test_promotion_fails_closed_without_oos_or_percent_drawdown_evidence():
    report = promotion_report(
        backtest_metrics={
            "Completed Trades": 120,
            "Profit Factor": 2.0,
            "Expectancy": 1.0,
        },
        parity_metrics={
            "actionable_agreement_percent": 100,
            "missing_in_tradingview": 0,
            "missing_in_aaqts": 0,
        },
        forward_metrics={
            "sample_complete": True,
            "expectancy": 1.0,
            "profit_factor": 2.0,
        },
    )

    assert report["eligible_for_human_review"] is False
    assert report["checks"]["backtest_drawdown"] is False
    assert report["checks"]["out_of_sample_sample"] is False
    assert report["checks"]["forward_drawdown"] is False


def test_promotion_rejects_weak_symbol_hidden_by_aggregate_profit():
    report = promotion_report(
        backtest_metrics={
            "full": {"Completed Trades": 100, "Profit Factor": 2, "Expectancy": 1, "Max Drawdown %": 5},
            "out_of_sample": {"Completed Trades": 20, "Profit Factor": 2, "Expectancy": 1, "Max Drawdown %": 5},
        },
        parity_metrics={"actionable_agreement_percent": 100, "missing_in_tradingview": 0, "missing_in_aaqts": 0},
        context_parity_metrics={"passed": True, "sample_complete": True},
        forward_metrics={
            "sample_complete": True,
            "per_symbol_sample_complete": True,
            "expectancy": 1,
            "profit_factor": 2,
            "max_drawdown_percent": 5,
            "per_symbol": {
                "GOOD": {"sample_complete": True, "profit_factor": 2, "expectancy": 1, "max_drawdown_percent": 5},
                "WEAK": {"sample_complete": True, "profit_factor": 0.8, "expectancy": -1, "max_drawdown_percent": 5},
            },
        },
        slippage_metrics={"sample_complete": True, "within_assumption": True},
        restart_metrics={"passed": True},
    )
    assert report["eligible_for_human_review"] is False
    assert report["checks"]["forward_per_symbol_quality"] is False
