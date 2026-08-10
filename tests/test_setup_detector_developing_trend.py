import pandas as pd

from strategy.setup_detector import SetupDetector


def _latest(ema20, ema50, ema200, supertrend):
    return pd.Series({
        "EMA_20": ema20,
        "EMA_50": ema50,
        "EMA_200": ema200,
        "SUPERTREND": supertrend,
    })


def test_full_alignment_keeps_legacy_strength():
    detector = SetupDetector()

    bullish = detector.detect(_latest(3.0, 2.0, 1.0, True))
    bearish = detector.detect(_latest(1.0, 2.0, 3.0, False))

    assert bullish.trend_score == 30
    assert bullish.direction == "BUY"
    assert bullish.reasons == ("Bullish EMA alignment",)

    assert bearish.trend_score == -30
    assert bearish.direction == "SELL"
    assert bearish.reasons == ("Bearish EMA alignment",)


def test_developing_trend_can_establish_direction_with_reduced_score():
    detector = SetupDetector()

    bullish = detector.detect(_latest(3.0, 2.0, 4.0, True))
    bearish = detector.detect(_latest(2.0, 3.0, 1.0, False))

    assert bullish.trend_score == 25
    assert bullish.direction == "BUY"
    assert "Bullish 2/3 trend vote" in bullish.reasons[0]

    assert bearish.trend_score == -25
    assert bearish.direction == "SELL"
    assert "Bearish 2/3 trend vote" in bearish.reasons[0]


def test_supertrend_conflict_still_fails_closed():
    detector = SetupDetector()

    bullish_ema_bearish_supertrend = detector.detect(
        _latest(3.0, 2.0, 1.0, False)
    )
    bearish_ema_bullish_supertrend = detector.detect(
        _latest(1.0, 2.0, 3.0, True)
    )

    assert bullish_ema_bearish_supertrend.trend_score == 0
    assert bullish_ema_bearish_supertrend.direction is None
    assert bearish_ema_bullish_supertrend.trend_score == 0
    assert bearish_ema_bullish_supertrend.direction is None


def test_developing_direction_still_requires_context_structure_agreement():
    detector = SetupDetector()
    setup = detector.detect(_latest(3.0, 2.0, 4.0, True))
    decision_time = pd.Timestamp("2026-08-10T00:00:00Z")

    allowed = detector.create_contextual_setup(
        setup=setup,
        decision_time=decision_time,
        bar_duration=pd.Timedelta(minutes=15),
        htf_regime="NEUTRAL",
        structure_trend="BULLISH",
        symbol="EURUSD=X",
    )
    blocked = detector.create_contextual_setup(
        setup=setup,
        decision_time=decision_time + pd.Timedelta(minutes=15),
        bar_duration=pd.Timedelta(minutes=15),
        htf_regime="BEARISH",
        structure_trend="BULLISH",
        symbol="EURUSD=X",
    )

    assert allowed is not None
    assert allowed.direction == "BUY"
    assert blocked is None
