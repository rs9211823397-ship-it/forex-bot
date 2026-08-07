from types import SimpleNamespace

import pytest

from execution.live_mt5_executor import LiveMT5Executor
from execution.mt5_executor import ExecutionConfig, ExecutionError


class FakeLiveMT5:
    ACCOUNT_TRADE_MODE_REAL = 2
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self, *, login=123456, server="Broker-Real", trade_mode=2):
        self.login = login
        self.server = server
        self.trade_mode = trade_mode
        self.shutdown_calls = 0

    def initialize(self, **kwargs):
        return True

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(
            login=self.login,
            server=self.server,
            trade_mode=self.trade_mode,
            trade_allowed=True,
            trade_expert=True,
        )

    def shutdown(self):
        self.shutdown_calls += 1

    def last_error(self):
        return (1, "Success")


def config(*, expected_login=123456, server="Broker-Real"):
    return ExecutionConfig(expected_login=expected_login, server=server)


def test_live_executor_accepts_only_matching_real_identity():
    executor = LiveMT5Executor(config(), adapter=FakeLiveMT5())
    assert executor.connect() is True
    assert executor.connected is True


def test_live_executor_rejects_demo_account():
    executor = LiveMT5Executor(config(), adapter=FakeLiveMT5(trade_mode=0))
    with pytest.raises(ExecutionError, match="REAL broker account"):
        executor.connect()


def test_live_executor_rejects_wrong_login():
    executor = LiveMT5Executor(config(), adapter=FakeLiveMT5(login=999999))
    with pytest.raises(ExecutionError, match="unexpected account login"):
        executor.connect()


def test_live_executor_rejects_wrong_server():
    executor = LiveMT5Executor(config(), adapter=FakeLiveMT5(server="Wrong-Real"))
    with pytest.raises(ExecutionError, match="unexpected server"):
        executor.connect()


def test_live_executor_requires_pin_and_server():
    with pytest.raises(ExecutionError, match="pinned expected login"):
        LiveMT5Executor(config(expected_login=None), adapter=FakeLiveMT5()).connect()
    with pytest.raises(ExecutionError, match="expected server"):
        LiveMT5Executor(config(server=""), adapter=FakeLiveMT5()).connect()
