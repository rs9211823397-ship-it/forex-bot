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
        mtf_confirmed,
    ):

        score = 0

        strengths = []
        weaknesses = []

        ##########################################################
        # TREND
        ##########################################################

        if abs(trend_score) >= 30:

            score += 20
            strengths.append("Strong trend")

        elif abs(trend_score) >= 20:

            score += 15
            strengths.append("Moderate trend")

        else:

            weaknesses.append("Weak trend")

        ##########################################################
        # MOMENTUM
        ##########################################################

        if abs(momentum_score) >= 20:

            score += 20
            strengths.append("Momentum confirmed")

        elif abs(momentum_score) >= 10:

            score += 10
            strengths.append("Moderate momentum")

        else:

            weaknesses.append("Weak momentum")

        ##########################################################
        # MARKET STRUCTURE
        ##########################################################

        if abs(structure_score) >= 20:

            score += 20
            strengths.append("Strong market structure")

        elif abs(structure_score) >= 10:

            score += 10
            strengths.append("Moderate market structure")

        else:

            weaknesses.append("Weak market structure")

        ##########################################################
        # PRICE ACTION
        ##########################################################

        if abs(candle_score) >= 10:

            score += 15
            strengths.append("Strong price action")

        elif abs(candle_score) >= 5:

            score += 8
            strengths.append("Moderate price action")

        else:

            weaknesses.append("Weak price action")

        ##########################################################
        # VOLUME
        ##########################################################

        if abs(volume_score) >= 15:

            score += 10
            strengths.append("Volume confirmation")

        elif abs(volume_score) > 0:

            score += 5

        else:

            weaknesses.append("Volume not confirmed")

        ##########################################################
        # ADX
        ##########################################################

        if adx >= 35:

            score += 10
            strengths.append("Strong trend strength (ADX)")

        elif adx >= 25:

            score += 7
            strengths.append("Healthy ADX")

        elif adx >= 20:

            score += 4

        else:

            weaknesses.append("Low ADX")

        ##########################################################
        # MULTI TIMEFRAME
        ##########################################################

        if mtf_confirmed:

            score += 5
            strengths.append("Higher timeframe aligned")

        else:

            weaknesses.append("Higher timeframe not aligned")

        ##########################################################
        # FINAL GRADE
        ##########################################################

        if score >= 90:

            grade = "A+"
            confidence = "VERY HIGH"

        elif score >= 80:

            grade = "A"
            confidence = "HIGH"

        elif score >= 70:

            grade = "B"
            confidence = "GOOD"

        elif score >= 60:

            grade = "C"
            confidence = "MODERATE"

        else:

            grade = "D"
            confidence = "LOW"

        ##########################################################
        # RESULT
        ##########################################################

        return {

            "quality": score,

            "grade": grade,

            "confidence": confidence,

            "approved": score >= MIN_TRADE_QUALITY,

            "strengths": strengths,

            "weaknesses": weaknesses,

            # Backward compatibility
            "reasons": strengths,
        }