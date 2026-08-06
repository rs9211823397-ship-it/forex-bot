from datetime import datetime, timedelta, timezone
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
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_OUT_BY = 3

    def __init__(self):
        self._positions = []
        self._deals = []
        self.sent = []
        self.account_trade_mode = self.ACCOUNT_TRADE_MODE_DEMO
        self.account_login = 12345678

    def initialize(self, **kwargs):
        return True

    def shutdown(self):
        return None

    def last_error(self):
        return (1, "Success")

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(
            login=self.account_login,
            trade_allowed=True,
            trade_expert=True,
            trade_mode=self.account_trade_mode,
            balance=10_000.0,
            equity=9_975.0,
        )

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
        now = datetime.now(timezone.utc).timestamp()
        return SimpleNamespace(
            bid=1.10000,
            ask=1.10002,
            time=now,
            time_msc=int(now * 1000),
        )

    def positions_get(self, symbol=None):
        if symbol:
            return tuple(p for p in self._positions if p.symbol == symbol)
        return tuple(self._positions)

    def history_deals_get(self, start_time, end_time):
        return tuple(self._deals)

    def order_calc_profit(self, order_type, symbol, volume, open_price, close_price):
        direction = 1 if order_type == self.ORDER_TYPE_BUY else -1
        return (close_price - open_price) * direction * volume * 100_000

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


def test_connect_rejects_non_demo_account():
    adapter = FakeMT5()
    adapter.account_trade_mode = adapter.ACCOUNT_TRADE_MODE_REAL
    executor = MT5Executor(ExecutionConfig(), adapter=adapter)

    with pytest.raises(ExecutionError, match="requires a broker demo account"):
        executor.connect()

    assert executor.connected is False


def test_preauthenticated_connect_validates_expected_login():
    adapter = FakeMT5()
    executor = MT5Executor(
        ExecutionConfig(expected_login=12345678),
        adapter=adapter,
    )

    assert executor.connect() is True

    adapter = FakeMT5()
    adapter.account_login = 87654321
    executor = MT5Executor(
        ExecutionConfig(expected_login=12345678),
        adapter=adapter,
    )
    with pytest.raises(ExecutionError, match="unexpected account login"):
        executor.connect()


def managed_position(adapter, *, ticket=10, volume=0.05):
    return SimpleNamespace(
        ticket=ticket,
        symbol="EURUSD",
        type=adapter.POSITION_TYPE_BUY,
        volume=volume,
        magic=20260730,
        price_open=1.09800,
        price_current=1.10000,
        sl=1.09600,
        tp=1.10400,
        time=1_700_000_000,
        profit=10.0,
        comment="AAQTS",
    )


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


def test_reference_distances_are_translated_to_current_broker_quote():
    executor, adapter = connected_executor()

    executor.place_market_order(
        "EURUSD",
        "BUY",
        0.01,
        stop_loss=1.19800,
        take_profit=1.20400,
        reference_entry=1.20000,
    )

    request = adapter.sent[-1]
    assert request["price"] == 1.10002
    assert request["sl"] == 1.09802
    assert request["tp"] == 1.10402


def test_broker_contract_risk_sizes_volume_without_rounding_up():
    executor, adapter = connected_executor()

    executor.place_market_order(
        "EURUSD",
        "BUY",
        None,
        stop_loss=1.09800,
        take_profit=1.10400,
        risk_amount=4.0,
    )

    assert adapter.sent[-1]["volume"] == 0.01


def test_broker_minimum_volume_cannot_exceed_approved_risk():
    executor, _ = connected_executor()

    with pytest.raises(ExecutionError, match="minimum volume would exceed"):
        executor.place_market_order(
            "EURUSD",
            "BUY",
            None,
            stop_loss=1.09800,
            take_profit=1.10400,
            risk_amount=1.0,
        )


def test_volume_normalization_never_rounds_risk_up():
    executor, adapter = connected_executor()

    executor.place_market_order(
        "EURUSD", "BUY", 0.019, stop_loss=1.09800, take_profit=1.10400
    )

    assert adapter.sent[-1]["volume"] == 0.01


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


def test_position_management_market_data_contract_is_exposed():
    executor, _ = connected_executor()

    assert executor.symbol_info("EURUSD").digits == 5
    assert executor.symbol_tick("EURUSD").bid == 1.10000


def test_account_snapshot_uses_broker_balance_and_equity():
    executor, _ = connected_executor()

    snapshot = executor.account_snapshot()

    assert snapshot.balance == 10_000.0
    assert snapshot.equity == 9_975.0


def test_closed_results_include_only_managed_exit_deals():
    executor, adapter = connected_executor()
    now = datetime.now(timezone.utc)
    adapter._deals.extend(
        [
            SimpleNamespace(
                magic=20260730,
                entry=adapter.DEAL_ENTRY_OUT,
                time=now.timestamp(),
                profit=-20.0,
                swap=-1.0,
                commission=-2.0,
                fee=-0.5,
            ),
            SimpleNamespace(
                magic=999,
                entry=adapter.DEAL_ENTRY_OUT,
                time=now.timestamp(),
                profit=100.0,
            ),
            SimpleNamespace(
                magic=20260730,
                entry=adapter.DEAL_ENTRY_IN,
                time=now.timestamp(),
                profit=0.0,
            ),
        ]
    )

    results = executor.closed_position_results(
        now - timedelta(days=1),
        now + timedelta(seconds=1),
    )

    assert len(results) == 1
    assert results[0].profit_loss == -23.5
    assert results[0].closed_at == now


def test_remaining_loss_at_stop_uses_current_broker_price():
    executor, adapter = connected_executor()
    position = managed_position(adapter)

    risk = executor.remaining_loss_at_stop(position)

    assert risk == pytest.approx(20.0)


def test_move_to_break_even_updates_broker_side_protection():
    executor, adapter = connected_executor()
    adapter._positions.append(managed_position(adapter))

    result = executor.move_to_break_even(10)

    assert result.success is True
    assert adapter.sent[-1]["action"] == adapter.TRADE_ACTION_SLTP
    assert adapter.sent[-1]["position"] == 10
    assert adapter.sent[-1]["sl"] == 1.098
    assert adapter.sent[-1]["tp"] == 1.104


def test_trailing_stop_update_preserves_existing_take_profit():
    executor, adapter = connected_executor()
    adapter._positions.append(managed_position(adapter))

    result = executor.update_trailing_stop(10, 1.09900)

    assert result.success is True
    assert adapter.sent[-1]["sl"] == 1.099
    assert adapter.sent[-1]["tp"] == 1.104


def test_partial_close_uses_requested_volume_and_preserves_remainder():
    executor, adapter = connected_executor()
    adapter._positions.append(managed_position(adapter, volume=0.05))

    result = executor.partial_close(10, 0.02, "AAQTS TP1")

    assert result.success is True
    assert adapter.sent[-1]["position"] == 10
    assert adapter.sent[-1]["volume"] == 0.02
    assert adapter.sent[-1]["type"] == adapter.ORDER_TYPE_SELL


def test_partial_close_rejects_full_position_volume():
    executor, adapter = connected_executor()
    adapter._positions.append(managed_position(adapter, volume=0.05))

    with pytest.raises(ExecutionError, match="smaller than"):
        executor.partial_close(10, 0.05)
