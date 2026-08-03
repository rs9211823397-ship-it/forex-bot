import numpy as np
import pandas as pd
import pytest

from backtesting.backtest_engine import BacktestEngine
from risk.instrument import InstrumentSpec


def market_frame(rows, index=None):
    if index is None:
        index = pd.date_range(
            "2024-01-01T00:00:00Z",
            periods=len(rows),
            freq="h"
        )

    return pd.DataFrame(rows, index=index)


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


def zero_cost_instrument():
    return InstrumentSpec(
        symbol="TEST",
        tick_size=0.01,
        contract_multiplier=1.0,
        quantity_step=0.0001,
        minimum_quantity=0.0001
    )


def test_two_argument_constructor_remains_supported():
    engine = BacktestEngine(
        market_frame([candle()]),
        lambda index: "HOLD"
    )

    assert engine.run() == []


def test_signal_fills_at_next_available_open():
    data = market_frame([
        candle(
            open_price=99.0,
            high=101.0,
            low=98.0,
            close=100.0
        ),
        candle(
            open_price=101.0,
            high=102.0,
            low=100.0,
            close=101.5
        ),
        candle(
            open_price=101.5,
            high=102.0,
            low=100.5,
            close=101.0
        )
    ])
    signals = ["BUY", "HOLD", "HOLD"]
    engine = BacktestEngine(
        data,
        lambda index: signals[index],
        instrument=zero_cost_instrument()
    )

    trades = engine.run()
    entry = next(
        trade for trade in trades
        if trade["type"] == "ENTRY"
    )
    order = engine.orders[0]

    assert order["decision_time"] == data.index[0]
    assert order["created_time"] == data.index[0]
    assert order["eligible_fill_time"] == data.index[1]
    assert entry["fill_time"] == data.index[1]
    assert entry["price"] == 101.0
    assert entry["price"] != data.iloc[0]["close"]


def test_explicit_open_and_close_times_define_contract():
    data = pd.DataFrame([
        {
            "open_time": pd.Timestamp("2024-01-01T00:00:00Z"),
            "close_time": pd.Timestamp("2024-01-01T01:00:00Z"),
            **candle(
                open_price=99.0,
                high=101.0,
                low=98.0,
                close=100.0
            )
        },
        {
            "open_time": pd.Timestamp("2024-01-01T01:00:00Z"),
            "close_time": pd.Timestamp("2024-01-01T02:00:00Z"),
            **candle(
                open_price=101.0,
                high=102.0,
                low=100.0,
                close=101.0
            )
        }
    ])
    engine = BacktestEngine(
        data,
        lambda index: "BUY" if index == 0 else "HOLD",
        instrument=zero_cost_instrument()
    )

    trades = engine.run()
    order = engine.orders[0]
    entry = next(
        trade for trade in trades
        if trade["type"] == "ENTRY"
    )

    assert order["decision_time"] == data.iloc[0]["close_time"]
    assert order["created_time"] == data.iloc[0]["close_time"]
    assert (
        order["eligible_fill_time"]
        == data.iloc[1]["open_time"]
    )
    assert entry["fill_time"] == data.iloc[1]["open_time"]


def test_future_price_mutation_cannot_change_past_order():
    original = market_frame([
        candle(close=100.0),
        candle(close=100.5),
        candle(open_price=100.5, close=100.7)
    ])
    mutated = original.copy(deep=True)
    mutated.loc[
        mutated.index[1:],
        ["open", "high", "low", "close", "ATR", "ADX"]
    ] = [
        [10000.0, 20000.0, 1.0, 15000.0, 5000.0, 1.0],
        [20000.0, 30000.0, 2.0, 25000.0, 6000.0, 2.0]
    ]
    signals = ["SELL", "HOLD", "HOLD"]
    original_engine = BacktestEngine(
        original,
        lambda index: signals[index],
        instrument=zero_cost_instrument()
    )
    mutated_engine = BacktestEngine(
        mutated,
        lambda index: signals[index],
        instrument=zero_cost_instrument()
    )

    original_engine.run()
    mutated_engine.run()
    order_fields = (
        "side",
        "decision_time",
        "created_time",
        "eligible_fill_time",
        "decision_price",
        "atr",
        "adx"
    )

    assert {
        field: original_engine.orders[0][field]
        for field in order_fields
    } == {
        field: mutated_engine.orders[0][field]
        for field in order_fields
    }


def test_final_candle_signal_remains_unfilled():
    engine = BacktestEngine(
        market_frame([candle()]),
        lambda index: "BUY",
        instrument=zero_cost_instrument()
    )

    assert engine.run() == []
    assert len(engine.orders) == 1
    assert engine.orders[0]["eligible_fill_time"] is None
    assert (
        engine.orders[0]["status"]
        == "UNFILLED_NO_NEXT_CANDLE"
    )


def test_empty_dataset_is_safe():
    data = pd.DataFrame(columns=[
        "open", "high", "low", "close", "ATR", "ADX"
    ])
    engine = BacktestEngine(data, lambda index: "HOLD")

    assert engine.run() == []
    assert engine.equity_history == [1000.0]


def test_nan_values_are_rejected():
    data = market_frame([candle()])
    data.loc[data.index[0], "close"] = np.nan
    engine = BacktestEngine(data, lambda index: "HOLD")

    with pytest.raises(ValueError, match="finite"):
        engine.run()


def test_duplicate_timestamps_are_rejected():
    duplicate = pd.Timestamp("2024-01-01T00:00:00Z")
    data = market_frame(
        [candle(), candle()],
        index=pd.DatetimeIndex([duplicate, duplicate])
    )
    engine = BacktestEngine(data, lambda index: "HOLD")

    with pytest.raises(ValueError, match="unique"):
        engine.run()


def test_non_monotonic_timestamps_are_rejected():
    data = market_frame(
        [candle(), candle()],
        index=pd.DatetimeIndex([
            pd.Timestamp("2024-01-01T01:00:00Z"),
            pd.Timestamp("2024-01-01T00:00:00Z")
        ])
    )
    engine = BacktestEngine(data, lambda index: "HOLD")

    with pytest.raises(ValueError, match="monotonic"):
        engine.run()
