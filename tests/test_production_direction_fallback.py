import pandas as pd

from strategy.pipeline import SignalPipeline
from strategy.setup_detector import SetupDetector
from strategy.signal_engine import ProductionSignalPipeline, SignalEngine


def _latest(*, bullish):
    if bullish:
        return pd.Series({
            "EMA_20": 100.0,
            "EMA_50": 101.0,
            "EMA_200": 99.0,
            "SUPERTREND": True,
            "MACD": 1.0,
            "MACD_SIGNAL": 0.5,
            "RSI": 60.0,
            "STOCH_RSI": 50.0,
        })
    return pd.Series({
        "EMA_20": 101.0,
        "EMA_50": 100.0,
        "EMA_200": 102.0,
        "SUPERTREND": False,
        "MACD": -1.0,
        "MACD_SIGNAL": -0.5,
        "RSI": 40.0,
        "STOCH_RSI": 50.0,
    })


def test_majority_vote_can_form_direction_without_full_alignment():
    detector = SetupDetector()
    setup = detector.detect(_latest(bullish=True))

    assert setup.trend_score == 25
    assert setup.direction == "BUY"
    assert setup.reasons == ("Bullish majority trend vote (2/3)",)


def test_production_detector_can_form_small_momentum_led_candidates():
    detector = SetupDetector(allow_momentum_fallback=True)

    bullish = detector.detect(_latest(bullish=True))
    bearish = detector.detect(_latest(bullish=False))

    assert bullish.trend_score == 25
    assert bullish.direction == "BUY"
    assert bullish.reasons == ("Bullish majority trend vote (2/3)",)

    assert bearish.trend_score == -25
    assert bearish.direction == "SELL"
    assert bearish.reasons == ("Bearish majority trend vote (2/3)",)


def test_momentum_led_candidate_still_needs_structure_and_htf_context():
    detector = SetupDetector(allow_momentum_fallback=True)
    setup = detector.detect(_latest(bullish=True))
    now = pd.Timestamp("2026-08-10T01:00:00Z")

    allowed = detector.create_contextual_setup(
        setup=setup,
        decision_time=now,
        bar_duration=pd.Timedelta(minutes=15),
        htf_regime="BULLISH",
        structure_trend="BULLISH",
        symbol="EURUSD=X",
    )
    blocked_structure = detector.create_contextual_setup(
        setup=setup,
        decision_time=now + pd.Timedelta(minutes=15),
        bar_duration=pd.Timedelta(minutes=15),
        htf_regime="BULLISH",
        structure_trend="BEARISH",
        symbol="EURUSD=X",
    )
    blocked_htf = detector.create_contextual_setup(
        setup=setup,
        decision_time=now + pd.Timedelta(minutes=30),
        bar_duration=pd.Timedelta(minutes=15),
        htf_regime="BEARISH",
        structure_trend="BULLISH",
        symbol="EURUSD=X",
    )

    assert allowed is not None
    assert allowed.direction == "BUY"
    assert blocked_structure is None
    assert blocked_htf is None


def test_signal_engine_enables_fallback_only_for_production_pipeline():
    legacy = SignalEngine.__new__(SignalEngine)
    legacy._initialize(object(), SignalPipeline)
    assert legacy.setup_detector.allow_momentum_fallback is False

    production = SignalEngine.__new__(SignalEngine)
    production._initialize(object(), ProductionSignalPipeline)
    assert production.setup_detector.allow_momentum_fallback is True
