"""Deterministic ranking for trades that already have a rule-based setup."""

from config.settings import MIN_TRADE_QUALITY


class TradeQuality:

    @staticmethod
    def _aligned(score, direction):
        if direction == "BUY":
            return score > 0

        if direction == "SELL":
            return score < 0

        return True

    def evaluate(
        self,
        trend_score,
        momentum_score,
        structure_score,
        candle_score,
        volume_score,
        adx,
        mtf_confirmed,
        direction=None,
        mtf_direction=None
    ):
        score = 0
        reasons = []
        supporting_factors = []
        rejected_factors = []

        def aligned(value, label):
            is_aligned = self._aligned(
                value,
                direction
            )

            if value and not is_aligned:
                rejected_factors.append(
                    f"{label} conflicts with {direction}"
                )

            return is_aligned

        # Trend
        if aligned(trend_score, "Trend") and abs(trend_score) >= 30:
            score += 20
            reasons.append("Strong trend")
            supporting_factors.append("trend")

        elif aligned(trend_score, "Trend") and abs(trend_score) >= 20:
            score += 15
            supporting_factors.append("trend")

        # Momentum
        if (
            aligned(momentum_score, "Momentum")
            and abs(momentum_score) >= 20
        ):
            score += 20
            reasons.append("Momentum confirmed")
            supporting_factors.append("momentum")

        elif (
            aligned(momentum_score, "Momentum")
            and abs(momentum_score) >= 10
        ):
            score += 10
            supporting_factors.append("momentum")

        # Market Structure
        if (
            aligned(structure_score, "Market structure")
            and abs(structure_score) >= 20
        ):
            score += 20
            reasons.append("Market structure aligned")
            supporting_factors.append("market_structure")

        elif (
            aligned(structure_score, "Market structure")
            and abs(structure_score) >= 10
        ):
            score += 10
            supporting_factors.append("market_structure")

        # Price Action
        if (
            aligned(candle_score, "Price action")
            and abs(candle_score) >= 10
        ):
            score += 15
            reasons.append("Strong price action")
            supporting_factors.append("price_action")

        elif (
            aligned(candle_score, "Price action")
            and abs(candle_score) >= 5
        ):
            score += 8
            supporting_factors.append("price_action")

        # Volume
        if (
            aligned(volume_score, "Participation")
            and abs(volume_score) >= 15
        ):
            score += 10
            reasons.append("Volume confirms")
            supporting_factors.append("participation")

        # ADX
        if adx >= 35:
            score += 10
            supporting_factors.append("market_strength")

        elif adx >= 25:
            score += 6
            supporting_factors.append("market_strength")

        # Multi Timeframe
        mtf_aligned = (
            mtf_direction is None
            or direction is None
            or mtf_direction == direction
        )

        if mtf_confirmed and mtf_aligned:
            score += 5
            supporting_factors.append("higher_timeframe")

        elif mtf_direction is not None:
            rejected_factors.append(
                "Higher timeframe conflicts with "
                + str(direction)
            )

        return {
            "quality": min(score, 100),
            "approved": score >= MIN_TRADE_QUALITY,
            "reasons": reasons,
            "supporting_factors": supporting_factors,
            "rejected_factors": rejected_factors
        }
