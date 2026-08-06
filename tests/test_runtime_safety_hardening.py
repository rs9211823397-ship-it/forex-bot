from types import SimpleNamespace

import pytest

from execution.mt5_executor import ExecutionConfig, ExecutionError, MT5Executor


def test_execution_config_rejects_invalid_tick_age():
    with pytest.raises(ValueError):
        ExecutionConfig(max_tick_age_seconds=0)


def test_execution_config_rejects_invalid_spread_ratio():
    with pytest.raises(ValueError):
        ExecutionConfig(max_spread_stop_ratio=1.1)


def test_tick_guard_rejects_stale_quote(monkeypatch):
    executor = MT5Executor(ExecutionConfig(max_tick_age_seconds=5.0), adapter=SimpleNamespace())
    monkeypatch.setattr("execution.mt5_executor.datetime", SimpleNamespace(
        now=lambda tz: SimpleNamespace(timestamp=lambda: 100.0)
    ))
    tick = SimpleNamespace(bid=1.1000, ask=1.1002, time=90.0, time_msc=0)
    with pytest.raises(ExecutionError, match="stale"):
        executor._validate_tick_and_spread(tick, 1.1002, 1.0950)


def test_tick_guard_rejects_excessive_spread(monkeypatch):
    executor = MT5Executor(ExecutionConfig(max_tick_age_seconds=15.0, max_spread_stop_ratio=0.25), adapter=SimpleNamespace())
    monkeypatch.setattr("execution.mt5_executor.datetime", SimpleNamespace(
        now=lambda tz: SimpleNamespace(timestamp=lambda: 100.0)
    ))
    tick = SimpleNamespace(bid=1.1000, ask=1.1010, time=99.0, time_msc=0)
    with pytest.raises(ExecutionError, match="Spread is too large"):
        executor._validate_tick_and_spread(tick, 1.1010, 1.0980)
