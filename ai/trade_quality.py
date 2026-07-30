from config.settings import MIN_TRADE_QUALITY


class TradeQuality:

    def evaluate(
        self,
        trend_score,
        momentum_score,
        structure_score,
        candle_score,
        volume_score,
        adx,
        mtf_confirmed
    ):
        score = 0
        reasons = []

        # Trend
        if abs(trend_score) >= 30:
            score += 20
            reasons.append("Strong trend")
        elif abs(trend_score) >= 20:
            score += 15

        # Momentum
        if abs(momentum_score) >= 20:
            score += 20
            reasons.append("Momentum confirmed")
        elif abs(momentum_score) >= 10:
            score += 10

        # Market Structure
        if abs(structure_score) >= 20:
            score += 20
            reasons.append("Market structure aligned")
        elif abs(structure_score) >= 10:
            score += 10

        # Price Action
        if abs(candle_score) >= 10:
            score += 15
            reasons.append("Strong price action")
        elif abs(candle_score) >= 5:
            score += 8

        # Volume
        if abs(volume_score) >= 15:
            score += 10
            reasons.append("Volume confirms")

        # ADX
        if adx >= 35:
            score += 10
        elif adx >= 25:
            score += 6
        elif adx >= 20:
            score += 4

        # Multi Timeframe
        if mtf_confirmed:
            score += 5

        return {
            "quality": score,
            "approved": score >= MIN_TRADE_QUALITY,
            "reasons": reasons
        }
