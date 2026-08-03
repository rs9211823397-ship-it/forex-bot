"""Trigger confirmation extracted from the legacy signal engine."""

from price_action.candles import CandlePatterns
from strategy.decision import TriggerResult


class TriggerDetector:

    def __init__(self, candles=None):
        self.candles = candles or CandlePatterns()

    def detect(self, data):
        """Score the existing candle-pattern triggers without changing rules."""

        patterns = self.candles.analyze(data)
        candle_score = 0
        reasons = []

        for pattern in patterns:
            if pattern in [
                "Bullish engulfing",
                "BULLISH PIN BAR"
            ]:
                candle_score += 10
                reasons.append(
                    "Bullish price action: " + pattern
                )

            elif pattern in [
                "Bearish engulfing",
                "BEARISH PIN BAR"
            ]:
                candle_score -= 10
                reasons.append(
                    "Bearish price action: " + pattern
                )

            elif pattern == "STRONG BULLISH CANDLE":
                candle_score += 5
                reasons.append(
                    "Bullish momentum candle"
                )

            elif pattern == "STRONG BEARISH CANDLE":
                candle_score -= 5
                reasons.append(
                    "Bearish momentum candle"
                )

            else:
                reasons.append(pattern)

        return TriggerResult(
            candle_score=candle_score,
            patterns=tuple(patterns),
            reasons=tuple(reasons)
        )
