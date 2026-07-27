"""Deterministic premium, discount, and pullback-zone calculations."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ZoneState:
    range_low: float | None
    range_high: float | None
    equilibrium: float | None
    bullish_pullback_low: float | None
    bullish_pullback_high: float | None
    bearish_pullback_low: float | None
    bearish_pullback_high: float | None
    location: str

    def valid_for_direction(self, direction):
        return (
            direction == "BUY"
            and self.location == "BULLISH_PULLBACK"
        ) or (
            direction == "SELL"
            and self.location == "BEARISH_PULLBACK"
        )

    def to_dict(self):
        return {
            "range_low": self.range_low,
            "range_high": self.range_high,
            "equilibrium": self.equilibrium,
            "bullish_pullback_low": self.bullish_pullback_low,
            "bullish_pullback_high": self.bullish_pullback_high,
            "bearish_pullback_low": self.bearish_pullback_low,
            "bearish_pullback_high": self.bearish_pullback_high,
            "location": self.location
        }


def unavailable_zones():
    return ZoneState(
        range_low=None,
        range_high=None,
        equilibrium=None,
        bullish_pullback_low=None,
        bullish_pullback_high=None,
        bearish_pullback_low=None,
        bearish_pullback_high=None,
        location="UNAVAILABLE"
    )


def calculate_zones(protected_high, protected_low, price):
    if protected_high is None or protected_low is None:
        return unavailable_zones()

    high = float(protected_high)
    low = float(protected_low)
    current_price = float(price)

    if not all(isfinite(value) for value in (high, low, current_price)):
        raise ValueError("Zone inputs must be finite")

    if high <= low:
        raise ValueError(
            "Protected swing high must be above protected swing low"
        )

    price_range = high - low
    equilibrium = low + (price_range * 0.5)
    bullish_pullback_low = low + (price_range * 0.382)
    bullish_pullback_high = equilibrium
    bearish_pullback_low = equilibrium
    bearish_pullback_high = low + (price_range * 0.618)

    if current_price == equilibrium:
        location = "EQUILIBRIUM"
    elif (
        bullish_pullback_low
        <= current_price
        < bullish_pullback_high
    ):
        location = "BULLISH_PULLBACK"
    elif (
        bearish_pullback_low
        < current_price
        <= bearish_pullback_high
    ):
        location = "BEARISH_PULLBACK"
    elif current_price < equilibrium:
        location = "DISCOUNT"
    else:
        location = "PREMIUM"

    return ZoneState(
        range_low=low,
        range_high=high,
        equilibrium=equilibrium,
        bullish_pullback_low=bullish_pullback_low,
        bullish_pullback_high=bullish_pullback_high,
        bearish_pullback_low=bearish_pullback_low,
        bearish_pullback_high=bearish_pullback_high,
        location=location
    )
