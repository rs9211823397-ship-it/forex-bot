from datetime import datetime, timezone
from types import SimpleNamespace

from execution.mt5_executor import AccountSnapshot, ClosedPositionResult
from main import TradingApplication


class FakeDemoExecution:
    mode = "MT5_DEMO"

    def account_snapshot(self):
        return AccountSnapshot(balance=10_000.0, equity=9_900.0)

    def positions(self):
        return [
            SimpleNamespace(
                symbol="EURUSD",
                type=0,
                time=1_700_000_000,
                volume=0.05,
            )
        ]

    def position_side(self, position):
        return "BUY"

    def remaining_loss_at_stop(self, position):
        return 75.0

    def closed_position_results(self, start_time, end_time):
        return [
            ClosedPositionResult(
                closed_at=end_time,
                profit_loss=-25.0,
            )
        ]


def test_demo_risk_context_uses_broker_positions_and_realized_results():
    app = TradingApplication.__new__(TradingApplication)
    app.execution = FakeDemoExecution()
    app.equity_history = []
    app.news_provider = None
    now = datetime.now(timezone.utc)

    context = app._risk_context(now)

    assert len(context.open_positions) == 1
    assert context.open_positions[0].symbol == "EURUSD=X"
    assert context.open_positions[0].risk_amount == 75.0
    assert context.open_positions[0].quantity == 0.05
    assert len(context.closed_trades) == 1
    assert context.closed_trades[0].profit_loss == -25.0
