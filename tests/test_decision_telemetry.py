from collections import Counter
from datetime import datetime, timezone
import threading

import pytest

from execution.mt5_executor import ClosedPositionResult
from main import TradingApplication


def _application():
    app = TradingApplication.__new__(TradingApplication)
    app._cycle_stages = Counter()
    app._session_stages = Counter()
    app._cycle_reasons = Counter()
    app._session_reasons = Counter()
    app._telemetry_lock = threading.RLock()
    return app


def test_decision_telemetry_separates_strategy_risk_and_execution_stages():
    app = _application()

    app._record_decision_stage("STRATEGY_HOLD", "No directional setup")
    app._record_decision_stage("STRATEGY_ACTIONABLE", "BUY")
    app._record_decision_stage(
        "PORTFOLIO_RISK_BLOCKED",
        ("EQUITY_DRAWDOWN_LIMIT", "MAX_OPEN_TRADES"),
    )

    telemetry = app._decision_telemetry()
    assert telemetry["cycle_stages"] == {
        "STRATEGY_HOLD": 1,
        "STRATEGY_ACTIONABLE": 1,
        "PORTFOLIO_RISK_BLOCKED": 1,
    }
    assert telemetry["cycle_reasons"][
        "PORTFOLIO_RISK_BLOCKED:EQUITY_DRAWDOWN_LIMIT"
    ] == 1


def test_broker_closed_trade_statistics_report_real_wins_and_losses():
    now = datetime.now(timezone.utc)
    stats = TradingApplication._closed_trade_stats(
        (
            ClosedPositionResult(now, 2.0),
            ClosedPositionResult(now, -1.0),
            ClosedPositionResult(now, 0.0),
        )
    )

    assert stats["closed_trades"] == 3
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["win_rate"] == pytest.approx(100.0 / 3.0)
