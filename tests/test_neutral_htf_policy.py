from types import SimpleNamespace

import pandas as pd

from price_action.contextual_trigger import ContextualTriggerEngine, SetupContext
from strategy.decision import MarketRegimeResult, SetupResult
from strategy.setup_detector import SetupDetector


def test_neutral_htf_is_soft_not_directional_veto():
    regime = MarketRegimeResult(
        mtf_confirmed=False,
        regime="NEUTRAL",
        higher_timeframe_available=True,
        confirmation="HOLD",
    )

    assert regime.allows("BUY") is True
    assert regime.allows("SELL") is True
    assert regime.allows("HOLD") is False


def test_opposite_directional_htf_remains_hard_veto():
    bullish = MarketRegimeResult(
        mtf_confirmed=True,
        regime="BULLISH",
        higher_timeframe_available=True,
        confirmation="BUY",
    )
    bearish = MarketRegimeResult(
        mtf_confirmed=True,
        regime="BEARISH",
        higher_timeframe_available=True,
        confirmation="SELL",
    )

    assert bullish.allows("BUY") is True
    assert bullish.allows("SELL") is False
    assert bearish.allows("SELL") is True
    assert bearish.allows("BUY") is False


def test_setup_detector_carries_aligned_ltf_setup_through_neutral_htf():
    detector = SetupDetector(contextual_expiry_candles=3)
    now = pd.Timestamp("2026-08-08T10:00:00Z")
    duration = pd.Timedelta(minutes=15)

    buy = detector.create_contextual_setup(
        setup=SetupResult(trend_score=30),
        decision_time=now,
        bar_duration=duration,
        htf_regime="NEUTRAL",
        structure_trend="BULLISH",
        symbol="BTC-USD",
    )
    sell = detector.create_contextual_setup(
        setup=SetupResult(trend_score=-30),
        decision_time=now,
        bar_duration=duration,
        htf_regime="NEUTRAL",
        structure_trend="BEARISH",
        symbol="ETH-USD",
    )

    assert buy is not None and buy.direction == "BUY"
    assert sell is not None and sell.direction == "SELL"


def test_neutral_htf_still_requires_structure_and_contextual_location():
    engine = ContextualTriggerEngine()
    now = pd.Timestamp("2026-08-08T10:00:00Z")
    setup = SetupContext(
        direction="SELL",
        created_at=now,
        valid_until=now + pd.Timedelta(minutes=45),
    )

    class InvalidZone:
        location = "PREMIUM"

        @staticmethod
        def valid_for_direction(direction):
            return False

    context = SimpleNamespace(
        decision_time=now,
        htf_regime=SimpleNamespace(regime="NEUTRAL"),
        structure=SimpleNamespace(trend="BEARISH"),
        zones=InvalidZone(),
        liquidity=SimpleNamespace(event="NONE"),
    )

    output = engine.evaluate(context, setup)

    # The neutral HTF got past the HTF gate, but contextual location still
    # blocks the trade.  This is the intended soft-neutral behavior.
    assert output.reason_codes == ("INVALID_LOCATION",)


def test_opposite_htf_is_rejected_before_contextual_location():
    engine = ContextualTriggerEngine()
    now = pd.Timestamp("2026-08-08T10:00:00Z")
    setup = SetupContext(
        direction="SELL",
        created_at=now,
        valid_until=now + pd.Timedelta(minutes=45),
    )

    class InvalidZone:
        location = "PREMIUM"

        @staticmethod
        def valid_for_direction(direction):
            return False

    context = SimpleNamespace(
        decision_time=now,
        htf_regime=SimpleNamespace(regime="BULLISH"),
        structure=SimpleNamespace(trend="BEARISH"),
        zones=InvalidZone(),
        liquidity=SimpleNamespace(event="NONE"),
    )

    output = engine.evaluate(context, setup)

    assert output.reason_codes == ("HTF_DIRECTION_MISMATCH",)
