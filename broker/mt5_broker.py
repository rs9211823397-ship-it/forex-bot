from __future__ import annotations

from typing import Dict, Optional

from broker.base import Broker, BrokerOrder, OrderStatus


class MT5Broker(Broker):
    """MetaTrader 5 broker adapter with explicit connection and symbol checks.

    The MetaTrader5 package is imported lazily so paper trading and tests remain
    usable on machines where the Windows-only MT5 terminal dependency is absent.
    """

    def __init__(self, login=None, password=None, server=None, terminal_path=None, deviation=20, magic=31003, mt5_module=None):
        self.login = login
        self.password = password
        self.server = server
        self.terminal_path = terminal_path
        self.deviation = int(deviation)
        self.magic = int(magic)
        self.orders: Dict[str, BrokerOrder] = {}
        self.mt5 = mt5_module or self._load_mt5()
        self.connected = False

    @staticmethod
    def _load_mt5():
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError(
                "MetaTrader5 package is required for live execution. "
                "Install it only on the Windows machine running the MT5 terminal."
            ) from exc
        return mt5

    def connect(self) -> None:
        kwargs = {}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if self.login is not None:
            kwargs["login"] = int(self.login)
        if self.password is not None:
            kwargs["password"] = self.password
        if self.server is not None:
            kwargs["server"] = self.server

        if not self.mt5.initialize(**kwargs):
            raise ConnectionError(f"MT5 initialization failed: {self.mt5.last_error()}")
        self.connected = True

    def disconnect(self) -> None:
        if self.connected:
            self.mt5.shutdown()
            self.connected = False

    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        self._require_connection()
        info = self._require_symbol(order.symbol)
        tick = self.mt5.symbol_info_tick(order.symbol)
        if tick is None:
            return self._reject(order, "No market tick available")

        is_buy = order.side.upper() == "BUY"
        order_type = self.mt5.ORDER_TYPE_BUY if is_buy else self.mt5.ORDER_TYPE_SELL
        price = float(tick.ask if is_buy else tick.bid)
        volume = self._normalize_volume(order.quantity, info)

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": order.symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": float(order.stop_loss),
            "tp": float(order.take_profit),
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": f"forex-bot:{order.order_id[:12]}",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }
        result = self.mt5.order_send(request)
        if result is None:
            return self._reject(order, f"order_send failed: {self.mt5.last_error()}")

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return self._reject(order, f"MT5 retcode={result.retcode}; comment={getattr(result, 'comment', '')}")

        order.status = OrderStatus.FILLED
        order.entry = price
        order.quantity = volume
        order.broker_reference = str(getattr(result, "order", None) or getattr(result, "deal", ""))
        order.metadata.update({"mt5_retcode": result.retcode, "fill_price": price})
        self.orders[order.order_id] = order
        return order

    def close_order(self, order_id: str, exit_price: float = 0.0) -> BrokerOrder:
        self._require_connection()
        order = self._require_order(order_id)
        if order.status != OrderStatus.FILLED:
            raise ValueError(f"Order {order_id} is not open")

        positions = self.mt5.positions_get(symbol=order.symbol) or []
        position = next(
            (p for p in positions if str(getattr(p, "ticket", "")) == str(order.broker_reference)),
            positions[0] if len(positions) == 1 else None,
        )
        if position is None:
            raise KeyError(f"Open MT5 position for {order_id} not found")

        tick = self.mt5.symbol_info_tick(order.symbol)
        if tick is None:
            raise RuntimeError("No market tick available for close")
        close_is_buy = order.side.upper() == "SELL"
        price = float(tick.ask if close_is_buy else tick.bid)
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": order.symbol,
            "volume": float(position.volume),
            "type": self.mt5.ORDER_TYPE_BUY if close_is_buy else self.mt5.ORDER_TYPE_SELL,
            "price": price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": f"forex-bot-close:{order.order_id[:8]}",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(self._require_symbol(order.symbol)),
        }
        result = self.mt5.order_send(request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            retcode = getattr(result, "retcode", None)
            raise RuntimeError(f"MT5 close failed: retcode={retcode}; error={self.mt5.last_error()}")
        order.status = OrderStatus.CLOSED
        order.metadata.update({"close_price": price, "close_retcode": result.retcode})
        return order

    def cancel_order(self, order_id: str) -> BrokerOrder:
        order = self._require_order(order_id)
        if order.status != OrderStatus.PENDING or not order.broker_reference:
            raise ValueError("Only pending MT5 orders can be cancelled")
        result = self.mt5.order_send({"action": self.mt5.TRADE_ACTION_REMOVE, "order": int(order.broker_reference)})
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError("MT5 cancellation failed")
        order.status = OrderStatus.CANCELLED
        return order

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        return self.orders.get(order_id)

    def _require_connection(self) -> None:
        if not self.connected:
            raise ConnectionError("MT5 broker is not connected")

    def _require_symbol(self, symbol):
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(f"Unknown MT5 symbol: {symbol}")
        if not info.visible and not self.mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Unable to enable MT5 symbol: {symbol}")
        return info

    @staticmethod
    def _normalize_volume(quantity, info):
        minimum = float(info.volume_min)
        maximum = float(info.volume_max)
        step = float(info.volume_step)
        value = min(max(float(quantity), minimum), maximum)
        steps = round((value - minimum) / step)
        return round(minimum + steps * step, 8)

    def _filling_mode(self, info):
        return getattr(info, "filling_mode", self.mt5.ORDER_FILLING_IOC)

    def _reject(self, order, reason):
        order.status = OrderStatus.REJECTED
        order.metadata["rejection_reason"] = reason
        self.orders[order.order_id] = order
        return order

    def _require_order(self, order_id):
        order = self.orders.get(order_id)
        if order is None:
            raise KeyError(f"Order {order_id} not found")
        return order
