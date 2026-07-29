from datetime import datetime, timezone

import pytest

from execution.models import OrderRequest, OrderSide
from execution.router import ExecutionRouter, create_paper_router
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


def make_request() -> OrderRequest:
    return OrderRequest(
        client_order_id="router-test-1",
        symbol="EURUSD",
        side=OrderSide.BUY,
        quantity=1.0,
        created_time=datetime.now(timezone.utc),
    )


def test_router_delegates_submission_to_backend():
    simulator = BrokerSimulator(make_instrument())
    router = ExecutionRouter(simulator)

    result = router.submit(make_request())

    assert result.request.client_order_id == "router-test-1"


def test_create_paper_router_returns_router():
    simulator = BrokerSimulator(make_instrument())

    router = create_paper_router(simulator)

    assert isinstance(router, ExecutionRouter)
    assert router.backend is simulator


def test_router_rejects_invalid_backend():
    with pytest.raises(TypeError):
        ExecutionRouter(object())
