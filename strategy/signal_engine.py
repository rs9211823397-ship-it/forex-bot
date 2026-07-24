class SignalEngine:

    def generate_signal(self, data):

        latest = data.iloc[-1]

        adx = latest["ADX"]
        atr = latest["ATR"]

        score = 0
        reasons = []

        # ==========================
        # Market Regime Filter
        # ==========================
        if adx < 25:
            return {
                "signal": "HOLD",
                "confidence": 0,
                "score": 0,
                "reasons": ["Weak market (ADX below 25)"]
            }

        # ==========================
        # Trend Filter
        # ==========================
        if (
            latest["Close"] > latest["EMA_20"]
            and latest["EMA_20"] > latest["EMA_50"]
        ):
            score += 2
            reasons.append("Strong bullish trend")

        elif (
            latest["Close"] < latest["EMA_20"]
            and latest["EMA_20"] < latest["EMA_50"]
        ):
            score -= 2
            reasons.append("Strong bearish trend")

        else:
            reasons.append("Weak trend")

        # ==========================
        # RSI Confirmation
        # ==========================
        if latest["RSI"] < 35:
            score += 1
            reasons.append("RSI oversold")

        elif latest["RSI"] > 65:
            score -= 1
            reasons.append("RSI overbought")

        else:
            reasons.append("RSI neutral")

        # ==========================
        # MACD Confirmation
        # ==========================
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
