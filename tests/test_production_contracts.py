"""Production-facing API and execution safety contracts."""

from datetime import datetime, timedelta, timezone
import inspect

import pandas as pd
import pytest

from execution.models import OrderRequest, OrderState
from execution.order_manager import OrderLifecycleError, OrderManager
from execution.simulation import BrokerSimulator
from risk.instrument import InstrumentSpec
from strategy.signal_engine import SignalEngine


NOW = datetime(2025, 2, 1, 12, tzinfo=timezone.utc)


def _instrument():
    return InstrumentSpec(
        symbol="EURUSD",
        tick_size=0.0001,
        contract_multiplier=100_000.0,
        quantity_step=0.01,
        minimum_quantity=0.01,
        maximum_quantity=100.0,
        spread=0.0002,
        slippage=0.0001,
        commission_per_quantity=0.0,
    )


def _request(**overrides):
    values = {
        "client_order_id": "contract-order",
        "symbol": "EURUSD",
        "side": "BUY",
        "quantity": 1.0,
        "created_time": NOW,
    }
    values.update(overrides)
    return OrderRequest(**values)


def test_signal_engine_public_signature_and_legacy_dictionary_are_stable():
    assert str(inspect.signature(SignalEngine)) == "()"
    assert str(inspect.signature(SignalEngine.generate_signal)) == (
        "(self, data, symbol, higher_tf=None)"
    )

    decision = SignalEngine().generate_signal(
        pd.DataFrame({"ADX": [19.999]}),
        "EURUSD=X",
    )

    assert decision == {
        "signal": "HOLD",
        "confidence": 0,
        "score": 0,
        "reasons": ["Weak market (ADX below 20)"],
    }
    assert isinstance(decision, dict)


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        [],
        pd.DataFrame(),
        pd.DataFrame({"close": [1.0]}),
    ],
)
def test_signal_engine_fails_closed_for_malformed_inputs(malformed):
    decision = SignalEngine().generate_signal(malformed, "EURUSD=X")

    assert decision["signal"] == "HOLD"
    assert decision["confidence"] == 0
    assert decision["score"] == 0
    assert decision["reasons"]


def test_order_request_rejects_non_datetime_and_naive_timestamps():
    with pytest.raises(TypeError, match="datetime"):
        _request(created_time="2025-02-01T12:00:00Z")
    with pytest.raises(ValueError, match="timezone"):
        _request(created_time=datetime(2025, 2, 1, 12))


def test_limit_order_waits_for_price_and_never_fills_worse_than_limit():
    simulator = BrokerSimulator(_instrument())
    submitted = simulator.submit(
        _request(order_type="LIMIT", limit_price=1.0990)
    )

    no_fill = simulator.process_bar(
        1.1000,
        NOW + timedelta(minutes=1),
    )
    fill = simulator.process_bar(
        1.0980,
        NOW + timedelta(minutes=2),
    )

    assert submitted.state is OrderState.ACKNOWLEDGED
    assert no_fill == ()
    assert len(fill) == 1
    assert fill[0].state is OrderState.FILLED
    assert fill[0].average_fill_price <= 1.0990


def test_order_lifecycle_rejects_events_that_move_backwards():
    manager = OrderManager()
    created = manager.create(_request())
    submitted = manager.submit(
        created.order_id,
        NOW + timedelta(seconds=2),
    )

    with pytest.raises(OrderLifecycleError, match="backwards"):
        manager.acknowledge(
            submitted.order_id,
            NOW + timedelta(seconds=1),
        )


def test_terminal_order_cannot_receive_an_additional_fill():
    manager = OrderManager()
    created = manager.create(_request())
    submitted = manager.submit(created.order_id, NOW)
    acknowledged = manager.acknowledge(submitted.order_id, NOW)
    filled = manager.record_fill(
        acknowledged.order_id,
        quantity=1.0,
        reference_price=1.1,
        price=1.1,
        commission=0.0,
        fill_time=NOW + timedelta(seconds=1),
    )

    assert filled.state is OrderState.FILLED
    with pytest.raises(
        OrderLifecycleError,
        match="remaining|FILLED",
    ):
        manager.record_fill(
            filled.order_id,
            quantity=0.01,
            reference_price=1.1,
            price=1.1,
            commission=0.0,
            fill_time=NOW + timedelta(seconds=2),
        )


def test_explicit_expiry_precedes_fill_at_same_market_timestamp():
    simulator = BrokerSimulator(_instrument())
    submitted = simulator.submit(
        _request(expire_time=NOW + timedelta(minutes=1))
    )

    changed = simulator.process_bar(
        1.1,
        NOW + timedelta(minutes=1),
    )

    assert submitted.state is OrderState.ACKNOWLEDGED
    assert len(changed) == 1
    assert changed[0].state is OrderState.EXPIRED
    assert simulator.order_manager.fills == ()
