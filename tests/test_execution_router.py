import pytest

from execution.execution_router import ExecutionRouter
from execution.mt5_executor import ExecutionError


RISK_PLAN = {
    "entry": 1.1000,
    "stop_loss": 1.0950,
    "take_profit": 1.1100,
}


class FakePaperTrader:
    def __init__(self):
        self.open_trades = []

    def open_trade(
        self,
        symbol,
        signal,
        entry,
        stop_loss,
        take_profit,
        position,
    ):
        trade = {
            "symbol": symbol,
            "signal": signal,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position": position,
        }
        self.open_trades.append(trade)
        return trade


class Position:
    ticket = 11


class FakeMT5Executor:
    def __init__(self):
        self.connected = False
        self.paused = False
        self.resumed = False
        self.emergency_called = False
        self.calls = []

    def connect(self):
        self.connected = True
        return True

    def recover_positions(self):
        return [Position()]

    def place_market_order(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs

    def pause(self):
        self.paused = True

    def resume(self):
        self.resumed = True

    def emergency_stop(self):
        self.emergency_called = True
        return ["closed"]

    def positions(self, managed_only=True):
        return [Position()]

    def shutdown(self):
        self.connected = False


def test_paper_mode_routes_to_paper_trader():
    paper = FakePaperTrader()
    router = ExecutionRouter(paper_trader=paper, mode="PAPER")

    result = router.execute("EURUSD=X", "BUY", RISK_PLAN, 2.5)

    assert result["symbol"] == "EURUSD=X"
    assert result["position"] == 2.5
    assert len(paper.open_trades) == 1


def test_mt5_demo_routes_to_mapped_broker_symbol():
    paper = FakePaperTrader()
    mt5 = FakeMT5Executor()
    router = ExecutionRouter(
        paper_trader=paper,
        mode="MT5_DEMO",
        mt5_executor=mt5,
    )

    recovered = router.start()
    result = router.execute("EURUSD=X", "BUY", RISK_PLAN, 99.0)

    assert mt5.connected is True
    assert recovered[0].ticket == 11
    assert result["symbol"] == "EURUSD"
    assert result["volume"] == 0.01
    assert result["stop_loss"] == 1.0950
    assert paper.open_trades == []


def test_live_mode_is_locked():
    with pytest.raises(ExecutionError, match="locked"):
        ExecutionRouter(paper_trader=FakePaperTrader(), mode="MT5_LIVE")


def test_unknown_mt5_symbol_is_rejected():
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(),
        mode="MT5_DEMO",
        mt5_executor=FakeMT5Executor(),
    )

    with pytest.raises(ExecutionError, match="No MT5 symbol mapping"):
        router.execute("UNKNOWN-USD", "BUY", RISK_PLAN, 1.0)


def test_pause_resume_and_emergency_are_forwarded():
    mt5 = FakeMT5Executor()
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(),
        mode="MT5_DEMO",
        mt5_executor=mt5,
    )

    router.pause()
    router.resume()
    result = router.emergency_stop()

    assert mt5.paused is True
    assert mt5.resumed is True
    assert mt5.emergency_called is True
    assert result == ["closed"]
