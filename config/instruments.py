"""Explicit baseline instrument economics.

These are conservative research defaults, not broker quotes. Live adapters
must replace them with account- and venue-specific contract metadata.
"""

from risk.instrument import InstrumentSpec


def _forex(symbol, *, jpy=False):
    return InstrumentSpec(
        symbol=symbol,
        tick_size=0.001 if jpy else 0.00001,
        contract_multiplier=100_000.0,
        quantity_step=0.01,
        minimum_quantity=0.01,
        maximum_quantity=100.0,
        spread=0.01 if jpy else 0.00010,
        slippage=0.002 if jpy else 0.00002,
        commission_per_quantity=3.50,
    )


INSTRUMENTS = {
    symbol: _forex(symbol)
    for symbol in (
        "EURUSD=X",
        "GBPUSD=X",
        "AUDUSD=X",
        "USDCAD=X",
        "USDCHF=X",
        "NZDUSD=X",
        "CAD=X",
    )
}
INSTRUMENTS.update({
    "USDJPY=X": _forex("USDJPY=X", jpy=True),
    "JPY=X": _forex("JPY=X", jpy=True),
    "GC=F": InstrumentSpec(
        symbol="GC=F",
        tick_size=0.10,
        contract_multiplier=100.0,
        quantity_step=1.0,
        minimum_quantity=1.0,
        maximum_quantity=25.0,
        spread=0.10,
        slippage=0.10,
        commission_per_quantity=2.50,
    ),
    "SI=F": InstrumentSpec(
        symbol="SI=F",
        tick_size=0.005,
        contract_multiplier=5_000.0,
        quantity_step=1.0,
        minimum_quantity=1.0,
        maximum_quantity=25.0,
        spread=0.01,
        slippage=0.005,
        commission_per_quantity=2.50,
    ),
    "BTC-USD": InstrumentSpec(
        symbol="BTC-USD",
        tick_size=0.01,
        contract_multiplier=1.0,
        quantity_step=0.0001,
        minimum_quantity=0.0001,
        maximum_quantity=100.0,
        spread=2.00,
        slippage=0.50,
        commission_per_quantity=1.00,
    ),
    "ETH-USD": InstrumentSpec(
        symbol="ETH-USD",
        tick_size=0.01,
        contract_multiplier=1.0,
        quantity_step=0.001,
        minimum_quantity=0.001,
        maximum_quantity=1_000.0,
        spread=0.20,
        slippage=0.05,
        commission_per_quantity=0.10,
    ),
    "SOL-USD": InstrumentSpec(
        symbol="SOL-USD",
        tick_size=0.001,
        contract_multiplier=1.0,
        quantity_step=0.01,
        minimum_quantity=0.01,
        maximum_quantity=10_000.0,
        spread=0.02,
        slippage=0.005,
        commission_per_quantity=0.01,
    ),
})


def get_instrument_spec(symbol):
    """Return explicit economics, failing closed for unknown instruments."""

    normalized = str(symbol).strip().upper()
    try:
        return INSTRUMENTS[normalized]
    except KeyError as exc:
        raise KeyError(
            f"No instrument specification configured for {normalized!r}"
        ) from exc
