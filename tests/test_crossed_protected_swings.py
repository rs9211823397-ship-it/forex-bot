import pandas as pd

from price_action.context import (
    ContextEngine,
    ProtectedSwing,
    RegimeState,
    StructureState,
)
from price_action.zones import calculate_zones


BASE = pd.Timestamp("2026-08-05T00:00:00Z")


def _frame():
    return pd.DataFrame(
        [
            {
                "close_time": BASE + pd.Timedelta(minutes=15),
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "atr": 0.0010,
            },
            {
                "close_time": BASE + pd.Timedelta(minutes=30),
                "open": 1.1005,
                "high": 1.1015,
                "low": 1.1000,
                "close": 1.1010,
                "atr": 0.0010,
            },
        ]
    )


def test_crossed_protected_swings_make_zones_unavailable_instead_of_crashing():
    zones = calculate_zones(1.0990, 1.1010, 1.1000)

    assert zones.location == "UNAVAILABLE"
    assert zones.range_high is None
    assert zones.range_low is None


def test_context_engine_survives_transient_crossed_protected_swings():
    decision_time = BASE + pd.Timedelta(minutes=30)
    confirmed_at = BASE + pd.Timedelta(minutes=15)

    context = ContextEngine().build(
        data=_frame(),
        decision_time=decision_time,
        htf_regime=RegimeState("BULLISH", confirmed_at),
        structure=StructureState("BULLISH", confirmed_at),
        protected_swing_high=ProtectedSwing(
            kind="HIGH",
            price=1.0990,
            formed_at=BASE,
            confirmed_at=confirmed_at,
        ),
        protected_swing_low=ProtectedSwing(
            kind="LOW",
            price=1.1010,
            formed_at=BASE,
            confirmed_at=confirmed_at,
        ),
    )

    assert context.zones.location == "UNAVAILABLE"
    assert context.protected_swing_high.price == 1.0990
    assert context.protected_swing_low.price == 1.1010
