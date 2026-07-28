from typing import Dict, Optional

from broker.base import Broker, BrokerOrder, OrderStatus
from paper.paper_trader import PaperTrader


class PaperBroker(Broker):
    """Broker adapter that preserves the existing PaperTrader implementation."""

    def __init__(self, trader: Optional[PaperTrader] = None):
        self.trader = trader or PaperTrader()
        self.orders: Dict[str, BrokerOrder] = {}

    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        side = order.side.upper()
        if side not in {"BUY", "SELL"} or order.quantity <= 0:
            order.status = OrderStatus.REJECTED
            self.orders[order.order_id] = order
            return order

        trade = self.trader.open_trade(
            order.symbol,
            side,
            order.entry,
            order.stop_loss,
            order.take_profit,
            order.quantity,
        )
        if trade is None:
            order.status = OrderStatus.REJECTED
        else:
            order.status = OrderStatus.FILLED
            order.broker_reference = order.order_id
            trade["order_id"] = order.order_id
            self.trader.save_trades()

        self.orders[order.order_id] = order
        return order

    def close_order(self, order_id: str, exit_price: float) -> BrokerOrder:
        order = self._require_order(order_id)
        if order.status != OrderStatus.FILLED:
            raise ValueError(f"Order {order_id} is not open")

        for trade in self.trader.open_trades:
            if trade.get("order_id") == order_id:
                trade["stop_loss"] = float(exit_price)
                trade["take_profit"] = float(exit_price)
                self.trader.check_trade(order.symbol, float(exit_price))
                order.status = OrderStatus.CLOSED
                return order

        raise KeyError(f"Open paper trade for {order_id} not found")

    def cancel_order(self, order_id: str) -> BrokerOrder:
        order = self._require_order(order_id)
        if order.status != OrderStatus.PENDING:
            raise ValueError("Only pending orders can be cancelled")
        order.status = OrderStatus.CANCELLED
        return order

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        return self.orders.get(order_id)

    def _require_order(self, order_id: str) -> BrokerOrder:
        order = self.get_order(order_id)
        if order is None:
            raise KeyError(f"Order {order_id} not found")
        return order
