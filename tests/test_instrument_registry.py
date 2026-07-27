import pytest

from config.instruments import get_instrument_spec
from strategy.signal_engine import SignalEngine


@pytest.mark.parametrize(
    "symbol",
    (
        "EURUSD=X",
        "JPY=X",
        "GC=F",
        "SI=F",
        "BTC-USD",
        "ETH-USD",
    ),
)
def test_supported_assets_have_cost_aware_instrument_specs(symbol):
    instrument = get_instrument_spec(symbol)

    assert instrument.symbol == symbol
    assert instrument.tick_size > 0
    assert instrument.contract_multiplier > 0
    assert instrument.quantity_step > 0
    assert instrument.spread > 0
    assert instrument.slippage > 0


def test_unknown_instrument_fails_closed():
    with pytest.raises(KeyError, match="No instrument specification"):
        get_instrument_spec("UNKNOWN")


def test_production_signal_engine_uses_strict_timeframe_roles():
    engine = SignalEngine.production("1d", "1h")

    assert engine.mtf.higher_timeframe == "1d"
    assert engine.mtf.lower_timeframe == "1h"
    assert engine.mtf.allow_untimed_legacy is False


def test_production_signal_engine_rejects_inverted_roles():
    with pytest.raises(
        ValueError,
        match="higher timeframe",
    ):
        SignalEngine.production("1h", "1d")
