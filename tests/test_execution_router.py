from types import SimpleNamespace

import pytest

from execution.execution_router import ExecutionRouter
from execution.mt5_executor import ExecutionError


class FakePaperTrader:
    def __init__(self):
        self.open_trades = []

    def open_trade(self, symbol, signal, entry, stop_loss, take_profit, position):
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


class FakeMT5Executor:
    def __init__(self):
        self.connected = False
        self.paused = False
        self.orders = []
        self._positions = [SimpleNamespace(ticket=11)]

    def connect(self):
        self.connected = True
        return True

    def recover_positions(self):
        return self._positions

    def place_market_order(self, **kwargs):
        self.orders.append(kwargs)
        return kwargs

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def emergency_stop(self):
        self.paused = True
        closed = list(self._positions)
        self._positions = []
        return closed

    def positions(self, managed_only=True):
        return self._positions

    def shutdown(self):
        self.connected = False


RISK_PLAN = {
    "entry": 1.1000,
    "stop_loss": 1.0950,
    "take_profit": 1.1100,
}


def test_paper_mode_routes_to_paper_trader():
    paper = FakePaperTrader()
    router = ExecutionRouter(paper_trader=paper, mode="PAPER")

    result = router.execute("EURUSD=X", "BUY", RISK_PLAN, 123.0)

    assert result["symbol"] == "EURUSD=X"
    assert result["stop_loss"] == 1.0950
    assert len(paper.open_trades) == 1


def test_mt5_demo_connects_recovers_and_maps_symbol():
    paper = FakePaperTrader()
    mt5 = FakeMT5Executor()
    router = ExecutionRouter(paper_trader=paper, mode="MT5_DEMO", mt5_executor=mt5)

    recovered = router.start()
    result = router.execute("EURUSD=X", "BUY", RISK_PLAN, 999999.0)

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
        router.execute("SOL-USD", "BUY", RISK_PLAN, 1.0)


def test_pause_resume_and_emergency_are_forwarded():
    mt5 = FakeMT5Executor()
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(),
        mode="MT5_DEMO",
        mt5_executor=mt5,
    )

    router.pause()
    assert mt5.paused is True
    router.resume()
    assert mt5.paused is False
    closed = router.emergency_stop()
    assert len(closed) == 1
    assert router.positions() == []
