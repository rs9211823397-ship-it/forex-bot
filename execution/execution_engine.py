from broker.base import Broker, BrokerOrder, OrderStatus


class ExecutionEngine:
    """Validates and routes strategy orders through a configured broker."""

    def __init__(self, broker: Broker, logger=None):
        self.broker = broker
        self.logger = logger

    def submit_market_order(
        self,
        symbol,
        side,
        quantity,
        entry,
        stop_loss,
        take_profit,
        metadata=None,
    ):
        self._validate_order(side, quantity, entry, stop_loss, take_profit)
        order = BrokerOrder(
            symbol=symbol,
            side=side.upper(),
            quantity=float(quantity),
            entry=float(entry),
            stop_loss=float(stop_loss),
            take_profit=float(take_profit),
            metadata=metadata or {},
        )

        if self.logger:
            self.logger.log_event("order_submitted", order_id=order.order_id, symbol=symbol)

        result = self.broker.place_order(order)

        if self.logger:
            self.logger.log_event(
                "order_result",
                order_id=result.order_id,
                symbol=result.symbol,
                status=result.status.value,
            )
        return result

    @staticmethod
    def _validate_order(side, quantity, entry, stop_loss, take_profit):
        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if float(quantity) <= 0:
            raise ValueError("quantity must be greater than zero")

        entry = float(entry)
        stop_loss = float(stop_loss)
        take_profit = float(take_profit)
        if side == "BUY" and not (stop_loss < entry < take_profit):
            raise ValueError("BUY requires stop_loss < entry < take_profit")
        if side == "SELL" and not (take_profit < entry < stop_loss):
            raise ValueError("SELL requires take_profit < entry < stop_loss")
