"""Deterministic post-signal portfolio protection.

This module sits after a strategy has already produced a direction and before
an execution adapter receives an order.  It can allow, block, or reduce a
requested size; it never creates or changes trade direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import isfinite
from typing import Protocol

from risk.portfolio import (
    CorrelationObservation,
    CurrencyExposure,
    OpenRiskPosition,
    PortfolioExposure,
    VALID_DIRECTIONS,
    aligned_correlation,
    as_utc,
)


class RiskAction(str, Enum):
    """Permitted outcomes from the post-signal protection layer."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REDUCE_SIZE = "REDUCE_SIZE"


@dataclass(frozen=True)
class EquityPoint:
    """Point-in-time account equity used for drawdown protection."""

    timestamp: datetime
    equity: float

    def __post_init__(self) -> None:
        value = float(self.equity)
        if not isfinite(value) or value <= 0:
            raise ValueError("equity point must be finite and positive")
        object.__setattr__(
            self,
            "timestamp",
            as_utc(self.timestamp, "equity timestamp"),
        )
        object.__setattr__(self, "equity", value)


@dataclass(frozen=True)
class ClosedTradeOutcome:
    """A realized result available from its close timestamp onward."""

    closed_at: datetime
    profit_loss: float

    def __post_init__(self) -> None:
        value = float(self.profit_loss)
        if not isfinite(value):
            raise ValueError("profit_loss must be finite")
        object.__setattr__(
            self,
            "closed_at",
            as_utc(self.closed_at, "closed_at"),
        )
        object.__setattr__(self, "profit_loss", value)


@dataclass(frozen=True)
class NewsEvent:
    """Scheduled event returned by a news calendar adapter."""

    event_time: datetime
    impact: str
    currencies: tuple[str, ...] = ()
    name: str = ""

    def __post_init__(self) -> None:
        impact = str(self.impact).strip().upper()
        if impact not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("news impact must be LOW, MEDIUM, or HIGH")
        currencies = tuple(
            sorted(
                {
                    str(currency).strip().upper()
                    for currency in self.currencies
                    if str(currency).strip()
                }
            )
        )
        object.__setattr__(
            self,
            "event_time",
            as_utc(self.event_time, "event_time"),
        )
        object.__setattr__(self, "impact", impact)
        object.__setattr__(self, "currencies", currencies)
        object.__setattr__(self, "name", str(self.name).strip())


class NewsEventProvider(Protocol):
    """Minimal interface implemented by future calendar integrations."""

    def events_between(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[NewsEvent, ...]:
        """Return events in the requested aware UTC interval."""


@dataclass(frozen=True)
class TradeRiskRequest:
    """A qualified setup requesting portfolio authorization."""

    decision_time: datetime
    symbol: str
    direction: str
    requested_quantity: float
    risk_amount: float
    equity: float
    asset_class: str = "UNKNOWN"
    session: str | None = None
    volatility_ratio: float | None = None
    currency_exposures: tuple[CurrencyExposure, ...] = ()

    def __post_init__(self) -> None:
        symbol = str(self.symbol).strip().upper()
        direction = str(self.direction).strip().upper()
        if not symbol:
            raise ValueError("symbol must be non-empty")
        if direction not in VALID_DIRECTIONS:
            raise ValueError(
                "direction must already be an existing BUY or SELL setup"
            )
        for field_name in ("requested_quantity", "risk_amount", "equity"):
            value = float(getattr(self, field_name))
            if not isfinite(value) or value <= 0:
                raise ValueError(
                    f"{field_name} must be finite and greater than zero"
                )
            object.__setattr__(self, field_name, value)
        if self.volatility_ratio is not None:
            volatility = float(self.volatility_ratio)
            if not isfinite(volatility) or volatility < 0:
                raise ValueError(
                    "volatility_ratio must be finite and non-negative"
                )
            object.__setattr__(self, "volatility_ratio", volatility)
        session = (
            str(self.session).strip().upper()
            if self.session is not None
            else None
        )
        object.__setattr__(
            self,
            "decision_time",
            as_utc(self.decision_time, "decision_time"),
        )
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(
            self,
            "asset_class",
            str(self.asset_class).strip().upper() or "UNKNOWN",
        )
        object.__setattr__(self, "session", session)
        object.__setattr__(
            self,
            "currency_exposures",
            tuple(self.currency_exposures),
        )


@dataclass(frozen=True)
class RiskContext:
    """All external state consulted by one deterministic assessment."""

    open_positions: tuple[OpenRiskPosition, ...] = ()
    closed_trades: tuple[ClosedTradeOutcome, ...] = ()
    equity_history: tuple[EquityPoint, ...] = ()
    correlations: tuple[CorrelationObservation, ...] = ()
    news_provider: NewsEventProvider | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "open_positions",
            tuple(self.open_positions),
        )
        object.__setattr__(
            self,
            "closed_trades",
            tuple(self.closed_trades),
        )
        object.__setattr__(
            self,
            "equity_history",
            tuple(self.equity_history),
        )
        object.__setattr__(
            self,
            "correlations",
            tuple(self.correlations),
        )


@dataclass(frozen=True)
class ProtectionConfig:
    """Configurable limits; every limit is disabled by default."""

    max_daily_loss_percent: float | None = None
    max_weekly_loss_percent: float | None = None
    max_equity_drawdown_percent: float | None = None
    max_consecutive_losses: int | None = None
    consecutive_loss_cooldown: timedelta = timedelta(hours=24)
    max_open_trades: int | None = None
    max_portfolio_risk_percent: float | None = None
    max_abs_correlation: float | None = None
    max_correlated_risk_percent: float | None = None
    allowed_sessions: tuple[str, ...] = ()
    minimum_volatility_ratio: float | None = None
    maximum_volatility_ratio: float | None = None
    news_filter_enabled: bool = False
    blocked_news_impacts: tuple[str, ...] = ("HIGH",)
    news_pre_event_buffer: timedelta = timedelta(minutes=30)
    news_post_event_buffer: timedelta = timedelta(minutes=15)
    reduce_size_when_possible: bool = True

    def __post_init__(self) -> None:
        percent_fields = (
            "max_daily_loss_percent",
            "max_weekly_loss_percent",
            "max_equity_drawdown_percent",
            "max_portfolio_risk_percent",
            "max_correlated_risk_percent",
        )
        for field_name in percent_fields:
            value = getattr(self, field_name)
            if value is None:
                continue
            number = float(value)
            if not isfinite(number) or number <= 0 or number > 100:
                raise ValueError(
                    f"{field_name} must be in the interval (0, 100]"
                )
            object.__setattr__(self, field_name, number)

        if (
            self.max_consecutive_losses is not None
            and (
                not isinstance(self.max_consecutive_losses, int)
                or isinstance(self.max_consecutive_losses, bool)
                or self.max_consecutive_losses <= 0
            )
        ):
            raise ValueError(
                "max_consecutive_losses must be a positive integer"
            )
        if (
            self.max_open_trades is not None
            and (
                not isinstance(self.max_open_trades, int)
                or isinstance(self.max_open_trades, bool)
                or self.max_open_trades <= 0
            )
        ):
            raise ValueError("max_open_trades must be a positive integer")
        if self.consecutive_loss_cooldown <= timedelta(0):
            raise ValueError(
                "consecutive_loss_cooldown must be greater than zero"
            )

        correlation_values = (
            self.max_abs_correlation,
            self.max_correlated_risk_percent,
        )
        if (correlation_values[0] is None) != (
            correlation_values[1] is None
        ):
            raise ValueError(
                "correlation threshold and risk limit must be configured "
                "together"
            )
        if self.max_abs_correlation is not None:
            correlation = float(self.max_abs_correlation)
            if (
                not isfinite(correlation)
                or correlation <= 0
                or correlation > 1
            ):
                raise ValueError(
                    "max_abs_correlation must be in the interval (0, 1]"
                )
            object.__setattr__(
                self,
                "max_abs_correlation",
                correlation,
            )

        for field_name in (
            "minimum_volatility_ratio",
            "maximum_volatility_ratio",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            number = float(value)
            if not isfinite(number) or number < 0:
                raise ValueError(
                    f"{field_name} must be finite and non-negative"
                )
            object.__setattr__(self, field_name, number)
        if (
            self.minimum_volatility_ratio is not None
            and self.maximum_volatility_ratio is not None
            and self.minimum_volatility_ratio
            > self.maximum_volatility_ratio
        ):
            raise ValueError(
                "minimum_volatility_ratio cannot exceed maximum"
            )

        sessions = tuple(
            sorted(
                {
                    str(session).strip().upper()
                    for session in self.allowed_sessions
                    if str(session).strip()
                }
            )
        )
        impacts = tuple(
            sorted(
                {
                    str(impact).strip().upper()
                    for impact in self.blocked_news_impacts
                }
            )
        )
        if not set(impacts).issubset({"LOW", "MEDIUM", "HIGH"}):
            raise ValueError(
                "blocked_news_impacts contains an invalid impact"
            )
        for field_name in (
            "news_pre_event_buffer",
            "news_post_event_buffer",
        ):
            if getattr(self, field_name) < timedelta(0):
                raise ValueError(
                    f"{field_name} must be non-negative"
                )
        object.__setattr__(self, "allowed_sessions", sessions)
        object.__setattr__(self, "blocked_news_impacts", impacts)


@dataclass(frozen=True)
class RiskAssessment:
    """Immutable authorization returned to an execution orchestrator."""

    action: RiskAction
    decision_time: datetime
    approved_quantity: float
    approved_risk_amount: float
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    exposure: PortfolioExposure

    @property
    def allowed(self) -> bool:
        return self.action is not RiskAction.BLOCK


class PortfolioRiskManager:
    """Apply configured portfolio limits to already-qualified trade setups."""

    def __init__(
        self,
        config: ProtectionConfig | None = None,
    ) -> None:
        self.config = config or ProtectionConfig()

    def assess(
        self,
        request: TradeRiskRequest,
        context: RiskContext | None = None,
    ) -> RiskAssessment:
        """Assess a request using only state visible at its decision time."""

        if not isinstance(request, TradeRiskRequest):
            raise TypeError("request must be a TradeRiskRequest")
        state = context or RiskContext()
        if not isinstance(state, RiskContext):
            raise TypeError("context must be a RiskContext")

        instant = request.decision_time
        visible_positions = tuple(
            position
            for position in state.open_positions
            if position.is_open_at(instant)
        )
        visible_outcomes = tuple(
            outcome
            for outcome in state.closed_trades
            if outcome.closed_at <= instant
        )
        visible_equity = tuple(
            point
            for point in state.equity_history
            if point.timestamp <= instant
        )
        visible_correlations = tuple(
            observation
            for observation in state.correlations
            if observation.observed_at <= instant
        )
        exposure = PortfolioExposure.from_positions(
            visible_positions,
            request.equity,
            instant,
        )

        blocking: list[str] = []
        reductions: list[tuple[str, float]] = []
        warnings: list[str] = []

        self._check_realized_limits(
            request,
            visible_outcomes,
            blocking,
        )
        self._check_drawdown(
            request,
            visible_equity,
            blocking,
        )
        self._check_consecutive_losses(
            request,
            visible_outcomes,
            blocking,
        )

        if (
            self.config.max_open_trades is not None
            and exposure.open_positions >= self.config.max_open_trades
        ):
            blocking.append("MAX_OPEN_TRADES")

        self._check_session_and_volatility(request, blocking)
        self._check_portfolio_heat(
            request,
            exposure,
            blocking,
            reductions,
        )
        self._check_correlation(
            request,
            visible_positions,
            visible_correlations,
            blocking,
            reductions,
        )
        self._check_news(request, state.news_provider, blocking, warnings)

        if blocking:
            return RiskAssessment(
                action=RiskAction.BLOCK,
                decision_time=instant,
                approved_quantity=0.0,
                approved_risk_amount=0.0,
                reason_codes=tuple(dict.fromkeys(blocking)),
                warning_codes=tuple(dict.fromkeys(warnings)),
                exposure=exposure,
            )

        if reductions:
            factor = min(
                max(min(reduction_factor, 1.0), 0.0)
                for _, reduction_factor in reductions
            )
            if factor <= 0:
                return RiskAssessment(
                    action=RiskAction.BLOCK,
                    decision_time=instant,
                    approved_quantity=0.0,
                    approved_risk_amount=0.0,
                    reason_codes=tuple(
                        dict.fromkeys(
                            reason for reason, _ in reductions
                        )
                    ),
                    warning_codes=tuple(dict.fromkeys(warnings)),
                    exposure=exposure,
                )
            return RiskAssessment(
                action=RiskAction.REDUCE_SIZE,
                decision_time=instant,
                approved_quantity=request.requested_quantity * factor,
                approved_risk_amount=request.risk_amount * factor,
                reason_codes=tuple(
                    dict.fromkeys(reason for reason, _ in reductions)
                ),
                warning_codes=tuple(dict.fromkeys(warnings)),
                exposure=exposure,
            )

        return RiskAssessment(
            action=RiskAction.ALLOW,
            decision_time=instant,
            approved_quantity=request.requested_quantity,
            approved_risk_amount=request.risk_amount,
            reason_codes=("WITHIN_CONFIGURED_LIMITS",),
            warning_codes=tuple(dict.fromkeys(warnings)),
            exposure=exposure,
        )

    def _check_realized_limits(
        self,
        request: TradeRiskRequest,
        outcomes: tuple[ClosedTradeOutcome, ...],
        blocking: list[str],
    ) -> None:
        utc_date = request.decision_time.date()
        iso_year, iso_week, _ = utc_date.isocalendar()
        daily_loss = sum(
            -outcome.profit_loss
            for outcome in outcomes
            if outcome.profit_loss < 0
            and outcome.closed_at.date() == utc_date
        )
        weekly_loss = sum(
            -outcome.profit_loss
            for outcome in outcomes
            if outcome.profit_loss < 0
            and (
                outcome.closed_at.date().isocalendar().year,
                outcome.closed_at.date().isocalendar().week,
            )
            == (iso_year, iso_week)
        )
        if (
            self.config.max_daily_loss_percent is not None
            and (daily_loss / request.equity) * 100.0
            >= self.config.max_daily_loss_percent
        ):
            blocking.append("DAILY_LOSS_LIMIT")
        if (
            self.config.max_weekly_loss_percent is not None
            and (weekly_loss / request.equity) * 100.0
            >= self.config.max_weekly_loss_percent
        ):
            blocking.append("WEEKLY_LOSS_LIMIT")

    def _check_drawdown(
        self,
        request: TradeRiskRequest,
        equity_history: tuple[EquityPoint, ...],
        blocking: list[str],
    ) -> None:
        if self.config.max_equity_drawdown_percent is None:
            return
        peak = max(
            (point.equity for point in equity_history),
            default=request.equity,
        )
        peak = max(peak, request.equity)
        drawdown_percent = (
            (peak - request.equity) / peak
        ) * 100.0
        if drawdown_percent >= self.config.max_equity_drawdown_percent:
            blocking.append("EQUITY_DRAWDOWN_LIMIT")

    def _check_consecutive_losses(
        self,
        request: TradeRiskRequest,
        outcomes: tuple[ClosedTradeOutcome, ...],
        blocking: list[str],
    ) -> None:
        limit = self.config.max_consecutive_losses
        if limit is None:
            return
        ordered = sorted(
            outcomes,
            key=lambda outcome: outcome.closed_at,
            reverse=True,
        )
        loss_streak = 0
        most_recent_loss: ClosedTradeOutcome | None = None
        for outcome in ordered:
            if outcome.profit_loss >= 0:
                break
            loss_streak += 1
            if most_recent_loss is None:
                most_recent_loss = outcome
        if (
            loss_streak >= limit
            and most_recent_loss is not None
            and request.decision_time
            < (
                most_recent_loss.closed_at
                + self.config.consecutive_loss_cooldown
            )
        ):
            blocking.append("CONSECUTIVE_LOSS_COOLDOWN")

    def _check_session_and_volatility(
        self,
        request: TradeRiskRequest,
        blocking: list[str],
    ) -> None:
        if self.config.allowed_sessions:
            if (
                request.session is None
                or request.session not in self.config.allowed_sessions
            ):
                blocking.append("SESSION_NOT_ALLOWED")

        requires_volatility = (
            self.config.minimum_volatility_ratio is not None
            or self.config.maximum_volatility_ratio is not None
        )
        if requires_volatility and request.volatility_ratio is None:
            blocking.append("VOLATILITY_UNAVAILABLE")
            return
        if request.volatility_ratio is None:
            return
        if (
            self.config.minimum_volatility_ratio is not None
            and request.volatility_ratio
            < self.config.minimum_volatility_ratio
        ):
            blocking.append("VOLATILITY_TOO_LOW")
        if (
            self.config.maximum_volatility_ratio is not None
            and request.volatility_ratio
            > self.config.maximum_volatility_ratio
        ):
            blocking.append("VOLATILITY_TOO_HIGH")

    def _check_portfolio_heat(
        self,
        request: TradeRiskRequest,
        exposure: PortfolioExposure,
        blocking: list[str],
        reductions: list[tuple[str, float]],
    ) -> None:
        limit_percent = self.config.max_portfolio_risk_percent
        if limit_percent is None:
            return
        limit_amount = request.equity * (limit_percent / 100.0)
        available = limit_amount - exposure.open_risk
        if request.risk_amount <= available + 1e-12:
            return
        if (
            self.config.reduce_size_when_possible
            and available > 0
        ):
            reductions.append(
                (
                    "PORTFOLIO_HEAT_REDUCTION",
                    available / request.risk_amount,
                )
            )
        else:
            blocking.append("PORTFOLIO_HEAT_LIMIT")

    def _check_correlation(
        self,
        request: TradeRiskRequest,
        positions: tuple[OpenRiskPosition, ...],
        observations: tuple[CorrelationObservation, ...],
        blocking: list[str],
        reductions: list[tuple[str, float]],
    ) -> None:
        threshold = self.config.max_abs_correlation
        limit_percent = self.config.max_correlated_risk_percent
        if threshold is None or limit_percent is None:
            return

        latest: dict[str, CorrelationObservation] = {}
        for observation in sorted(
            observations,
            key=lambda item: item.observed_at,
        ):
            if request.symbol not in {
                observation.first_symbol,
                observation.second_symbol,
            }:
                continue
            other = (
                observation.second_symbol
                if observation.first_symbol == request.symbol
                else observation.first_symbol
            )
            latest[other] = observation

        correlated_risk = 0.0
        for position in positions:
            observation = latest.get(position.symbol)
            if observation is None:
                continue
            correlation = observation.value_for(
                request.symbol,
                position.symbol,
            )
            if (
                correlation is not None
                and abs(correlation) >= threshold
                and aligned_correlation(
                    request.direction,
                    position.direction,
                    correlation,
                )
            ):
                correlated_risk += position.risk_amount

        if correlated_risk <= 0:
            return
        limit_amount = request.equity * (limit_percent / 100.0)
        available = limit_amount - correlated_risk
        if request.risk_amount <= available + 1e-12:
            return
        if (
            self.config.reduce_size_when_possible
            and available > 0
        ):
            reductions.append(
                (
                    "CORRELATED_EXPOSURE_REDUCTION",
                    available / request.risk_amount,
                )
            )
        else:
            blocking.append("CORRELATED_EXPOSURE_LIMIT")

    def _check_news(
        self,
        request: TradeRiskRequest,
        provider: NewsEventProvider | None,
        blocking: list[str],
        warnings: list[str],
    ) -> None:
        if not self.config.news_filter_enabled:
            return
        if provider is None:
            warnings.append("NEWS_PROVIDER_UNAVAILABLE")
            return

        start = (
            request.decision_time
            - self.config.news_post_event_buffer
        )
        end = (
            request.decision_time
            + self.config.news_pre_event_buffer
        )
        try:
            events = tuple(provider.events_between(start, end))
            if not all(
                isinstance(event, NewsEvent)
                for event in events
            ):
                raise TypeError(
                    "news provider returned a non-NewsEvent value"
                )

            request_currencies = {
                exposure.currency
                for exposure in request.currency_exposures
            }
            for event in sorted(
                events,
                key=lambda item: item.event_time,
            ):
                if event.event_time < start or event.event_time > end:
                    continue
                if (
                    event.impact
                    not in self.config.blocked_news_impacts
                ):
                    continue
                if (
                    event.currencies
                    and request_currencies
                    and not request_currencies.intersection(
                        event.currencies
                    )
                ):
                    continue
                blocking.append("NEWS_EVENT_WINDOW")
                return
        except Exception:
            warnings.append("NEWS_PROVIDER_ERROR")


# Compatibility-oriented name for callers that prefer a generic label.
RiskProtectionManager = PortfolioRiskManager
