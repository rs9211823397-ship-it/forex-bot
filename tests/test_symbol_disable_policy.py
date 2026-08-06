import pytest

from config.symbol_policy import (
    DEFAULT_DISABLED_BROKER_SYMBOLS,
    filter_active_symbols,
    filter_executable_map,
    parse_disabled_broker_symbols,
)
from config.symbols import active_symbols, executable_symbol_map


def test_default_disabled_symbols_are_high_minimum_risk_metals():
    assert set(DEFAULT_DISABLED_BROKER_SYMBOLS) == {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"}


def test_default_policy_removes_metals_from_analysis_and_execution():
    disabled = parse_disabled_broker_symbols(None)
    grouped = filter_active_symbols(active_symbols(include_paper_only=False), disabled)
    mapping = filter_executable_map(executable_symbol_map(), disabled)
    active = {symbol for symbols in grouped.values() for symbol in symbols}
    for source in {"GC=F", "SI=F", "PL=F", "PA=F"}:
        assert source not in active and source not in mapping
    assert sum(len(symbols) for symbols in grouped.values()) == 9
    assert len(mapping) == 9


def test_empty_override_reenables_catalog_defaults():
    disabled = parse_disabled_broker_symbols("")
    grouped = filter_active_symbols(active_symbols(include_paper_only=False), disabled)
    mapping = filter_executable_map(executable_symbol_map(), disabled)
    assert disabled == ()
    assert "GC=F" in grouped["metals"]
    assert "XAUUSD" in mapping.values()
    assert sum(len(symbols) for symbols in grouped.values()) == 13
    assert len(mapping) == 13


def test_override_is_normalized_and_unknown_symbols_fail_closed():
    assert parse_disabled_broker_symbols(" xauusd, btcusd, XAUUSD ") == ("BTCUSD", "XAUUSD")
    with pytest.raises(KeyError, match="Unknown broker symbol"):
        parse_disabled_broker_symbols("NOT_A_SYMBOL")
