from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import execution.mt5_trade_audit as audit_module
from execution.mt5_trade_audit import MT5TradeAudit


@pytest.fixture(autouse=True)
def isolate_local_risk_baseline(monkeypatch):
    """Unit fixtures must not inherit the operator's local demo risk epoch."""
    monkeypatch.setattr(audit_module, "MT5_RISK_BASELINE_UTC", None)


class FakeMT5:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3
    DEAL_REASON_CLIENT = 0
    DEAL_REASON_MOBILE = 1
    DEAL_REASON_WEB = 2
    DEAL_REASON_EXPERT = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5
    DEAL_REASON_SO = 6

    def __init__(self, deals):
        self.deals = deals

    def history_deals_get(self, start, end):
        return tuple(
            deal
            for deal in self.deals
            if start.timestamp() <= deal.time <= end.timestamp()
        )

    @staticmethod
    def last_error():
        return (0, "OK")


class FakeExecutor:
    def __init__(self, deals):
        self.mt5 = FakeMT5(deals)
        self.config = SimpleNamespace(magic=20260730)

    @staticmethod
    def _as_utc(value, _field):
        return value.astimezone(timezone.utc)


def deal(*, ticket, position, entry, magic, reason, profit, symbol="USDJPYm"):
    return SimpleNamespace(
        ticket=ticket,
        position_id=position,
        entry=entry,
        magic=magic,
        reason=reason,
        profit=profit,
        swap=0.0,
        commission=0.0,
        fee=0.0,
        symbol=symbol,
        volume=0.06,
        price=157.66,
        comment="",
        time=datetime(2026, 8, 5, 20, 0, tzinfo=timezone.utc).timestamp(),
    )


def test_manual_mobile_exit_is_attributed_to_aaqts_opening_position(tmp_path):
    position_id = 3580141624
    opening = deal(
        ticket=1,
        position=position_id,
        entry=FakeMT5.DEAL_ENTRY_IN,
        magic=20260730,
        reason=FakeMT5.DEAL_REASON_EXPERT,
        profit=0.0,
    )
    closing = deal(
        ticket=2,
        position=position_id,
        entry=FakeMT5.DEAL_ENTRY_OUT,
        magic=0,
        reason=FakeMT5.DEAL_REASON_MOBILE,
        profit=-13.02,
    )
    unrelated = deal(
        ticket=3,
        position=999,
        entry=FakeMT5.DEAL_ENTRY_OUT,
        magic=0,
        reason=FakeMT5.DEAL_REASON_MOBILE,
        profit=-4.41,
    )
    audit = MT5TradeAudit(
        FakeExecutor([opening, closing, unrelated]),
        tmp_path / "audit.csv",
    )

    end = datetime(2026, 8, 5, 21, 0, tzinfo=timezone.utc)
    results = audit.managed_closed_deals(end - timedelta(days=1), end)

    assert len(results) == 1
    assert results[0].position_id == position_id
    assert results[0].profit_loss == -13.02
    assert results[0].exit_reason == "MANUAL_MOBILE"


def test_stop_loss_exit_classification(tmp_path):
    position_id = 42
    opening = deal(
        ticket=10,
        position=position_id,
        entry=FakeMT5.DEAL_ENTRY_IN,
        magic=20260730,
        reason=FakeMT5.DEAL_REASON_EXPERT,
        profit=0.0,
    )
    closing = deal(
        ticket=11,
        position=position_id,
        entry=FakeMT5.DEAL_ENTRY_OUT,
        magic=0,
        reason=FakeMT5.DEAL_REASON_SL,
        profit=-1.0,
    )
    audit = MT5TradeAudit(
        FakeExecutor([opening, closing]),
        tmp_path / "audit.csv",
    )

    end = datetime(2026, 8, 5, 21, 0, tzinfo=timezone.utc)
    results = audit.managed_closed_deals(end - timedelta(days=1), end)

    assert results[0].exit_reason == "STOP_LOSS"
