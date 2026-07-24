class SignalEngine:

    def generate_signal(self, data):

        latest = data.iloc[-1]

        score = 0
        reasons = []

        if latest["Close"] > latest["EMA_20"]:
            score += 1
            reasons.append("Price above EMA20")
        else:
            score -= 1
            reasons.append("Price below EMA20")

        if latest["EMA_20"] > latest["EMA_50"]:
            score += 1
            reasons.append("Trend bullish")
        else:
            score -= 1
            reasons.append("Trend bearish")

        if latest["RSI"] < 35:
            score += 1
            reasons.append("RSI oversold")
        elif latest["RSI"] > 65:
            score -= 1
            reasons.append("RSI overbought")
        else:
            reasons.append("RSI neutral")

        if latest["MACD"] > latest["MACD_SIGNAL"]:
            score += 1
            reasons.append("MACD bullish")
        else:
            score -= 1
            reasons.append("MACD bearish")

        confidence = abs(score) / 4 * 100

        if score >= 2:
            signal = "BUY"

        elif score <= -2:
            signal = "SELL"

        else:
            signal = "HOLD"

        return {
            "signal": signal,
            "confidence": round(confidence, 1),
            "score": score,
            "reasons": reasons
        }
