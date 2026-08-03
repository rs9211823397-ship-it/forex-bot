"""Immutable strategy decision and intermediate result contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketRegimeResult:
    mtf_confirmed: bool
    reasons: tuple[str, ...] = ()
    regime: str = "NEUTRAL"
    confirmed_at: object | None = None
    higher_timeframe_available: bool = False
    confirmation: str = "HOLD"

    def allows(self, direction):
        """Return whether the confirmed HTF state permits ``direction``."""

        if not self.higher_timeframe_available:
            return True

        return (
            self.mtf_confirmed
            and self.regime
            == ("BULLISH" if direction == "BUY" else "BEARISH")
            and self.confirmation == direction
        )


@dataclass(frozen=True)
class MarketStructureResult:
    score: int
    reasons: tuple[str, ...] = ()
    trend: str = "NEUTRAL"
    confirmed_at: object | None = None
    bos: str = "NO BOS"
    choch: str = "NO CHoCH"

    def allows(self, direction):
        """Reject counter-structure entries and opposite CHoCH events."""

        expected_trend = (
            "BULLISH" if direction == "BUY" else "BEARISH"
        )
        opposing_choch = (
            "BEARISH CHoCH"
            if direction == "BUY"
            else "BULLISH CHoCH"
        )

        return (
            self.trend == expected_trend
            and self.choch != opposing_choch
        )


@dataclass(frozen=True)
class SetupResult:
    trend_score: int
    reasons: tuple[str, ...] = ()

    @property
    def direction(self):
        if self.trend_score > 0:
            return "BUY"

        if self.trend_score < 0:
            return "SELL"

        return None


@dataclass(frozen=True)
class TriggerResult:
    candle_score: int
    patterns: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def confirms(self, direction):
        if direction == "BUY":
            return self.candle_score > 0

        if direction == "SELL":
            return self.candle_score < 0

        return False


@dataclass(frozen=True)
class MomentumResult:
    score: int
    reasons: tuple[str, ...] = ()

    def confirms(self, direction):
        if direction == "BUY":
            return self.score > 0

        if direction == "SELL":
            return self.score < 0

        return False


@dataclass(frozen=True)
class VolumeResult:
    score: int
    reasons: tuple[str, ...] = ()
    quality_score: int | None = None

    @property
    def ranking_score(self):
        if self.quality_score is None:
            return self.score

        return self.quality_score


@dataclass(frozen=True)
class TradeQualityResult:
    quality: int
    approved: bool
    reasons: tuple[str, ...] = ()
    supporting_factors: tuple[str, ...] = ()
    rejected_factors: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionSummary:
    positive: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self):
        return {
            "positive": list(self.positive),
            "warnings": list(self.warnings)
        }


@dataclass(frozen=True)
class SignalDecision:
    signal: str
    confidence: int
    score: int
    reasons: tuple[str, ...] = ()
    decision_summary: DecisionSummary | None = None

    def to_dict(self):
        """Return the exact legacy ``SignalEngine`` dictionary contract."""

        result = {
            "signal": self.signal,
            "confidence": self.confidence,
            "score": self.score,
            "reasons": list(self.reasons)
        }

        if self.decision_summary is not None:
            result["decision_summary"] = self.decision_summary.to_dict()

        return result
