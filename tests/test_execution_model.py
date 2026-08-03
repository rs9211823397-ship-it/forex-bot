import math
from decimal import Decimal

import pandas as pd
import pytest

from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from risk.instrument import InstrumentSpec
from risk.risk_manager import RiskManager


def market_frame(rows):
    return pd.DataFrame(
        rows,
        index=pd.date_range(
            "2024-02-01T00:00:00Z",
            periods=len(rows),
            freq="h"
        )
    )


def candle(
    open_price=100.0,
    high=101.0,
    low=99.0,
    close=100.0,
    atr=1.0,
    adx=35.0
):
    return {
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "ATR": atr,
        "ADX": adx
    }


def instrument(**overrides):
    values = {
        "symbol": "TEST",
        "tick_size": 0.01,
        "contract_multiplier": 1.0,
        "quantity_step": 0.0001,
        "minimum_quantity": 0.0001,
        "spread": 0.0,
        "slippage": 0.0,
        "commission_per_quantity": 0.0
    }
    values.update(overrides)
    return InstrumentSpec(**values)


def run_two_bar_trade(side, high, low, spec=None):
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=high, low=low)
    ])
    engine = BacktestEngine(
        data,
        lambda index: side if index == 0 else "HOLD",
        instrument=spec or instrument()
    )
    trades = engine.run()
    exit_record = next(
        trade for trade in trades
        if trade["type"] == "EXIT"
    )
    return engine, exit_record


def run_gap_trade(side, gap_open):
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=101.0, low=99.0),
        candle(
            open_price=gap_open,
            high=gap_open + 1.0,
            low=gap_open - 1.0,
            close=gap_open
        )
    ])
    engine = BacktestEngine(
        data,
        lambda index: side if index == 0 else "HOLD",
        instrument=instrument()
    )
    trades = engine.run()
    return next(
        trade for trade in trades
        if trade["type"] == "EXIT"
    )


def test_buy_stop():
    _, trade = run_two_bar_trade("BUY", high=101.0, low=97.0)

    assert trade["result"] == "STOP LOSS"
    assert trade["exit_reason"] == "STOP_LOSS_INTRABAR"
    assert trade["exit_reference_price"] == pytest.approx(98.2)


def test_sell_stop():
    _, trade = run_two_bar_trade("SELL", high=103.0, low=99.0)

    assert trade["result"] == "STOP LOSS"
    assert trade["exit_reason"] == "STOP_LOSS_INTRABAR"
    assert trade["exit_reference_price"] == pytest.approx(101.8)


def test_buy_target():
    _, trade = run_two_bar_trade("BUY", high=104.0, low=99.0)

    assert trade["result"] == "TAKE PROFIT"
    assert trade["exit_reason"] == "TAKE_PROFIT_INTRABAR"
    assert trade["exit_reference_price"] == pytest.approx(103.0)


def test_sell_target():
    _, trade = run_two_bar_trade("SELL", high=101.0, low=96.0)

    assert trade["result"] == "TAKE PROFIT"
    assert trade["exit_reason"] == "TAKE_PROFIT_INTRABAR"
    assert trade["exit_reference_price"] == pytest.approx(97.0)


def test_buy_gap_stop():
    trade = run_gap_trade("BUY", gap_open=95.0)

    assert trade["result"] == "STOP LOSS"
    assert trade["exit_reason"] == "STOP_LOSS_GAP"
    assert trade["exit_reference_price"] == 95.0


def test_sell_gap_stop():
    trade = run_gap_trade("SELL", gap_open=105.0)

    assert trade["result"] == "STOP LOSS"
    assert trade["exit_reason"] == "STOP_LOSS_GAP"
    assert trade["exit_reference_price"] == 105.0


def test_buy_same_candle_ambiguity_is_conservative():
    _, trade = run_two_bar_trade("BUY", high=104.0, low=97.0)

    assert trade["result"] == "STOP LOSS"
    assert (
        trade["exit_reason"]
        == "SAME_BAR_STOP_FIRST_CONSERVATIVE"
    )


def test_sell_same_candle_ambiguity_is_conservative():
    _, trade = run_two_bar_trade("SELL", high=103.0, low=96.0)

    assert trade["result"] == "STOP LOSS"
    assert (
        trade["exit_reason"]
        == "SAME_BAR_STOP_FIRST_CONSERVATIVE"
    )


def test_spread_slippage_commission_and_actual_fill_pnl():
    spec = instrument(
        contract_multiplier=10.0,
        quantity_step=0.01,
        minimum_quantity=0.01,
        spread=0.2,
        slippage=0.1,
        commission_per_quantity=2.0
    )
    _, trade = run_two_bar_trade(
        "BUY",
        high=104.0,
        low=99.0,
        spec=spec
    )
    expected_gross = (
        trade["exit_price"] - trade["entry_price"]
    ) * trade["quantity"] * spec.contract_multiplier
    expected_net = expected_gross - trade["commission"]

    assert trade["entry_price"] == pytest.approx(100.2)
    assert trade["exit_price"] == pytest.approx(102.8)
    assert trade["gross_profit"] == pytest.approx(expected_gross)
    assert trade["profit"] == pytest.approx(expected_net)
    assert trade["total_cost"] == pytest.approx(
        trade["reference_profit"] - trade["profit"]
    )
    assert trade["spread_cost"] > 0
    assert trade["slippage_cost"] > 0
    assert trade["commission"] > 0


@pytest.mark.parametrize(
    "side, high, low",
    [
        ("BUY", 101.0, 97.0),
        ("SELL", 103.0, 99.0)
    ]
)
def test_cost_inclusive_normal_stop_does_not_exceed_requested_risk(
    side,
    high,
    low
):
    spec = instrument(
        contract_multiplier=10.0,
        quantity_step=0.01,
        minimum_quantity=0.01,
        spread=0.2,
        slippage=0.1,
        commission_per_quantity=2.0
    )
    engine, trade = run_two_bar_trade(
        side,
        high=high,
        low=low,
        spec=spec
    )
    requested_risk = engine.initial_equity * 0.01

    assert abs(trade["profit"]) <= requested_risk
    assert trade["initial_risk"] <= requested_risk
    assert trade["risk_percent"] <= 1.0
    assert abs(trade["profit"]) == pytest.approx(
        trade["initial_risk"]
    )


def test_trade_records_preserve_legacy_dictionary_fields():
    engine, exit_trade = run_two_bar_trade(
        "BUY",
        high=104.0,
        low=99.0
    )
    entry_trade = next(
        trade for trade in engine.trades
        if trade["type"] == "ENTRY"
    )

    assert {
        "type",
        "side",
        "price",
        "stop_loss",
        "take_profit",
        "time"
    }.issubset(entry_trade)
    assert {
        "type",
        "side",
        "entry_price",
        "exit_price",
        "profit",
        "result",
        "entry_time",
        "exit_time"
    }.issubset(exit_trade)


def test_tick_rounding_is_included_in_fills_and_profit():
    spec = instrument(
        tick_size=0.5,
        contract_multiplier=1.0,
        quantity_step=0.1,
        minimum_quantity=0.1,
        spread=0.1,
        slippage=0.05
    )
    _, trade = run_two_bar_trade(
        "BUY",
        high=104.0,
        low=99.0,
        spec=spec
    )
    expected = (
        trade["exit_price"] - trade["entry_price"]
    ) * trade["quantity"]

    assert trade["entry_price"] % spec.tick_size == pytest.approx(0)
    assert trade["exit_price"] % spec.tick_size == pytest.approx(0)
    assert trade["profit"] == pytest.approx(expected)
    assert trade["tick_rounding_cost"] >= 0


def test_minimum_quantity_rejects_too_small_position():
    spec = instrument(
        contract_multiplier=1000.0,
        quantity_step=1.0,
        minimum_quantity=1.0
    )
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=101.0, low=99.0)
    ])
    engine = BacktestEngine(
        data,
        lambda index: "BUY" if index == 0 else "HOLD",
        instrument=spec
    )

    assert engine.run() == []
    assert engine.orders[0]["status"] == "REJECTED_ZERO_QUANTITY"


def test_maximum_quantity_is_enforced_and_step_aligned():
    spec = instrument(
        quantity_step=0.1,
        minimum_quantity=0.1,
        maximum_quantity=0.5
    )
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=101.0, low=99.0)
    ])
    engine = BacktestEngine(
        data,
        lambda index: "BUY" if index == 0 else "HOLD",
        instrument=spec
    )
    trades = engine.run()
    entry = next(
        trade for trade in trades
        if trade["type"] == "ENTRY"
    )

    assert entry["quantity"] == 0.5
    assert (
        Decimal(str(entry["quantity"]))
        % Decimal(str(spec.quantity_step))
        == 0
    )


@pytest.mark.parametrize(
    "overrides, error",
    [
        ({"tick_size": 0.0}, "tick_size"),
        ({"quantity_step": 0.0}, "quantity_step"),
        (
            {
                "quantity_step": 0.1,
                "minimum_quantity": 0.15
            },
            "align"
        ),
        (
            {
                "quantity_step": 0.1,
                "minimum_quantity": 0.1,
                "maximum_quantity": 0.55
            },
            "align"
        ),
        (
            {
                "minimum_quantity": 1.0,
                "maximum_quantity": 0.5
            },
            "below"
        )
    ]
)
def test_invalid_instrument_is_rejected(overrides, error):
    with pytest.raises(ValueError, match=error):
        instrument(**overrides)


def test_backtest_rejects_non_instrument_object():
    data = market_frame([candle()])

    with pytest.raises(TypeError, match="InstrumentSpec"):
        BacktestEngine(
            data,
            lambda index: "HOLD",
            instrument=object()
        )


def test_legacy_risk_manager_call_remains_compatible():
    manager = RiskManager(risk_percent=1.0)

    assert manager.position_size(
        1000.0,
        100.0,
        98.0
    ) == 5.0


def test_position_size_uses_point_in_time_equity():
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=104.0, low=99.0, close=103.0),
        candle(high=104.0, low=99.0, close=103.0)
    ])
    signals = ["BUY", "BUY", "HOLD"]
    engine = BacktestEngine(
        data,
        lambda index: signals[index],
        instrument=instrument()
    )
    exits = [
        trade for trade in engine.run()
        if trade["type"] == "EXIT"
    ]

    assert len(exits) == 2
    assert exits[1]["quantity"] > exits[0]["quantity"]
    assert exits[1]["risk_percent"] <= 1.0
    assert math.isclose(
        exits[1]["risk_percent"],
        1.0,
        rel_tol=0.0,
        abs_tol=0.0001
    )


def test_strategy_risk_multiplier_reduces_backtest_position_size():
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=101.0, low=99.0),
    ])
    full = BacktestEngine(
        data,
        lambda index: {"signal": "BUY", "risk_multiplier": 1.0}
        if index == 0
        else "HOLD",
        instrument=instrument(),
    )
    reduced = BacktestEngine(
        data,
        lambda index: {
            "signal": "BUY",
            "risk_multiplier": 0.5,
            "strategy": "RANGE_REVERSION",
            "regime": "RANGE",
        }
        if index == 0
        else "HOLD",
        instrument=instrument(),
    )

    full_entry = next(
        trade for trade in full.run() if trade["type"] == "ENTRY"
    )
    reduced_entry = next(
        trade for trade in reduced.run() if trade["type"] == "ENTRY"
    )

    assert reduced_entry["quantity"] == pytest.approx(
        full_entry["quantity"] * 0.5,
        abs=instrument().quantity_step,
    )
    assert reduced_entry["risk_multiplier"] == 0.5
    assert reduced_entry["strategy"] == "RANGE_REVERSION"
    assert reduced_entry["regime"] == "RANGE"


def test_invalid_strategy_risk_multiplier_fails_closed():
    data = market_frame([candle(), candle()])
    engine = BacktestEngine(
        data,
        lambda index: {"signal": "BUY", "risk_multiplier": 1.5},
        instrument=instrument(),
    )

    with pytest.raises(ValueError, match="between zero and one"):
        engine.run()


def test_open_position_drawdown_is_in_equity_curve():
    data = market_frame([
        candle(high=100.5, low=99.5),
        candle(high=100.5, low=98.5, close=99.0),
        candle(
            open_price=99.0,
            high=99.5,
            low=98.3,
            close=98.5
        )
    ])
    engine = BacktestEngine(
        data,
        lambda index: "BUY" if index == 0 else "HOLD",
        instrument=instrument()
    )
    trades = engine.run()
    report = PerformanceReport(
        trades,
        initial_equity=engine.initial_equity,
        equity_curve=engine.equity_history
    )

    assert report.total_trades() == 0
    assert report.open_trades() == 1
    assert report.ending_equity() < engine.initial_equity
    assert report.max_drawdown() > 0
