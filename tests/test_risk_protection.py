"""Offline deterministic tests for post-signal portfolio protection."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from risk.portfolio import (
    CorrelationObservation,
    CurrencyExposure,
    OpenRiskPosition,
    PortfolioExposure,
)
from risk.protection import (
    ClosedTradeOutcome,
    EquityPoint,
    NewsEvent,
    PortfolioRiskManager,
    ProtectionConfig,
    RiskAction,
    RiskContext,
    TradeRiskRequest,
)


BASE_TIME = datetime(2025, 1, 8, 12, tzinfo=timezone.utc)


def request(**overrides):
    values = {
        "decision_time": BASE_TIME,
        "symbol": "EURUSD",
        "direction": "BUY",
        "requested_quantity": 10.0,
        "risk_amount": 100.0,
        "equity": 10_000.0,
        "asset_class": "FOREX",
        "session": "LONDON",
        "volatility_ratio": 1.0,
        "currency_exposures": (
            CurrencyExposure("EUR", 1),
            CurrencyExposure("USD", -1),
        ),
    }
    values.update(overrides)
    return TradeRiskRequest(**values)


def position(**overrides):
    values = {
        "symbol": "GBPUSD",
        "direction": "BUY",
        "opened_at": BASE_TIME - timedelta(hours=2),
        "risk_amount": 100.0,
        "quantity": 5.0,
        "asset_class": "FOREX",
        "currency_exposures": (
            CurrencyExposure("GBP", 1),
            CurrencyExposure("USD", -1),
        ),
    }
    values.update(overrides)
    return OpenRiskPosition(**values)


def outcome(hours_ago, profit_loss):
    return ClosedTradeOutcome(
        BASE_TIME - timedelta(hours=hours_ago),
        profit_loss,
    )


def test_defaults_are_disabled_and_preserve_an_allowed_request():
    context = RiskContext(
        open_positions=tuple(position(symbol=f"S{i}") for i in range(20)),
        closed_trades=(
            outcome(1, -5_000),
            outcome(2, -5_000),
            outcome(3, -5_000),
        ),
        equity_history=(
            EquityPoint(BASE_TIME - timedelta(days=1), 50_000),
        ),
    )

    assessment = PortfolioRiskManager().assess(request(), context)

    assert assessment.action is RiskAction.ALLOW
    assert assessment.approved_quantity == 10.0
    assert assessment.approved_risk_amount == 100.0
    assert assessment.reason_codes == ("WITHIN_CONFIGURED_LIMITS",)
    assert assessment.warning_codes == ()


@pytest.mark.parametrize(
    ("config", "trades", "reason"),
    [
        (
            ProtectionConfig(max_daily_loss_percent=2.0),
            (outcome(1, -200.0),),
            "DAILY_LOSS_LIMIT",
        ),
        (
            ProtectionConfig(max_weekly_loss_percent=3.0),
            (
                outcome(1, -200.0),
                outcome(25, -100.0),
            ),
            "WEEKLY_LOSS_LIMIT",
        ),
    ],
)
def test_realized_loss_limits_use_utc_point_in_time_results(
    config,
    trades,
    reason,
):
    assessment = PortfolioRiskManager(config).assess(
        request(),
        RiskContext(closed_trades=trades),
    )

    assert assessment.action is RiskAction.BLOCK
    assert assessment.approved_quantity == 0
    assert reason in assessment.reason_codes


def test_drawdown_protection_uses_only_equity_known_at_decision_time():
    config = ProtectionConfig(max_equity_drawdown_percent=10.0)
    history = (
        EquityPoint(BASE_TIME - timedelta(days=1), 12_000),
        EquityPoint(BASE_TIME + timedelta(days=1), 99_000),
    )

    assessment = PortfolioRiskManager(config).assess(
        request(),
        RiskContext(equity_history=history),
    )

    assert assessment.action is RiskAction.BLOCK
    assert assessment.reason_codes == ("EQUITY_DRAWDOWN_LIMIT",)


def test_consecutive_loss_cooldown_expires_deterministically():
    manager = PortfolioRiskManager(
        ProtectionConfig(
            max_consecutive_losses=2,
            consecutive_loss_cooldown=timedelta(hours=6),
        )
    )
    trades = (outcome(1, -10), outcome(2, -20))

    blocked = manager.assess(
        request(),
        RiskContext(closed_trades=trades),
    )
    released = manager.assess(
        request(decision_time=BASE_TIME + timedelta(hours=6)),
        RiskContext(closed_trades=trades),
    )

    assert blocked.action is RiskAction.BLOCK
    assert blocked.reason_codes == ("CONSECUTIVE_LOSS_COOLDOWN",)
    assert released.action is RiskAction.ALLOW


def test_max_open_trades_counts_only_positions_open_at_decision_time():
    future = position(
        symbol="FUTURE",
        opened_at=BASE_TIME + timedelta(minutes=1),
    )
    already_closed = position(
        symbol="CLOSED",
        closed_at=BASE_TIME - timedelta(minutes=1),
    )
    current = position(symbol="CURRENT")
    manager = PortfolioRiskManager(
        ProtectionConfig(max_open_trades=2)
    )

    allowed = manager.assess(
        request(),
        RiskContext(
            open_positions=(current, future, already_closed),
        ),
    )
    blocked = manager.assess(
        request(),
        RiskContext(
            open_positions=(current, position(symbol="CURRENT2")),
        ),
    )

    assert allowed.action is RiskAction.ALLOW
    assert allowed.exposure.open_positions == 1
    assert blocked.action is RiskAction.BLOCK
    assert blocked.reason_codes == ("MAX_OPEN_TRADES",)


def test_portfolio_heat_can_reduce_size_without_changing_direction():
    manager = PortfolioRiskManager(
        ProtectionConfig(max_portfolio_risk_percent=2.0)
    )
    assessment = manager.assess(
        request(),
        RiskContext(
            open_positions=(position(risk_amount=150.0),)
        ),
    )

    assert assessment.action is RiskAction.REDUCE_SIZE
    assert assessment.approved_quantity == pytest.approx(5.0)
    assert assessment.approved_risk_amount == pytest.approx(50.0)
    assert assessment.reason_codes == (
        "PORTFOLIO_HEAT_REDUCTION",
    )
    assert not hasattr(assessment, "direction")


def test_portfolio_heat_blocks_when_reduction_is_disabled():
    manager = PortfolioRiskManager(
        ProtectionConfig(
            max_portfolio_risk_percent=2.0,
            reduce_size_when_possible=False,
        )
    )
    assessment = manager.assess(
        request(),
        RiskContext(
            open_positions=(position(risk_amount=150.0),)
        ),
    )

    assert assessment.action is RiskAction.BLOCK
    assert assessment.reason_codes == ("PORTFOLIO_HEAT_LIMIT",)


def test_aligned_correlation_reduces_but_inverse_risk_does_not():
    manager = PortfolioRiskManager(
        ProtectionConfig(
            max_abs_correlation=0.8,
            max_correlated_risk_percent=1.0,
        )
    )
    observation = CorrelationObservation(
        "EURUSD",
        "GBPUSD",
        BASE_TIME - timedelta(minutes=5),
        0.9,
    )
    current = position(risk_amount=80.0)

    aligned = manager.assess(
        request(),
        RiskContext(
            open_positions=(current,),
            correlations=(observation,),
        ),
    )
    inverse = manager.assess(
        request(direction="SELL"),
        RiskContext(
            open_positions=(current,),
            correlations=(observation,),
        ),
    )

    assert aligned.action is RiskAction.REDUCE_SIZE
    assert aligned.approved_risk_amount == pytest.approx(20.0)
    assert aligned.reason_codes == (
        "CORRELATED_EXPOSURE_REDUCTION",
    )
    assert inverse.action is RiskAction.ALLOW


def test_future_correlation_mutation_cannot_change_historical_assessment():
    manager = PortfolioRiskManager(
        ProtectionConfig(
            max_abs_correlation=0.8,
            max_correlated_risk_percent=1.0,
        )
    )
    current = position(risk_amount=80.0)
    before = manager.assess(
        request(),
        RiskContext(open_positions=(current,)),
    )
    after = manager.assess(
        request(),
        RiskContext(
            open_positions=(current,),
            correlations=(
                CorrelationObservation(
                    "EURUSD",
                    "GBPUSD",
                    BASE_TIME + timedelta(minutes=1),
                    1.0,
                ),
            ),
        ),
    )

    assert before == after
    assert after.action is RiskAction.ALLOW


@pytest.mark.parametrize(
    ("trade_request", "expected_reason"),
    [
        (
            request(session="ASIAN"),
            "SESSION_NOT_ALLOWED",
        ),
        (
            request(volatility_ratio=0.4),
            "VOLATILITY_TOO_LOW",
        ),
        (
            request(volatility_ratio=2.1),
            "VOLATILITY_TOO_HIGH",
        ),
        (
            request(volatility_ratio=None),
            "VOLATILITY_UNAVAILABLE",
        ),
    ],
)
def test_session_and_volatility_filters(
    trade_request,
    expected_reason,
):
    manager = PortfolioRiskManager(
        ProtectionConfig(
            allowed_sessions=("London", "New York"),
            minimum_volatility_ratio=0.5,
            maximum_volatility_ratio=2.0,
        )
    )

    assessment = manager.assess(trade_request)

    assert assessment.action is RiskAction.BLOCK
    assert expected_reason in assessment.reason_codes


class StaticNewsProvider:
    def __init__(self, events):
        self.events = tuple(events)

    def events_between(self, start_time, end_time):
        return self.events


class BrokenNewsProvider:
    def events_between(self, start_time, end_time):
        raise RuntimeError("calendar offline")


def test_news_filter_blocks_relevant_event_and_fails_gracefully():
    manager = PortfolioRiskManager(
        ProtectionConfig(news_filter_enabled=True)
    )
    event = NewsEvent(
        BASE_TIME + timedelta(minutes=20),
        "HIGH",
        ("USD",),
        "CPI",
    )

    blocked = manager.assess(
        request(),
        RiskContext(news_provider=StaticNewsProvider((event,))),
    )
    unavailable = manager.assess(request(), RiskContext())
    broken = manager.assess(
        request(),
        RiskContext(news_provider=BrokenNewsProvider()),
    )
    malformed = manager.assess(
        request(),
        RiskContext(news_provider=StaticNewsProvider((object(),))),
    )

    assert blocked.action is RiskAction.BLOCK
    assert blocked.reason_codes == ("NEWS_EVENT_WINDOW",)
    assert unavailable.action is RiskAction.ALLOW
    assert unavailable.warning_codes == ("NEWS_PROVIDER_UNAVAILABLE",)
    assert broken.action is RiskAction.ALLOW
    assert broken.warning_codes == ("NEWS_PROVIDER_ERROR",)
    assert malformed.action is RiskAction.ALLOW
    assert malformed.warning_codes == ("NEWS_PROVIDER_ERROR",)


def test_news_filter_can_fail_closed_for_live_execution():
    manager = PortfolioRiskManager(
        ProtectionConfig(
            news_filter_enabled=True,
            fail_closed_on_news_error=True,
        )
    )

    unavailable = manager.assess(request(), RiskContext())
    broken = manager.assess(
        request(),
        RiskContext(news_provider=BrokenNewsProvider()),
    )

    assert unavailable.action is RiskAction.BLOCK
    assert unavailable.reason_codes == ("NEWS_PROVIDER_UNAVAILABLE",)
    assert broken.action is RiskAction.BLOCK
    assert broken.reason_codes == ("NEWS_PROVIDER_ERROR",)


def test_same_input_is_deterministic_and_results_are_immutable():
    manager = PortfolioRiskManager(
        ProtectionConfig(max_portfolio_risk_percent=2.0)
    )
    state = RiskContext(
        open_positions=(position(risk_amount=150.0),)
    )

    first = manager.assess(request(), state)
    second = manager.assess(request(), state)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.approved_quantity = 1.0


def test_portfolio_exposure_aggregates_currency_risk_as_of_timestamp():
    exposure = PortfolioExposure.from_positions(
        (
            position(symbol="GBPUSD", risk_amount=100.0),
            position(
                symbol="USDJPY",
                direction="SELL",
                risk_amount=50.0,
                currency_exposures=(
                    CurrencyExposure("USD", -1),
                    CurrencyExposure("JPY", 1),
                ),
            ),
        ),
        equity=10_000,
        decision_time=BASE_TIME,
    )

    assert exposure.open_positions == 2
    assert exposure.open_risk == 150.0
    assert exposure.open_risk_percent == pytest.approx(1.5)
    assert exposure.risk_by_currency == {
        "GBP": 100.0,
        "JPY": 50.0,
        "USD": -150.0,
    }


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProtectionConfig(max_daily_loss_percent=0),
        lambda: ProtectionConfig(max_open_trades=0),
        lambda: ProtectionConfig(max_abs_correlation=0.8),
        lambda: ProtectionConfig(
            minimum_volatility_ratio=2,
            maximum_volatility_ratio=1,
        ),
        lambda: request(direction="HOLD"),
        lambda: request(decision_time=datetime(2025, 1, 1)),
        lambda: request(equity=float("nan")),
        lambda: position(risk_amount=-1),
    ],
)
def test_invalid_configuration_and_point_in_time_inputs_are_rejected(
    factory,
):
    with pytest.raises((TypeError, ValueError)):
        factory()
