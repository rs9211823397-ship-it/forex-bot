
class CandlePatterns:


    def normalize_columns(self, df):

        df = df.copy()

        df.columns = [
            str(col).lower()
            for col in df.columns
        ]

        return df



    def candle_strength(self, candle):

        body = abs(
            candle["close"] - candle["open"]
        )

        total_range = (
            candle["high"] - candle["low"]
        )

        if total_range == 0:
            return 0

        return body / total_range



    def bullish_engulfing(self, df):

        df = self.normalize_columns(df)

        prev = df.iloc[-2]
        curr = df.iloc[-1]


        return (
            prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["close"] > prev["open"]
            and curr["open"] < prev["close"]
            and abs(curr["close"]-curr["open"]) >
                abs(prev["close"]-prev["open"])
            and self.candle_strength(curr) > 0.5
        )



    def bearish_engulfing(self, df):

        df = self.normalize_columns(df)

        prev = df.iloc[-2]
        curr = df.iloc[-1]


        return (
            prev["close"] > prev["open"]
            and curr["close"] < curr["open"]
            and curr["close"] < prev["open"]
            and curr["open"] > prev["close"]
            and abs(curr["close"]-curr["open"]) >
                abs(prev["close"]-prev["open"])
            and self.candle_strength(curr) > 0.5
        )



    def pin_bar(self, df):

        df = self.normalize_columns(df)

        candle = df.iloc[-1]


        body = abs(
            candle["close"] -
            candle["open"]
        )

        upper_wick = (
            candle["high"]
            -
            max(
                candle["close"],
                candle["open"]
            )
        )

        lower_wick = (
            min(
                candle["close"],
                candle["open"]
            )
            -
            candle["low"]
        )


        total_range = (
            candle["high"] -
            candle["low"]
        )


        if total_range == 0:
            return "NO PIN BAR"


        if (
            lower_wick > body * 2
            and body / total_range < 0.35
        ):
            return "BULLISH PIN BAR"


        if (
            upper_wick > body * 2
            and body / total_range < 0.35
        ):
            return "BEARISH PIN BAR"


        return "NO PIN BAR"



    def momentum_candle(self, df):

        df = self.normalize_columns(df)

        candle = df.iloc[-1]


        strength = self.candle_strength(candle)


        if strength > 0.7:

            if candle["close"] > candle["open"]:
                return "STRONG BULLISH CANDLE"

            else:
                return "STRONG BEARISH CANDLE"


        return "NO MOMENTUM CANDLE"



    def analyze(self, df):

        df = self.normalize_columns(df)

        if len(df) < 2:
            return ["No candle confirmation"]


        result = []


        if self.bullish_engulfing(df):
            result.append("Bullish engulfing")


        if self.bearish_engulfing(df):
            result.append("Bearish engulfing")


        pin = self.pin_bar(df)

        if pin != "NO PIN BAR":
            result.append(pin)


        momentum = self.momentum_candle(df)

        if momentum != "NO MOMENTUM CANDLE":
            result.append(momentum)



        if not result:
            result.append(
                "No candle confirmation"
            )


        return result



    def check_patterns(self, df):

        return self.analyze(df)
