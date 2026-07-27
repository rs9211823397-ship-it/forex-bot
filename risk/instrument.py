"""Instrument economics used by deterministic backtest accounting."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from math import ceil, floor, isfinite


@dataclass(frozen=True)
class InstrumentSpec:
    """
    Describe how price movement and execution costs convert to cash.

    ``contract_multiplier`` is the cash value of a one-unit price move for one
    unit of position quantity. Costs are expressed in account currency except
    for ``spread`` and ``slippage``, which are price units.
    """

    symbol: str
    tick_size: float
    contract_multiplier: float
    quantity_step: float
    minimum_quantity: float
    maximum_quantity: float | None = None
    spread: float = 0.0
    slippage: float = 0.0
    commission_per_quantity: float = 0.0

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")

        positive = {
            "tick_size": self.tick_size,
            "contract_multiplier": self.contract_multiplier,
            "quantity_step": self.quantity_step,
            "minimum_quantity": self.minimum_quantity
        }

        for name, value in positive.items():
            if not isfinite(float(value)) or float(value) <= 0:
                raise ValueError(
                    f"{name} must be finite and greater than zero"
                )

        non_negative = {
            "spread": self.spread,
            "slippage": self.slippage,
            "commission_per_quantity": (
                self.commission_per_quantity
            )
        }

        for name, value in non_negative.items():
            if not isfinite(float(value)) or float(value) < 0:
                raise ValueError(
                    f"{name} must be finite and non-negative"
                )

        if self.maximum_quantity is not None:
            maximum = float(self.maximum_quantity)

            if not isfinite(maximum) or maximum <= 0:
                raise ValueError(
                    "maximum_quantity must be finite and positive"
                )

            if maximum < float(self.minimum_quantity):
                raise ValueError(
                    "maximum_quantity cannot be below minimum_quantity"
                )

        step = Decimal(str(self.quantity_step))
        minimum = Decimal(str(self.minimum_quantity))

        if minimum % step != 0:
            raise ValueError(
                "minimum_quantity must align with quantity_step"
            )

        if self.maximum_quantity is not None:
            maximum = Decimal(str(self.maximum_quantity))

            if maximum % step != 0:
                raise ValueError(
                    "maximum_quantity must align with quantity_step"
                )

    @classmethod
    def generic(cls, symbol="GENERIC"):
        """Return a zero-cost unit-value specification for compatibility."""

        return cls(
            symbol=symbol,
            tick_size=0.00001,
            contract_multiplier=1.0,
            quantity_step=0.0001,
            minimum_quantity=0.0001
        )

    def normalize_quantity(self, quantity):
        """Round quantity down so risk never exceeds the requested amount."""

        raw_quantity = float(quantity)

        if not isfinite(raw_quantity) or raw_quantity <= 0:
            return 0.0

        step = Decimal(str(self.quantity_step))
        capped_quantity = Decimal(str(raw_quantity))

        if self.maximum_quantity is not None:
            capped_quantity = min(
                capped_quantity,
                Decimal(str(self.maximum_quantity))
            )

        normalized = (
            capped_quantity / step
        ).to_integral_value(rounding=ROUND_FLOOR) * step

        if normalized < Decimal(str(self.minimum_quantity)):
            return 0.0

        return float(normalized)

    def normalize_price(self, price, action):
        """Round a fill price conservatively to the instrument tick."""

        value = float(price)

        if not isfinite(value):
            raise ValueError("Fill price must be finite")

        ticks = value / float(self.tick_size)

        if action == "BUY":
            normalized_ticks = ceil(ticks - 1e-12)
        elif action == "SELL":
            normalized_ticks = floor(ticks + 1e-12)
        else:
            raise ValueError("Fill action must be BUY or SELL")

        return normalized_ticks * float(self.tick_size)

    def entry_fill_price(self, reference_price, side):
        """Apply half-spread and adverse slippage to an entry."""

        reference = float(reference_price)
        half_spread = float(self.spread) / 2.0

        if side == "BUY":
            raw_fill = (
                reference
                + half_spread
                + float(self.slippage)
            )
            action = "BUY"
        elif side == "SELL":
            raw_fill = (
                reference
                - half_spread
                - float(self.slippage)
            )
            action = "SELL"
        else:
            raise ValueError("Entry side must be BUY or SELL")

        return self.normalize_price(raw_fill, action)

    def exit_fill_price(self, reference_price, entry_side):
        """Apply half-spread and adverse slippage to a closing fill."""

        reference = float(reference_price)
        half_spread = float(self.spread) / 2.0

        if entry_side == "BUY":
            raw_fill = (
                reference
                - half_spread
                - float(self.slippage)
            )
            action = "SELL"
        elif entry_side == "SELL":
            raw_fill = (
                reference
                + half_spread
                + float(self.slippage)
            )
            action = "BUY"
        else:
            raise ValueError("Entry side must be BUY or SELL")

        return self.normalize_price(raw_fill, action)

    def cash_value(self, price_difference, quantity):
        """Convert an absolute price move and quantity into account cash."""

        return (
            abs(float(price_difference))
            * float(quantity)
            * float(self.contract_multiplier)
        )

    def spread_cost(self, quantity):
        """Return round-trip spread cost in account currency."""

        return self.cash_value(self.spread, quantity)

    def slippage_cost(self, quantity):
        """Return round-trip slippage cost in account currency."""

        return self.cash_value(
            float(self.slippage) * 2.0,
            quantity
        )

    def commission_cost(self, quantity):
        """Return round-trip commission in account currency."""

        return (
            float(self.commission_per_quantity)
            * float(quantity)
            * 2.0
        )

    def planned_loss_per_quantity(
        self,
        entry_reference,
        stop_reference,
        side
    ):
        """
        Return normal-stop cash loss for one quantity unit.

        The calculation uses the same adverse spread, slippage, tick rounding,
        and round-trip commission policy as recorded backtest fills.
        """

        entry = float(entry_reference)
        stop = float(stop_reference)

        if not all(isfinite(value) for value in (entry, stop)):
            raise ValueError(
                "Entry and stop references must be finite"
            )

        if side == "BUY":
            if stop >= entry:
                raise ValueError(
                    "BUY stop must be below entry reference"
                )
            entry_fill = self.entry_fill_price(entry, side)
            exit_fill = self.exit_fill_price(stop, side)
            price_loss = entry_fill - exit_fill
        elif side == "SELL":
            if stop <= entry:
                raise ValueError(
                    "SELL stop must be above entry reference"
                )
            entry_fill = self.entry_fill_price(entry, side)
            exit_fill = self.exit_fill_price(stop, side)
            price_loss = exit_fill - entry_fill
        else:
            raise ValueError("Side must be BUY or SELL")

        price_loss_cash = (
            max(price_loss, 0.0)
            * float(self.contract_multiplier)
        )
        total_loss = (
            price_loss_cash
            + float(self.commission_per_quantity) * 2.0
        )

        if not isfinite(total_loss) or total_loss <= 0:
            raise ValueError(
                "Instrument costs produced invalid planned stop loss"
            )

        return total_loss
