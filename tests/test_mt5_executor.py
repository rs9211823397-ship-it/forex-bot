from types import SimpleNamespace

import pytest

from execution.mt5_executor import ExecutionConfig, ExecutionError, MT5Executor


class FakeMT5:
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_DONE = 10009

    def __init__(self):
        self._positions = []
        self.sent = []

    def initialize(self, **kwargs):
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "Success")

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(trade_allowed=True, trade_expert=True)

    def symbol_info(self, symbol):
        return SimpleNamespace(
            visible=True,
            trade_mode=4,
            digits=5,
            point=0.00001,
            trade_stops_level=0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            filling_mode=1,
        )

    def symbol_select(self, symbol, visible):
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=1.10000, ask=1.10002)

    def positions_get(self, symbol=None):
        if symbol:
            return tuple(p for p in self._positions if p.symbol == symbol)
        return tuple(self._positions)

    def order_check(self, request):
        return SimpleNamespace(retcode=0, comment="Done")

    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(
            retcode=10009,
            comment="Request executed",
            order=123,
            deal=456,
        )


def connected_executor(adapter=None):
    adapter = adapter or FakeMT5()
    executor = MT5Executor(ExecutionConfig(max_open_positions=3), adapter=adapter)
    executor.connect()
    return executor, adapter


def test_buy_requires_stop_loss_and_take_profit():
    executor, _ = connected_executor()
    with pytest.raises(ExecutionError, match="stop loss"):
        executor.place_market_order("EURUSD", "BUY", 0.01, 0, 1.10200)
    with pytest.raises(ExecutionError, match="take profit"):
        executor.place_market_order("EURUSD", "BUY", 0.01, 1.09800, 0)


def test_buy_request_contains_broker_side_protection():
    executor, adapter = connected_executor()
    result = executor.place_market_order(
        "EURUSD", "BUY", 0.01, stop_loss=1.09800, take_profit=1.10400
    )
    request = adapter.sent[-1]
    assert result.success is True
    assert request["sl"] == 1.098
    assert request["tp"] == 1.104
    assert request["type_filling"] == adapter.ORDER_FILLING_FOK


def test_invalid_protection_direction_is_rejected():
    executor, _ = connected_executor()
    with pytest.raises(ExecutionError, match="SL < entry < TP"):
        executor.place_market_order("EURUSD", "BUY", 0.01, 1.10100, 1.10400)


def test_duplicate_same_symbol_and_direction_is_rejected():
    executor, adapter = connected_executor()
    adapter._positions.append(
        SimpleNamespace(symbol="EURUSD", type=adapter.POSITION_TYPE_BUY, magic=20260730)
    )
    with pytest.raises(ExecutionError, match="Duplicate"):
        executor.place_market_order("EURUSD", "BUY", 0.01, 1.09800, 1.10400)


def test_pause_rejects_new_entries():
    executor, _ = connected_executor()
    executor.pause()
    with pytest.raises(ExecutionError, match="paused"):
        executor.place_market_order("EURUSD", "BUY", 0.01, 1.09800, 1.10400)


def test_emergency_stop_closes_only_managed_positions():
    executor, adapter = connected_executor()
    adapter._positions.extend(
        [
            SimpleNamespace(
                ticket=10,
                symbol="EURUSD",
                type=adapter.POSITION_TYPE_BUY,
                volume=0.01,
                magic=20260730,
            ),
            SimpleNamespace(
                ticket=20,
                symbol="GBPUSD",
                type=adapter.POSITION_TYPE_SELL,
                volume=0.01,
                magic=999,
            ),
        ]
    )
    results = executor.emergency_stop()
    assert executor.accept_new_trades is False
    assert len(results) == 1
    assert adapter.sent[-1]["position"] == 10
    assert adapter.sent[-1]["type"] == adapter.ORDER_TYPE_SELL
