"""Point-in-time portfolio exposure contracts.

The objects in this module deliberately contain no signal-generation logic.
They describe risk that already exists so a post-signal protection layer can
decide whether a qualified trade may be executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from types import MappingProxyType
from typing import Mapping


VALID_DIRECTIONS = frozenset({"BUY", "SELL"})


def as_utc(value: datetime, field_name: str = "timestamp") -> datetime:
    """Return an aware timestamp in UTC.

    Rejecting naive values avoids environment-dependent local-time behavior in
    backtests and live risk checks.
    """

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CurrencyExposure:
    """Directional exposure to one currency or settlement asset."""

    currency: str
    direction: int

    def __post_init__(self) -> None:
        code = str(self.currency).strip().upper()
        if not code:
            raise ValueError("currency must be non-empty")
        if self.direction not in (-1, 1):
            raise ValueError("currency direction must be -1 or 1")
        object.__setattr__(self, "currency", code)


@dataclass(frozen=True)
class OpenRiskPosition:
    """Risk reserved by an order or position at a historical instant."""

    symbol: str
    direction: str
    opened_at: datetime
    risk_amount: float
    quantity: float = 0.0
    asset_class: str = "UNKNOWN"
    strategy: str = "default"
    currency_exposures: tuple[CurrencyExposure, ...] = ()
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        direction = str(self.direction).strip().upper()
        if not symbol:
            raise ValueError("position symbol must be non-empty")
        if direction not in VALID_DIRECTIONS:
            raise ValueError("position direction must be BUY or SELL")
        opened_at = as_utc(self.opened_at, "opened_at")
        if self.closed_at is not None:
            closed_at = as_utc(self.closed_at, "closed_at")
            if closed_at < opened_at:
                raise ValueError("closed_at cannot precede opened_at")
            object.__setattr__(self, "closed_at", closed_at)
        for field_name in ("risk_amount", "quantity"):
            value = float(getattr(self, field_name))
            if not isfinite(value) or value < 0:
                raise ValueError(
                    f"{field_name} must be finite and non-negative"
                )
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(
            self,
            "asset_class",
            str(self.asset_class).strip().upper() or "UNKNOWN",
        )
        object.__setattr__(
            self,
            "strategy",
            str(self.strategy).strip() or "default",
        )
        object.__setattr__(
            self,
            "currency_exposures",
            tuple(self.currency_exposures),
        )

    def is_open_at(self, decision_time: datetime) -> bool:
        """Return whether this position was open at ``decision_time``."""

        instant = as_utc(decision_time, "decision_time")
        return (
            self.opened_at <= instant
            and (self.closed_at is None or self.closed_at > instant)
        )


@dataclass(frozen=True)
class CorrelationObservation:
    """A point-in-time rolling correlation produced outside this layer."""

    first_symbol: str
    second_symbol: str
    observed_at: datetime
    correlation: float

    def __post_init__(self) -> None:
        first = str(self.first_symbol).strip().upper()
        second = str(self.second_symbol).strip().upper()
        value = float(self.correlation)
        if not first or not second or first == second:
            raise ValueError(
                "correlation requires two different non-empty symbols"
            )
        if not isfinite(value) or value < -1.0 or value > 1.0:
            raise ValueError("correlation must be between -1 and 1")
        object.__setattr__(self, "first_symbol", first)
        object.__setattr__(self, "second_symbol", second)
        object.__setattr__(
            self,
            "observed_at",
            as_utc(self.observed_at, "observed_at"),
        )
        object.__setattr__(self, "correlation", value)

    def value_for(self, first_symbol: str, second_symbol: str) -> float | None:
        """Return the correlation for an unordered symbol pair."""

        requested = {
            str(first_symbol).strip().upper(),
            str(second_symbol).strip().upper(),
        }
        actual = {self.first_symbol, self.second_symbol}
        if requested == actual:
            return self.correlation
        return None


@dataclass(frozen=True)
class PortfolioExposure:
    """Immutable aggregate of risk known at an as-of timestamp."""

    as_of: datetime
    equity: float
    open_positions: int
    open_risk: float
    open_risk_percent: float
    risk_by_asset_class: Mapping[str, float]
    risk_by_currency: Mapping[str, float]
    risk_by_direction: Mapping[str, float]
    risk_by_strategy: Mapping[str, float]

    @classmethod
    def from_positions(
        cls,
        positions: tuple[OpenRiskPosition, ...],
        equity: float,
        decision_time: datetime,
    ) -> "PortfolioExposure":
        """Aggregate only positions that existed at ``decision_time``."""

        instant = as_utc(decision_time, "decision_time")
        account_equity = float(equity)
        if not isfinite(account_equity) or account_equity <= 0:
            raise ValueError("equity must be finite and greater than zero")

        visible = tuple(
            position
            for position in positions
            if position.is_open_at(instant)
        )
        open_risk = sum(position.risk_amount for position in visible)
        by_asset: dict[str, float] = {}
        by_currency: dict[str, float] = {}
        by_direction: dict[str, float] = {}
        by_strategy: dict[str, float] = {}

        for position in visible:
            by_asset[position.asset_class] = (
                by_asset.get(position.asset_class, 0.0)
                + position.risk_amount
            )
            by_direction[position.direction] = (
                by_direction.get(position.direction, 0.0)
                + position.risk_amount
            )
            by_strategy[position.strategy] = (
                by_strategy.get(position.strategy, 0.0)
                + position.risk_amount
            )
            for exposure in position.currency_exposures:
                signed_risk = position.risk_amount * exposure.direction
                by_currency[exposure.currency] = (
                    by_currency.get(exposure.currency, 0.0)
                    + signed_risk
                )

        return cls(
            as_of=instant,
            equity=account_equity,
            open_positions=len(visible),
            open_risk=open_risk,
            open_risk_percent=(open_risk / account_equity) * 100.0,
            risk_by_asset_class=MappingProxyType(dict(sorted(by_asset.items()))),
            risk_by_currency=MappingProxyType(
                dict(sorted(by_currency.items()))
            ),
            risk_by_direction=MappingProxyType(
                dict(sorted(by_direction.items()))
            ),
            risk_by_strategy=MappingProxyType(
                dict(sorted(by_strategy.items()))
            ),
        )


def direction_sign(direction: str) -> int:
    """Convert a validated trade direction to a correlation sign."""

    normalized = str(direction).strip().upper()
    if normalized == "BUY":
        return 1
    if normalized == "SELL":
        return -1
    raise ValueError("direction must be BUY or SELL")


def aligned_correlation(
    candidate_direction: str,
    position_direction: str,
    correlation: float,
) -> bool:
    """Return whether two trades express the same correlated market risk."""

    return (
        direction_sign(candidate_direction)
        * direction_sign(position_direction)
        * float(correlation)
        > 0
    )
