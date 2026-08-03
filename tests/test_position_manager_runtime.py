import time
from types import SimpleNamespace

from execution.position_manager import PositionManager, PositionManagerConfig


class LifecycleExecutor:
    def __init__(self):
        self.mt5 = SimpleNamespace(POSITION_TYPE_BUY=0, POSITION_TYPE_SELL=1)
        self.position = SimpleNamespace(
            ticket=42,
            symbol="EURUSD",
            type=0,
            volume=0.10,
            price_open=1.10000,
            price_current=1.10300,
            sl=1.09800,
            tp=1.10600,
            time=time.time(),
            profit=30.0,
            swap=0.0,
            magic=20260730,
            comment="AAQTS",
            reason=0,
        )
        self.actions = []

    def positions(self, managed_only=True):
        return [self.position] if self.position is not None else []

    def recover_positions(self):
        return self.positions()

    def symbol_tick(self, symbol):
        return SimpleNamespace(bid=1.10300, ask=1.10302)

    def symbol_info(self, symbol):
        return SimpleNamespace(
            point=0.00001,
            digits=5,
            volume_min=0.01,
            volume_step=0.01,
        )

    def modify_protection(self, ticket, stop_loss, take_profit):
        self.position.sl = stop_loss
        self.position.tp = take_profit
        self.actions.append(("PROTECTION", stop_loss, take_profit))
        return SimpleNamespace(success=True, retcode=10009, comment="Done")

    def move_to_break_even(self, ticket):
        return self.modify_protection(ticket, self.position.price_open, self.position.tp)

    def update_trailing_stop(self, ticket, stop_loss):
        return self.modify_protection(ticket, stop_loss, self.position.tp)

    def partial_close(self, ticket, volume, comment=""):
        self.position.volume = round(self.position.volume - volume, 8)
        self.actions.append(("PARTIAL", volume, comment))
        return SimpleNamespace(success=True, retcode=10009, comment="Done")

    def close_position(self, ticket, comment=""):
        self.position = None
        self.actions.append(("CLOSE", ticket, comment))
        return SimpleNamespace(success=True, retcode=10009, comment="Done")

    def pause(self):
        self.actions.append(("PAUSE",))


def test_runtime_cycle_recovers_break_even_and_trails_position():
    executor = LifecycleExecutor()
    manager = PositionManager(
        executor,
        PositionManagerConfig(
            sync_interval_seconds=0,
            position_refresh_seconds=0,
            enable_tp1=False,
            enable_tp2=False,
            enable_time_exit=False,
        ),
    )

    recovered = manager.recover_positions(reset_registry=True)
    report = manager.manage_positions({"EURUSD": 0.00100}, force_sync=True)

    assert recovered[0].ticket == 42
    assert report["errors"] == []
    actions = report["reports"][0]["actions"]
    assert [action["action"] for action in actions] == [
        "BREAK_EVEN",
        "TRAILING_STOP",
    ]
    assert manager.get(42).break_even_done is True
    assert manager.get(42).trailing_active is True
    assert executor.position.sl > executor.position.price_open


def test_runtime_cycle_executes_broker_valid_partial_take_profit():
    executor = LifecycleExecutor()
    manager = PositionManager(
        executor,
        PositionManagerConfig(
            sync_interval_seconds=0,
            position_refresh_seconds=0,
            enable_break_even=False,
            enable_trailing_stop=False,
            enable_tp1=True,
            enable_tp2=False,
            enable_time_exit=False,
        ),
    )
    manager.recover_positions(reset_registry=True)

    report = manager.manage_positions(force_sync=True)

    assert report["errors"] == []
    action = report["reports"][0]["actions"][0]
    assert action["action"] == "TP1"
    assert action["success"] is True
    assert executor.position.volume == 0.05
    assert manager.get(42).tp1_done is True
