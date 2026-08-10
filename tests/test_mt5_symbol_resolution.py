from types import SimpleNamespace

import pytest

from data.market_data import MarketData, MarketDataError


class FakeMT5:
    def __init__(self, names):
        self.names = tuple(names)
        self.symbol_info_calls = []
        self.symbols_get_calls = 0

    def symbol_info(self, name):
        self.symbol_info_calls.append(name)
        if name in self.names:
            return SimpleNamespace(name=name, visible=True)
        return None

    def symbols_get(self):
        self.symbols_get_calls += 1
        return tuple(SimpleNamespace(name=name) for name in self.names)


def _market():
    return MarketData(
        execution_mode="PAPER",
        provider="YAHOO",
        cache_downloads=False,
    )


def test_exact_configured_symbol_is_preferred():
    market = _market()
    mt5 = FakeMT5(["EURUSD", "EURUSDm"])

    assert market._resolve_mt5_symbol(mt5, "EURUSD=X", "EURUSD") == "EURUSD"
    assert mt5.symbols_get_calls == 0


def test_unique_broker_suffix_is_resolved_automatically():
    market = _market()
    mt5 = FakeMT5(["EURUSDm", "GBPUSDm"])

    assert market._resolve_mt5_symbol(mt5, "EURUSD=X", "EURUSD") == "EURUSDm"
    assert market._resolved_mt5_symbols["EURUSD=X"] == "EURUSDm"


def test_resolved_symbol_is_cached_for_future_reads():
    market = _market()
    mt5 = FakeMT5(["EURUSDm"])

    assert market._resolve_mt5_symbol(mt5, "EURUSD=X", "EURUSD") == "EURUSDm"
    assert mt5.symbols_get_calls == 1
    assert market._resolve_mt5_symbol(mt5, "EURUSD=X", "EURUSD") == "EURUSDm"
    assert mt5.symbols_get_calls == 1


def test_ambiguous_broker_suffixes_fail_closed():
    market = _market()
    mt5 = FakeMT5(["EURUSDm", "EURUSDc"])

    with pytest.raises(MarketDataError, match="Ambiguous MT5 symbol mapping"):
        market._resolve_mt5_symbol(mt5, "EURUSD=X", "EURUSD")


def test_missing_broker_symbol_fails_closed():
    market = _market()
    mt5 = FakeMT5(["GBPUSDm"])

    with pytest.raises(MarketDataError, match="no broker symbol matches EURUSD"):
        market._resolve_mt5_symbol(mt5, "EURUSD=X", "EURUSD")
