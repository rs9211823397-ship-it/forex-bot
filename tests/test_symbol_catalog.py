from config.instruments import get_instrument_spec
from config.settings import MT5_SYMBOL_MAP, SYMBOLS
from config.symbols import SYMBOL_CATALOG, active_symbols, symbol_by_broker


REQUESTED_BROKER_SYMBOLS = {
    "BTCUSD", "ETHUSD", "BTCUSDT", "ETHBTC", "BTCJPY", "BTCKRW",
    "BTCAUD", "BTCCNH", "BTCTHB", "BTCZAR", "BTCXAU", "BTCXAG",
    "XAUUSD", "XAUEUR", "XAUGBP", "XAUAUD", "XAGUSD", "XAGEUR",
    "XAGGBP", "XAGAUD", "XPTUSD", "XPDUSD", "EURUSD", "GBPUSD",
    "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
}


def test_every_requested_symbol_is_in_the_authoritative_catalog():
    configured = {item.broker_symbol for item in SYMBOL_CATALOG}

    assert REQUESTED_BROKER_SYMBOLS <= configured


def test_catalog_symbols_are_unique_and_disabled_entries_are_explained():
    broker_symbols = [item.broker_symbol for item in SYMBOL_CATALOG]
    data_symbols = [item.data_symbol for item in SYMBOL_CATALOG if item.data_symbol]

    assert len(broker_symbols) == len(set(broker_symbols))
    assert len(data_symbols) == len(set(data_symbols))
    assert all(
        item.enabled_by_default or item.disabled_reason
        for item in SYMBOL_CATALOG
    )


def test_current_exness_close_only_crosses_cannot_generate_new_entries():
    close_only = {
        "BTCAUD", "BTCCNH", "BTCTHB", "BTCZAR", "BTCXAU", "BTCXAG"
    }

    assert all(
        symbol_by_broker(symbol).entry_policy == "CLOSE_ONLY"
        for symbol in close_only
    )
    assert close_only.isdisjoint(MT5_SYMBOL_MAP.values())


def test_btckrw_is_catalogued_but_fails_closed_for_exness():
    definition = symbol_by_broker("BTCKRW")

    assert definition.entry_policy == "UNAVAILABLE"
    assert definition.enabled_by_default is False


def test_active_symbols_have_cost_aware_specs_and_safe_mt5_mappings():
    active = [symbol for symbols in SYMBOLS.values() for symbol in symbols]

    for symbol in active:
        get_instrument_spec(symbol)
        if symbol != "SOL-USD":
            assert symbol in MT5_SYMBOL_MAP


def test_yahoo_short_forex_tickers_map_to_the_correct_mt5_symbols():
    assert MT5_SYMBOL_MAP["JPY=X"] == "USDJPY"
    assert MT5_SYMBOL_MAP["CHF=X"] == "USDCHF"
    assert MT5_SYMBOL_MAP["CAD=X"] == "USDCAD"


def test_usdt_exposure_is_not_misclassified_as_usd():
    definition = symbol_by_broker("BTCUSDT")

    assert (definition.base_asset, definition.quote_asset) == ("BTC", "USDT")
    assert definition.enabled_by_default is False
    assert definition.data_symbol is None


def test_mt5_scan_excludes_paper_only_solusd():
    mt5_symbols = active_symbols(include_paper_only=False)

    assert "SOL-USD" not in mt5_symbols["crypto"]
