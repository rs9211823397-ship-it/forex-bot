from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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


class Position:
    ticket = 11


class FakeMT5Executor:
    def __init__(self):
        self.connected = False
        self.paused = False
        self.resumed = False
        self.emergency_called = False
        self.calls = []
        self.tick_age_seconds = 0.0
        self.bid = 1.10000
        self.ask = 1.10002

    def connect(self):
        self.connected = True
        return True

    def recover_positions(self):
        return [Position()]

    def place_market_order(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs

    def symbol_info(self, symbol):
        return SimpleNamespace(point=0.00001)

    def symbol_tick(self, symbol):
        timestamp = datetime.now(timezone.utc).timestamp() - self.tick_age_seconds
        return SimpleNamespace(bid=self.bid, ask=self.ask, time=timestamp, time_msc=0)

    def pause(self):
        self.paused = True

    def resume(self):
        self.resumed = True

    def emergency_stop(self):
        self.emergency_called = True
        return ["closed"]

    def positions(self, managed_only=True):
        return [Position()]

    def account_snapshot(self):
        return "account"

    def closed_position_results(self, start_time, end_time):
        return [(start_time, end_time)]

    def position_side(self, position):
        return "BUY"

    def remaining_loss_at_stop(self, position):
        return 12.5

    def shutdown(self):
        self.connected = False


class FakePositionManager:
    def __init__(self):
        self.recovered = False
        self.registered = []
        self.management_calls = []

    def recover_positions(self, reset_registry=False):
        self.recovered = reset_registry
        return [Position()]

    def register_execution_result(self, result):
        self.registered.append(result)

    def manage_positions(self, atr_by_symbol, force_sync=False):
        self.management_calls.append((atr_by_symbol, force_sync))
        return {"managed": True, "reports": [], "errors": []}


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
    positions = FakePositionManager()
    router = ExecutionRouter(
        paper_trader=paper,
        mode="MT5_DEMO",
        mt5_executor=mt5,
        position_manager=positions,
    )
    recovered = router.start()
    result = router.execute(
        "EURUSD=X", "BUY", RISK_PLAN, 99.0, approved_risk_amount=10.0
    )
    assert mt5.connected is True
    assert recovered[0].ticket == 11
    assert result["symbol"] == "EURUSD"
    assert result["volume"] is None
    assert result["stop_loss"] == 1.0950
    assert result["reference_entry"] == 1.1000
    assert result["risk_amount"] == 10.0
    assert paper.open_trades == []
    assert positions.recovered is True
    assert positions.registered == [result]


def test_stale_mt5_tick_is_rejected_before_order_send():
    mt5 = FakeMT5Executor()
    mt5.tick_age_seconds = 120
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(), mode="MT5_DEMO", mt5_executor=mt5
    )
    with pytest.raises(ExecutionError, match="Stale MT5 tick"):
        router.execute(
            "EURUSD=X", "BUY", RISK_PLAN, 1.0, approved_risk_amount=10.0
        )
    assert mt5.calls == []


def test_excessive_spread_relative_to_stop_is_rejected():
    mt5 = FakeMT5Executor()
    mt5.ask = 1.10200
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(), mode="MT5_DEMO", mt5_executor=mt5
    )
    with pytest.raises(ExecutionError, match="Spread too wide"):
        router.execute(
            "EURUSD=X", "BUY", RISK_PLAN, 1.0, approved_risk_amount=10.0
        )
    assert mt5.calls == []


def test_live_mode_is_locked():
    with pytest.raises(ExecutionError, match="locked"):
        ExecutionRouter(paper_trader=FakePaperTrader(), mode="MT5_LIVE")


def test_unknown_mt5_symbol_is_rejected():
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(), mode="MT5_DEMO", mt5_executor=FakeMT5Executor()
    )
    with pytest.raises(ExecutionError, match="No MT5 symbol mapping"):
        router.execute("UNKNOWN-USD", "BUY", RISK_PLAN, 1.0)


def test_mt5_demo_requires_portfolio_approved_risk_amount():
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(), mode="MT5_DEMO", mt5_executor=FakeMT5Executor()
    )
    with pytest.raises(ExecutionError, match="portfolio-approved risk amount"):
        router.execute("EURUSD=X", "BUY", RISK_PLAN, 1.0)


def test_pause_resume_and_emergency_are_forwarded():
    mt5 = FakeMT5Executor()
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(), mode="MT5_DEMO", mt5_executor=mt5
    )
    router.pause()
    router.resume()
    result = router.emergency_stop()
    assert mt5.paused is True
    assert mt5.resumed is True
    assert mt5.emergency_called is True
    assert result == ["closed"]


def test_management_cycle_maps_data_symbols_to_broker_symbols():
    positions = FakePositionManager()
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(),
        mode="MT5_DEMO",
        mt5_executor=FakeMT5Executor(),
        position_manager=positions,
    )
    result = router.manage_positions({"EURUSD=X": 0.0012, "GC=F": 2.5})
    assert result["managed"] is True
    assert positions.management_calls == [
        ({"EURUSD": 0.0012, "XAUUSD": 2.5}, False)
    ]


def test_paper_management_cycle_is_an_explicit_noop():
    router = ExecutionRouter(paper_trader=FakePaperTrader(), mode="PAPER")
    result = router.manage_positions({"EURUSD=X": 0.0012})
    assert result["managed"] is False
    assert result["errors"] == []


def test_mt5_account_and_history_state_are_forwarded():
    mt5 = FakeMT5Executor()
    router = ExecutionRouter(
        paper_trader=FakePaperTrader(), mode="MT5_DEMO", mt5_executor=mt5
    )
    now = datetime.now(timezone.utc)
    assert router.account_snapshot() == "account"
    assert router.closed_position_results(
        now - timedelta(days=1), now
    ) == [(now - timedelta(days=1), now)]
    assert router.position_side(Position()) == "BUY"
    assert router.remaining_loss_at_stop(Position()) == 12.5
