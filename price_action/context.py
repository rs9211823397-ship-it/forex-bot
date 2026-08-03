"""Point-in-time market context for contextual price-action decisions."""

from dataclasses import dataclass
from math import isfinite

import pandas as pd

from price_action.candle_metrics import (
    CandleMetrics,
    CandleSnapshot,
    calculate_candle_metrics,
    candle_snapshot,
    closed_candles_as_of,
    normalize_timestamp
)
from price_action.liquidity import (
    LiquidityDetector,
    LiquidityState
)
from price_action.zones import ZoneState, calculate_zones


@dataclass(frozen=True)
class RegimeState:
    regime: str
    confirmed_at: pd.Timestamp


@dataclass(frozen=True)
class StructureState:
    trend: str
    confirmed_at: pd.Timestamp


@dataclass(frozen=True)
class ProtectedSwing:
    kind: str
    price: float
    formed_at: pd.Timestamp
    confirmed_at: pd.Timestamp


@dataclass(frozen=True)
class MarketContext:
    decision_time: pd.Timestamp
    htf_regime: RegimeState
    structure: StructureState
    protected_swing_high: ProtectedSwing | None
    protected_swing_low: ProtectedSwing | None
    current_candle: CandleSnapshot
    previous_candle: CandleSnapshot | None
    candle_metrics: CandleMetrics
    zones: ZoneState
    liquidity: LiquidityState
    closed_candle_count: int
    recent_candles: tuple[CandleSnapshot, ...] = ()

    def to_dict(self):
        return {
            "decision_time": self.decision_time.isoformat(),
            "htf_regime": self.htf_regime.regime,
            "structure": self.structure.trend,
            "protected_swing_high": (
                _swing_to_dict(self.protected_swing_high)
            ),
            "protected_swing_low": (
                _swing_to_dict(self.protected_swing_low)
            ),
            "candle_metrics": self.candle_metrics.to_dict(),
            "zones": self.zones.to_dict(),
            "liquidity": self.liquidity.to_dict(),
            "closed_candle_count": self.closed_candle_count,
            "recent_candle_count": len(self.recent_candles)
        }


def _swing_to_dict(swing):
    if swing is None:
        return None

    return {
        "kind": swing.kind,
        "price": swing.price,
        "formed_at": swing.formed_at.isoformat(),
        "confirmed_at": swing.confirmed_at.isoformat()
    }


class ContextEngine:

    def __init__(self, liquidity_detector=None):
        self.liquidity_detector = (
            liquidity_detector or LiquidityDetector()
        )

    def _normalize_regime(self, state, decision_time):
        confirmed_at = normalize_timestamp(state.confirmed_at)

        if confirmed_at > decision_time:
            raise ValueError(
                "HTF regime was not confirmed at decision_time"
            )

        if state.regime not in {
            "BULLISH",
            "BEARISH",
            "NEUTRAL"
        }:
            raise ValueError("Unsupported HTF regime")

        return RegimeState(
            regime=state.regime,
            confirmed_at=confirmed_at
        )

    def _normalize_structure(self, state, decision_time):
        confirmed_at = normalize_timestamp(state.confirmed_at)

        if confirmed_at > decision_time:
            raise ValueError(
                "Structure was not confirmed at decision_time"
            )

        if state.trend not in {
            "BULLISH",
            "BEARISH",
            "NEUTRAL"
        }:
            raise ValueError("Unsupported structure trend")

        return StructureState(
            trend=state.trend,
            confirmed_at=confirmed_at
        )

    def _normalize_swing(
        self,
        swing,
        expected_kind,
        decision_time
    ):
        if swing is None:
            return None

        if swing.kind != expected_kind:
            raise ValueError(
                f"Expected protected swing {expected_kind}"
            )

        formed_at = normalize_timestamp(swing.formed_at)
        confirmed_at = normalize_timestamp(swing.confirmed_at)
        price = float(swing.price)

        if not isfinite(price):
            raise ValueError(
                "Protected swing price must be finite"
            )

        if formed_at > confirmed_at:
            raise ValueError(
                "Swing cannot be confirmed before it forms"
            )

        if confirmed_at > decision_time:
            raise ValueError(
                "Protected swing was not confirmed at decision_time"
            )

        return ProtectedSwing(
            kind=expected_kind,
            price=price,
            formed_at=formed_at,
            confirmed_at=confirmed_at
        )

    def build(
        self,
        data,
        decision_time,
        htf_regime,
        structure,
        protected_swing_high=None,
        protected_swing_low=None
    ):
        decision_timestamp = normalize_timestamp(decision_time)
        candles = closed_candles_as_of(
            data,
            decision_timestamp
        )

        normalized_regime = self._normalize_regime(
            htf_regime,
            decision_timestamp
        )
        normalized_structure = self._normalize_structure(
            structure,
            decision_timestamp
        )
        normalized_high = self._normalize_swing(
            protected_swing_high,
            "HIGH",
            decision_timestamp
        )
        normalized_low = self._normalize_swing(
            protected_swing_low,
            "LOW",
            decision_timestamp
        )

        current_candle = candle_snapshot(
            candles.iloc[-1]
        )
        previous_candle = (
            candle_snapshot(candles.iloc[-2])
            if len(candles) > 1
            else None
        )
        metrics = calculate_candle_metrics(
            current_candle,
            candles.iloc[-1]["atr"]
        )
        zones = calculate_zones(
            (
                normalized_high.price
                if normalized_high is not None
                else None
            ),
            (
                normalized_low.price
                if normalized_low is not None
                else None
            ),
            current_candle.close
        )
        liquidity = self.liquidity_detector.detect(
            data=data,
            decision_time=decision_timestamp,
            protected_high=(
                normalized_high.price
                if normalized_high is not None
                else None
            ),
            protected_low=(
                normalized_low.price
                if normalized_low is not None
                else None
            )
        )

        return MarketContext(
            decision_time=decision_timestamp,
            htf_regime=normalized_regime,
            structure=normalized_structure,
            protected_swing_high=normalized_high,
            protected_swing_low=normalized_low,
            current_candle=current_candle,
            previous_candle=previous_candle,
            candle_metrics=metrics,
            zones=zones,
            liquidity=liquidity,
            closed_candle_count=len(candles),
            recent_candles=tuple(
                candle_snapshot(candles.iloc[index])
                for index in range(
                    max(0, len(candles) - 3),
                    len(candles),
                )
            ),
        )
