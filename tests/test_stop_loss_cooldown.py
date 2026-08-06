from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from config.settings import MT5_SYMBOL_MAP
from execution.execution_router import ExecutionError, ExecutionRouter


class StubAudit:
    def __init__(self, deals):
        self.deals = list(deals)
        self.calls = []

    def managed_closed_deals(self, start, end):
        self.calls.append((start, end))
        return list(self.deals)


def _router_with(deals):
    router = object.__new__(ExecutionRouter)
    router.mode = "MT5_DEMO"
    router.trade_audit = StubAudit(deals)
    return router


def _symbol_pair():
    source, broker = next(iter(MT5_SYMBOL_MAP.items()))
    return source, broker


def test_recent_stop_loss_blocks_symbol_reentry(monkeypatch):
    monkeypatch.setenv("AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES", "60")
    source, broker = _symbol_pair()
    deal = SimpleNamespace(
        symbol=broker,
        exit_reason="STOP_LOSS",
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    router = _router_with([deal])

    with pytest.raises(ExecutionError, match="Stop-loss cooldown active"):
        router._enforce_stop_loss_cooldown(source, "SELL")


def test_take_profit_does_not_trigger_stop_loss_cooldown(monkeypatch):
    monkeypatch.setenv("AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES", "60")
    source, broker = _symbol_pair()
    deal = SimpleNamespace(
        symbol=broker,
        exit_reason="TAKE_PROFIT",
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    router = _router_with([deal])

    router._enforce_stop_loss_cooldown(source, "BUY")


def test_other_symbol_stop_does_not_block(monkeypatch):
    monkeypatch.setenv("AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES", "60")
    pairs = list(MT5_SYMBOL_MAP.items())
    if len(pairs) < 2:
        pytest.skip("requires at least two configured MT5 symbols")
    source, _ = pairs[0]
    _, other_broker = pairs[1]
    deal = SimpleNamespace(
        symbol=other_broker,
        exit_reason="STOP_LOSS",
        closed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    router = _router_with([deal])

    router._enforce_stop_loss_cooldown(source, "SELL")


def test_cooldown_can_be_disabled_for_research(monkeypatch):
    monkeypatch.setenv("AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES", "0")
    source, broker = _symbol_pair()
    deal = SimpleNamespace(
        symbol=broker,
        exit_reason="STOP_LOSS",
        closed_at=datetime.now(timezone.utc),
    )
    router = _router_with([deal])

    router._enforce_stop_loss_cooldown(source, "SELL")
    assert router.trade_audit.calls == []
