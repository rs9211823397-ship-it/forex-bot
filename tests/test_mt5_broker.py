from types import SimpleNamespace

import pytest

from broker.base import BrokerOrder, OrderStatus
from broker.mt5_broker import MT5Broker


class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 10
    TRADE_ACTION_REMOVE = 11
    ORDER_TIME_GTC = 20
    ORDER_FILLING_IOC = 30
    TRADE_RETCODE_DONE = 10009

    def __init__(self):
        self.initialized = False
        self.requests = []
        self.info = SimpleNamespace(
            visible=True,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            filling_mode=self.ORDER_FILLING_IOC,
        )

    def initialize(self, **kwargs):
        self.initialized = True
        return True

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return (0, "ok")

    def symbol_info(self, symbol):
        return self.info if symbol == "EURUSD" else None

    def symbol_select(self, symbol, enabled):
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(ask=1.1002, bid=1.1000)

    def order_send(self, request):
        self.requests.append(request)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=12345, deal=0, comment="done")

    def positions_get(self, symbol=None):
        return [SimpleNamespace(ticket=12345, volume=0.1)]


def make_order(quantity=0.1):
    return BrokerOrder(
        symbol="EURUSD",
        side="BUY",
        quantity=quantity,
        entry=1.1001,
        stop_loss=1.0950,
        take_profit=1.1100,
    )


def test_requires_explicit_connection():
    broker = MT5Broker(mt5_module=FakeMT5())
    with pytest.raises(ConnectionError):
        broker.place_order(make_order())


def test_places_market_order_and_maps_broker_reference():
    fake = FakeMT5()
    broker = MT5Broker(mt5_module=fake)
    broker.connect()

    result = broker.place_order(make_order())

    assert result.status == OrderStatus.FILLED
    assert result.broker_reference == "12345"
    assert result.entry == 1.1002
    assert fake.requests[0]["symbol"] == "EURUSD"
    assert fake.requests[0]["sl"] == 1.0950
    assert fake.requests[0]["tp"] == 1.1100


def test_normalizes_volume_to_symbol_limits():
    fake = FakeMT5()
    broker = MT5Broker(mt5_module=fake)
    broker.connect()

    result = broker.place_order(make_order(quantity=0.106))

    assert result.quantity == 0.11
    assert fake.requests[0]["volume"] == 0.11


def test_unknown_symbol_is_rejected_before_order_send():
    fake = FakeMT5()
    broker = MT5Broker(mt5_module=fake)
    broker.connect()
    order = make_order()
    order.symbol = "UNKNOWN"

    with pytest.raises(ValueError, match="Unknown MT5 symbol"):
        broker.place_order(order)
    assert fake.requests == []


def test_close_order_sends_opposite_market_deal():
    fake = FakeMT5()
    broker = MT5Broker(mt5_module=fake)
    broker.connect()
    opened = broker.place_order(make_order())

    closed = broker.close_order(opened.order_id)

    assert closed.status == OrderStatus.CLOSED
    assert fake.requests[-1]["position"] == 12345
    assert fake.requests[-1]["type"] == fake.ORDER_TYPE_SELL
    assert fake.requests[-1]["price"] == 1.1000
