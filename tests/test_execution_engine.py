import unittest

from broker.base import BrokerOrder, OrderStatus
from execution.execution_engine import ExecutionEngine


class FakeBroker:
    def __init__(self):
        self.order = None

    def place_order(self, order):
        self.order = order
        order.status = OrderStatus.FILLED
        return order

    def close_order(self, order_id, exit_price):
        raise NotImplementedError

    def cancel_order(self, order_id):
        raise NotImplementedError

    def get_order(self, order_id):
        return self.order if self.order and self.order.order_id == order_id else None


class ExecutionEngineTests(unittest.TestCase):
    def setUp(self):
        self.broker = FakeBroker()
        self.engine = ExecutionEngine(self.broker)

    def test_valid_buy_is_filled(self):
        order = self.engine.submit_market_order(
            "EURUSD=X", "BUY", 0.1, 1.1000, 1.0950, 1.1100
        )
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.side, "BUY")

    def test_invalid_buy_levels_are_rejected_before_broker(self):
        with self.assertRaises(ValueError):
            self.engine.submit_market_order(
                "EURUSD=X", "BUY", 0.1, 1.1000, 1.1050, 1.1100
            )
        self.assertIsNone(self.broker.order)

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.submit_market_order(
                "EURUSD=X", "SELL", 0, 1.1000, 1.1050, 1.0900
            )


if __name__ == "__main__":
    unittest.main()
