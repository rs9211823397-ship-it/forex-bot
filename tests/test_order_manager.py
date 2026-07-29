"""Tests for read-only OrderManager projections."""

from datetime import datetime, timezone

from execution.models import OrderRequest
from execution.order_manager import OrderManager


NOW = datetime(2025, 5, 1, 12, tzinfo=timezone.utc)


def _request(client_order_id: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        symbol="EURUSD",
        side="BUY",
        quantity=1.0,
        created_time=NOW,
    )


def test_orders_returns_all_snapshots_in_creation_order():
    manager = OrderManager()

    first = manager.create(_request("client-1"))
    second = manager.create(_request("client-2"))

    assert manager.orders == (first, second)


def test_orders_returns_immutable_tuple_snapshot():
    manager = OrderManager()
    created = manager.create(_request("client-1"))

    orders = manager.orders

    assert orders == (created,)
    assert isinstance(orders, tuple)
