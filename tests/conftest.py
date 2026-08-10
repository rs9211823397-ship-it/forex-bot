import pytest


@pytest.fixture(autouse=True)
def _isolate_local_trading_environment(monkeypatch):
    """Keep unit/research tests independent from an operator's local .env.

    Production/demo tests explicitly set the mode they need.  The default test
    process stays in PAPER/YAHOO mode with news and strategy-risk isolation
    disabled so a developer's MT5_DEMO credentials, suffix, or live calendar
    availability cannot change unrelated deterministic tests.
    """

    monkeypatch.setenv("AAQTS_EXECUTION_MODE", "PAPER")
    monkeypatch.setenv("AAQTS_MARKET_DATA_PROVIDER", "YAHOO")
    monkeypatch.setenv("AAQTS_NEWS_FILTER_ENABLED", "false")
    monkeypatch.setenv("AAQTS_ISOLATE_STRATEGY_RISK", "false")
