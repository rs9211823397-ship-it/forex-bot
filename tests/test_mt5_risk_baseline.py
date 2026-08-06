from datetime import datetime, timedelta, timezone

import execution.mt5_trade_audit as audit_module
from execution.mt5_trade_audit import MT5TradeAudit


def test_risk_baseline_clamps_realized_history(monkeypatch):
    baseline = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(audit_module, "MT5_RISK_BASELINE_UTC", baseline)

    start = baseline - timedelta(days=8)
    end = baseline + timedelta(hours=1)

    assert MT5TradeAudit._apply_risk_baseline(start, end) == (baseline, end)


def test_risk_baseline_excludes_windows_before_epoch(monkeypatch):
    baseline = datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(audit_module, "MT5_RISK_BASELINE_UTC", baseline)

    start = baseline - timedelta(days=8)
    end = baseline - timedelta(seconds=1)

    assert MT5TradeAudit._apply_risk_baseline(start, end) is None


def test_no_baseline_preserves_full_history_window(monkeypatch):
    monkeypatch.setattr(audit_module, "MT5_RISK_BASELINE_UTC", None)
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 6, tzinfo=timezone.utc)

    assert MT5TradeAudit._apply_risk_baseline(start, end) == (start, end)
