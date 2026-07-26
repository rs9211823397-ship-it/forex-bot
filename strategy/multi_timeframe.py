from indicators.technical import TechnicalIndicators
from price_action.candles import CandlePatterns


class MultiTimeframeAnalyzer:

    def __init__(self):
        self.indicators = TechnicalIndicators()
        self.candles = CandlePatterns()

    def get_trend(self, df):

        df = self.indicators.add_indicators(df)
        df = df.dropna()

        if len(df) == 0:
            return "SIDEWAYS"

        latest = df.iloc[-1]

        if (
            latest["EMA_20"] > latest["EMA_50"]
            and latest["EMA_50"] > latest["EMA_200"]
        ):
            return "BULLISH"

        elif (
            latest["EMA_20"] < latest["EMA_50"]
            and latest["EMA_50"] < latest["EMA_200"]
        ):
            return "BEARISH"

        return "SIDEWAYS"

    def analyze(self, higher_tf, lower_tf):

        higher_trend = self.get_trend(higher_tf)

        patterns = self.candles.analyze(lower_tf)

        bullish = (
            "Bullish engulfing" in patterns
            or "BULLISH PIN BAR" in patterns
            or "STRONG BULLISH CANDLE" in patterns
        )

        bearish = (
            "Bearish engulfing" in patterns
            or "BEARISH PIN BAR" in patterns
            or "STRONG BEARISH CANDLE" in patterns
        )

        if higher_trend == "BULLISH" and bullish:
            confirmation = "BUY"

        elif higher_trend == "BEARISH" and bearish:
            confirmation = "SELL"

        else:
            confirmation = "HOLD"

        return {
            "higher_trend": higher_trend,
            "confirmation": confirmation
        }
