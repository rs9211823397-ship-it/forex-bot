import math

import pytest

from backtesting.performance import PerformanceReport
from config.settings import ACCOUNT_BALANCE


def completed_trade(
    profit,
    r_multiple=None,
    equity=None,
    starting_equity=None
):
    trade = {
        "type": "EXIT",
        "profit": profit
    }

    if r_multiple is not None:
        trade["r_multiple"] = r_multiple

    if equity is not None:
        trade["equity"] = equity

    if starting_equity is not None:
        trade["starting_equity"] = starting_equity

    return trade


def test_first_losing_trade_creates_drawdown_from_initial_equity():
    report = PerformanceReport(
        [completed_trade(-10.0, -1.0, 990.0)],
        initial_equity=1000.0
    )

    assert report.max_drawdown() == pytest.approx(10.0)
    assert report.max_drawdown_percent() == pytest.approx(1.0)
    assert report.ending_equity() == pytest.approx(990.0)


def test_default_initial_equity_never_starts_at_zero():
    report = PerformanceReport([])

    assert report.initial_equity == pytest.approx(ACCOUNT_BALANCE)
    assert report.ending_equity() == pytest.approx(ACCOUNT_BALANCE)
    assert report._equity_path() == [pytest.approx(ACCOUNT_BALANCE)]


def test_initial_equity_is_inferred_from_recorded_starting_equity():
    report = PerformanceReport([
        completed_trade(
            -10.0,
            -1.0,
            equity=990.0,
            starting_equity=1000.0
        )
    ])

    assert report.initial_equity == pytest.approx(1000.0)
    assert report.max_drawdown() == pytest.approx(10.0)


def test_initial_equity_is_inferred_from_equity_and_profit():
    report = PerformanceReport([
        completed_trade(-10.0, -1.0, equity=990.0)
    ])

    assert report.initial_equity == pytest.approx(1000.0)
    assert report.max_drawdown() == pytest.approx(10.0)


def test_all_winning_trades_metrics():
    report = PerformanceReport(
        [
            completed_trade(10.0, 1.0),
            completed_trade(20.0, 2.0)
        ],
        initial_equity=1000.0
    )

    assert report.win_rate() == pytest.approx(100.0)
    assert math.isinf(report.profit_factor())
    assert math.isinf(report.payoff_ratio())
    assert report.expectancy() == pytest.approx(15.0)
    assert report.average_r() == pytest.approx(1.5)
    assert report.max_drawdown() == pytest.approx(0.0)
    assert report.ending_equity() == pytest.approx(1030.0)


def test_all_losing_trades_metrics():
    report = PerformanceReport(
        [
            completed_trade(-10.0, -1.0),
            completed_trade(-20.0, -2.0)
        ],
        initial_equity=1000.0
    )

    assert report.win_rate() == pytest.approx(0.0)
    assert report.profit_factor() == pytest.approx(0.0)
    assert report.payoff_ratio() == pytest.approx(0.0)
    assert report.expectancy() == pytest.approx(-15.0)
    assert report.average_r() == pytest.approx(-1.5)
    assert report.max_drawdown() == pytest.approx(30.0)
    assert report.max_drawdown_percent() == pytest.approx(3.0)
    assert report.ending_equity() == pytest.approx(970.0)


def test_expectancy_average_r_and_payoff_ratio():
    report = PerformanceReport(
        [
            completed_trade(20.0, 2.0),
            completed_trade(-10.0, -1.0),
            completed_trade(10.0, 1.0)
        ],
        initial_equity=1000.0
    )

    assert report.expectancy() == pytest.approx(20.0 / 3.0)
    assert report.average_r() == pytest.approx(2.0 / 3.0)
    assert report.payoff_ratio() == pytest.approx(1.5)
    assert report.profit_factor() == pytest.approx(3.0)


def test_zero_trade_report_is_defined():
    report = PerformanceReport([], initial_equity=1000.0)
    summary = report.summary()

    assert summary["Completed Trades"] == 0
    assert summary["Win Rate %"] == 0
    assert summary["Net Profit"] == 0
    assert summary["Profit Factor"] == 0
    assert summary["Expectancy"] == 0
    assert summary["Average R"] == 0
    assert summary["Max Drawdown"] == 0
    assert summary["Ending Equity"] == pytest.approx(1000.0)
    assert summary["Open Trades"] == 0


def test_open_final_trade_is_not_counted_as_completed():
    trades = [{
        "type": "ENTRY",
        "side": "BUY",
        "price": 100.0,
        "time": 1
    }]
    report = PerformanceReport(
        trades,
        initial_equity=1000.0
    )

    assert report.total_trades() == 0
    assert report.open_trades() == 1
    assert report.total_profit() == 0
    assert report.expectancy() == 0
    assert report.average_r() == 0


def test_marked_equity_curve_includes_open_position_drawdown():
    report = PerformanceReport(
        [{
            "type": "ENTRY",
            "side": "BUY",
            "price": 100.0,
            "time": 1
        }],
        initial_equity=1000.0,
        equity_curve=[1000.0, 1005.0, 980.0]
    )

    assert report.ending_equity() == pytest.approx(980.0)
    assert report.equity_curve() == [
        pytest.approx(1005.0),
        pytest.approx(980.0)
    ]
    assert report.max_drawdown() == pytest.approx(25.0)
    assert report.max_drawdown_percent() == pytest.approx(
        25.0 / 1005.0 * 100.0
    )
    assert report.open_trades() == 1
    assert report.total_trades() == 0


def test_provided_equity_curve_must_start_at_initial_equity():
    with pytest.raises(ValueError, match="begin at initial_equity"):
        PerformanceReport(
            [],
            initial_equity=1000.0,
            equity_curve=[999.0, 1001.0]
        )


@pytest.mark.parametrize(
    "invalid_equity",
    [0.0, -1.0, float("nan"), float("inf")]
)
def test_invalid_initial_equity_is_rejected(invalid_equity):
    with pytest.raises(ValueError, match="initial_equity"):
        PerformanceReport([], initial_equity=invalid_equity)
