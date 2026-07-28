from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Dict


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    tick_size: float
    tick_value: float
    min_lot: float
    max_lot: float
    lot_step: float

    def normalize_lot(self, lots: float) -> float:
        if lots <= 0:
            return 0.0

        bounded = min(max(lots, self.min_lot), self.max_lot)
        step = Decimal(str(self.lot_step))
        normalized = (
            Decimal(str(bounded)) / step
        ).to_integral_value(rounding=ROUND_DOWN) * step
        return float(normalized)

    def pnl(self, side: str, entry: float, exit_price: float, lots: float) -> float:
        direction = 1 if side == "BUY" else -1
        ticks = ((exit_price - entry) * direction) / self.tick_size
        return ticks * self.tick_value * lots


INSTRUMENT_SPECS: Dict[str, InstrumentSpec] = {
    "EURUSD=X": InstrumentSpec("EURUSD=X", 0.00001, 1.0, 0.01, 100.0, 0.01),
    "GBPUSD=X": InstrumentSpec("GBPUSD=X", 0.00001, 1.0, 0.01, 100.0, 0.01),
    "AUDUSD=X": InstrumentSpec("AUDUSD=X", 0.00001, 1.0, 0.01, 100.0, 0.01),
    "JPY=X": InstrumentSpec("JPY=X", 0.0001, 10.0, 0.01, 100.0, 0.01),
    "CAD=X": InstrumentSpec("CAD=X", 0.0001, 10.0, 0.01, 100.0, 0.01),
    "GC=F": InstrumentSpec("GC=F", 0.1, 10.0, 0.01, 100.0, 0.01),
    "SI=F": InstrumentSpec("SI=F", 0.005, 25.0, 0.01, 100.0, 0.01),
    "BTC-USD": InstrumentSpec("BTC-USD", 0.01, 0.01, 0.001, 100.0, 0.001),
    "ETH-USD": InstrumentSpec("ETH-USD", 0.01, 0.01, 0.001, 1000.0, 0.001),
    "SOL-USD": InstrumentSpec("SOL-USD", 0.001, 0.001, 0.01, 10000.0, 0.01),
}


def get_instrument_spec(symbol: str) -> InstrumentSpec:
    try:
        return INSTRUMENT_SPECS[symbol]
    except KeyError as exc:
        raise ValueError(f"No instrument specification configured for {symbol}") from exc
