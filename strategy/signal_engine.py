class SignalEngine:

    def generate_signal(self, data):

        latest = data.iloc[-1]

        score = 0

        if latest["Close"] > latest["EMA_20"]:
            score += 1
        else:
            score -= 1

        if latest["EMA_20"] > latest["EMA_50"]:
            score += 1
        else:
            score -= 1

        if latest["RSI"] < 35:
            score += 1
        elif latest["RSI"] > 65:
            score -= 1

        if latest["MACD"] > latest["MACD_SIGNAL"]:
            score += 1
        else:
            score -= 1

        if score >= 2:
            return "BUY"

        elif score <= -2:
            return "SELL"

        return "HOLD"