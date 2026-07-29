from datetime import datetime, timezone

import pytest

from broker.adapters import PaperAdapter
from execution.models import OrderRequest, OrderSide
from execution.simulation import BrokerSimulator
from risk.instrument import InstrumentSpec


def make_instrument() -> InstrumentSpec:
    return InstrumentSpec(
        symbol="EURUSD",
        contract_multiplier=100000.0,
        tick_size=0.00001,
        quantity_step=0.01,
        minimum_quantity=0.01,
        maximum_quantity=100.0,
        spread=0.0001,
        slippage=0.0,
        commission_per_quantity=0.0,
    )


def make_request(client_order_id: str = "paper-adapter-test-1") -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol="EURUSD",
        side=OrderSide.BUY,
        quantity=1.0,
        created_time=datetime.now(timezone.utc),
    )


def make_adapter() -> PaperAdapter:
    simulator = BrokerSimulator(make_instrument())
    return PaperAdapter(simulator)


def test_health_reports_paper_adapter_ready():
    adapter = make_adapter()

    health = adapter.health()

    assert health.adapter == "PAPER"
    assert health.ready is True
    assert health.reason == "Paper execution simulator is ready"


def test_submit_order_returns_broker_snapshot():
    adapter = make_adapter()

    result = adapter.submit_order("paper-account", make_request())

    assert result.account_id == "paper-account"
    assert result.client_order_id == "paper-adapter-test-1"
    assert result.symbol == "EURUSD"
    assert result.side is OrderSide.BUY
    assert result.quantity == 1.0
    assert result.filled_quantity == 0.0
    assert result.state == "ACKNOWLEDGED"


def test_orders_returns_submitted_order_projection():
    adapter = make_adapter()
    submitted = adapter.submit_order("paper-account", make_request())

    orders = adapter.orders("paper-account")

    assert isinstance(orders, tuple)
    assert len(orders) == 1
    assert orders[0].order_id == submitted.order_id
    assert orders[0].client_order_id == "paper-adapter-test-1"


def test_cancel_order_updates_order_projection():
    adapter = make_adapter()
    submitted = adapter.submit_order("paper-account", make_request())

    cancelled = adapter.cancel_order(
        "paper-account",
        submitted.order_id,
    )

    assert cancelled.order_id == submitted.order_id
    assert cancelled.state == "CANCELLED"

    orders = adapter.orders("paper-account")

    assert len(orders) == 1
    assert orders[0].state == "CANCELLED"


def test_adapter_rejects_different_account_after_binding():
    adapter = make_adapter()
    adapter.submit_order("paper-account", make_request())

    with pytest.raises(
        ValueError,
        match="already bound to another account",
    ):
        adapter.orders("different-account")


@pytest.mark.parametrize("account_id", ["", "   ", None])
def test_adapter_rejects_invalid_account_id(account_id):
    adapter = make_adapter()

    with pytest.raises(
        ValueError,
        match="account_id must be a non-empty string",
    ):
        adapter.orders(account_id)
