from datetime import datetime, timezone
from types import SimpleNamespace

import main as main_module
from execution.mt5_executor import AccountSnapshot
from main import TradingApplication


def _application(previous, *, mode="MT5_DEMO"):
    app = TradingApplication.__new__(TradingApplication)
    app.account_id = "exness_demo"
    app.execution = SimpleNamespace(mode=mode)
    app.equity_history = []
    app._previous_runtime_state = dict(previous)
    app._risk_state_identity = ""
    return app


def _snapshot(equity=96.69, *, login=416083595, server="Exness-MT5Trial14"):
    return AccountSnapshot(
        balance=equity,
        equity=equity,
        login=login,
        server=server,
        trade_mode=0,
    )


def test_identityless_legacy_peak_is_not_applied_to_current_broker_account(monkeypatch):
    monkeypatch.setattr(main_module, "MT5_RISK_BASELINE_UTC", None)
    app = _application({"equity_peak": 1000.0})

    app._initialize_equity_state(_snapshot(), datetime.now(timezone.utc))

    assert app.equity_history[0].equity == 96.69
    assert "mt5:416083595:exness-mt5trial14" in app._risk_state_identity


def test_matching_identity_restores_real_peak(monkeypatch):
    monkeypatch.setattr(main_module, "MT5_RISK_BASELINE_UTC", None)
    seed = _application({})
    identity = seed._runtime_risk_identity(_snapshot())
    app = _application({"equity_peak": 105.0, "risk_state_identity": identity})

    app._initialize_equity_state(_snapshot(), datetime.now(timezone.utc))

    assert app.equity_history[0].equity == 105.0


def test_different_login_or_baseline_cannot_inherit_peak(monkeypatch):
    monkeypatch.setattr(main_module, "MT5_RISK_BASELINE_UTC", None)
    seed = _application({})
    old_identity = seed._runtime_risk_identity(_snapshot(login=111))
    app = _application({"equity_peak": 1000.0, "risk_state_identity": old_identity})

    app._initialize_equity_state(_snapshot(login=222), datetime.now(timezone.utc))

    assert app.equity_history[0].equity == 96.69


def test_isolated_account_snapshot_preserves_broker_identity():
    snapshot = AccountSnapshot(
        balance=100.0,
        equity=99.0,
        login=123456,
        server="Broker-Demo",
        trade_mode=0,
    )

    assert snapshot.login == 123456
    assert snapshot.server == "Broker-Demo"
    assert snapshot.trade_mode == 0
