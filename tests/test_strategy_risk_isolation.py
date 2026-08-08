from datetime import datetime, timezone
from types import SimpleNamespace

from execution.execution_router import ExecutionRouter
from execution.mt5_executor import AccountSnapshot, ClosedPositionResult


class DummyPaper:
    balance = 100.0
    equity = 100.0
    open_trades = []


class DummyManager:
    def recover_positions(self, reset_registry=False):
        return []


class FakeExecutor:
    def __init__(self):
        self.balance = 100.0
        self.equity = 100.0
        self.managed_positions = []
        self.connected = False

    def connect(self):
        self.connected = True
        return True

    def account_snapshot(self):
        return AccountSnapshot(balance=self.balance, equity=self.equity)

    def positions(self, symbol=None, managed_only=True):
        assert managed_only is True
        return list(self.managed_positions)


class FakeAudit:
    def __init__(self):
        self.results = []

    def sync_closed(self):
        return []

    def closed_position_results(self, start_time, end_time):
        assert start_time.tzinfo is not None
        assert end_time.tzinfo is not None
        return list(self.results)


def test_demo_risk_equity_ignores_other_ea_account_pnl(monkeypatch):
    monkeypatch.delenv("AAQTS_ISOLATE_STRATEGY_RISK", raising=False)
    executor = FakeExecutor()
    audit = FakeAudit()
    router = ExecutionRouter(
        DummyPaper(),
        mode="MT5_DEMO",
        mt5_executor=executor,
        position_manager=DummyManager(),
        trade_audit=audit,
    )

    router.start()

    # Another EA changes the broker account from 100 to 125 after AAQTS starts.
    executor.balance = 125.0
    executor.equity = 126.0

    # AAQTS itself has +2 realized and +1 floating PnL.
    audit.results = [
        ClosedPositionResult(
            closed_at=datetime.now(timezone.utc),
            profit_loss=2.0,
        )
    ]
    executor.managed_positions = [SimpleNamespace(profit=1.0, swap=0.0)]

    snapshot = router.account_snapshot()

    assert snapshot.balance == 102.0
    assert snapshot.equity == 103.0


def test_demo_risk_isolation_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AAQTS_ISOLATE_STRATEGY_RISK", "false")
    executor = FakeExecutor()
    router = ExecutionRouter(
        DummyPaper(),
        mode="MT5_DEMO",
        mt5_executor=executor,
        position_manager=DummyManager(),
        trade_audit=FakeAudit(),
    )

    router.start()
    executor.balance = 125.0
    executor.equity = 126.0

    snapshot = router.account_snapshot()

    assert snapshot.balance == 125.0
    assert snapshot.equity == 126.0


def test_demo_positions_remain_magic_managed_only(monkeypatch):
    monkeypatch.delenv("AAQTS_ISOLATE_STRATEGY_RISK", raising=False)
    executor = FakeExecutor()
    executor.managed_positions = [SimpleNamespace(ticket=1)]
    router = ExecutionRouter(
        DummyPaper(),
        mode="MT5_DEMO",
        mt5_executor=executor,
        position_manager=DummyManager(),
        trade_audit=FakeAudit(),
    )

    assert [position.ticket for position in router.positions()] == [1]
