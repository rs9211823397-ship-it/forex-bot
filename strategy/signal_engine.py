"""
Trading Signal Engine
Generates BUY / SELL / HOLD decisions.
"""


class SignalEngine:

    def generate_signal(self, data):

        latest = data.iloc[-1]

        rsi = latest["RSI"]
        macd = latest["MACD"]
        macd_signal = latest["MACD_SIGNAL"]
        ema20 = latest["EMA_20"]
        ema50 = latest["EMA_50"]
        close = latest["Close"]

        # BUY conditions
        if (
            rsi < 70
            and macd > macd_signal
            and ema20 > ema50
            and close > ema20
        ):
            return "BUY"


        # SELL conditions
        elif (
            rsi > 30
            and macd < macd_signal
            and ema20 < ema50
            and close < ema20
        ):
            return "SELL"


        # No strong setup
        else:
            return "HOLD"
