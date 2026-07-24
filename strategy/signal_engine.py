class SignalEngine:

    def generate_signal(self, data):

        latest = data.iloc[-1]

        score = 0
        reasons = []

        # Trend filter
        if latest["Close"] > latest["EMA_20"] and latest["EMA_20"] > latest["EMA_50"]:
            score += 2
            reasons.append("Strong bullish trend")

        elif latest["Close"] < latest["EMA_20"] and latest["EMA_20"] < latest["EMA_50"]:
            score -= 2
            reasons.append("Strong bearish trend")

        else:
            reasons.append("Weak trend")


        # RSI confirmation
        if latest["RSI"] < 30:
            score += 1
            reasons.append("RSI oversold")

        elif latest["RSI"] > 70:
            score -= 1
            reasons.append("RSI overbought")

        else:
            reasons.append("RSI neutral")


        # MACD confirmation
        if latest["MACD"] > latest["MACD_SIGNAL"]:
            score += 1
            reasons.append("MACD bullish")

        else:
            score -= 1
            reasons.append("MACD bearish")


        confidence = abs(score) / 4 * 100


        if score >= 3:
            signal = "BUY"

        elif score <= -3:
            signal = "SELL"

        else:
            signal = "HOLD"


        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "score": score,
            "reasons": reasons
        }
