class CandlePatterns:

    def normalize_columns(self, df):
        df = df.copy()

        df.columns = [
            str(col).lower()
            for col in df.columns
        ]

        return df



    def bullish_engulfing(self, df):

        df = self.normalize_columns(df)

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        return (
            prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["close"] > prev["open"]
            and curr["open"] < prev["close"]
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
        )


    def pin_bar(self, df):

        df = self.normalize_columns(df)

        candle = df.iloc[-1]

        body = abs(
            candle["close"] - candle["open"]
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


        if body == 0:
            return "NO PIN BAR"


        if lower_wick > body * 2 and upper_wick < body:
            return "BULLISH PIN BAR"


        if upper_wick > body * 2 and lower_wick < body:
            return "BEARISH PIN BAR"


        return "NO PIN BAR"



    def analyze(self, df):

        df = self.normalize_columns(df)

        result = []

        if self.bullish_engulfing(df):
            result.append(
                "Bullish engulfing"
            )


        if self.bearish_engulfing(df):
            result.append(
                "Bearish engulfing"
            )


        pin = self.pin_bar(df)

        if pin != "NO PIN BAR":
            result.append(pin)


        if not result:
            result.append(
                "No candle confirmation"
            )


        return result

    def check_patterns(self, df):
        return self.analyze(df)
