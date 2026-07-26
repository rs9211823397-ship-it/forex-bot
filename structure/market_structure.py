import pandas as pd


class MarketStructure:


    def __init__(self, lookback=3):

        self.lookback = lookback



    def normalize_columns(self, df):

        df = df.copy()

        df.columns = [
            str(col).lower()
            for col in df.columns
        ]

        return df



    def find_swings(self, df):

        df = self.normalize_columns(df)

        df = df.tail(300)

        if len(df) < self.lookback * 2 + 5:
            return [], []


        swing_highs = []
        swing_lows = []


        highs = df["high"].tolist()
        lows = df["low"].tolist()


        for i in range(
            self.lookback,
            len(df)-self.lookback
        ):

            high = highs[i]
            low = lows[i]


            left_highs = highs[
                i-self.lookback:i
            ]

            right_highs = highs[
                i+1:i+self.lookback+1
            ]


            left_lows = lows[
                i-self.lookback:i
            ]

            right_lows = lows[
                i+1:i+self.lookback+1
            ]


            if high > max(left_highs) and high > max(right_highs):

                swing_highs.append(
                    {
                        "index": i,
                        "price": high
                    }
                )


            if low < min(left_lows) and low < min(right_lows):

                swing_lows.append(
                    {
                        "index": i,
                        "price": low
                    }
                )


        return swing_highs, swing_lows



    def detect_structure(self, df):

        highs, lows = self.find_swings(df)

        structure = []


        for i in range(1, len(highs)):

            if highs[i]["price"] > highs[i-1]["price"]:
                structure.append("HH")

            else:
                structure.append("LH")



        for i in range(1, len(lows)):

            if lows[i]["price"] > lows[i-1]["price"]:
                structure.append("HL")

            else:
                structure.append("LL")


        return structure




    def detect_trend(self, df):

        structure = self.detect_structure(df)


        if len(structure) < 4:
            return "SIDEWAYS"


        recent = structure[-10:]


        bullish = (
            recent.count("HH")
            +
            recent.count("HL")
        )


        bearish = (
            recent.count("LH")
            +
            recent.count("LL")
        )


        if bullish > bearish:

            return "BULLISH"


        elif bearish > bullish:

            return "BEARISH"


        return "SIDEWAYS"


    def get_structure_summary(self, df):

        df = self.normalize_columns(df)

        trend = self.detect_trend(df)

        bos = self.detect_bos(df)

        choch = self.detect_choch(df)

        levels = self.support_resistance(df)


        return {

            "trend": trend,

            "bos": bos,

            "choch": choch,

            "support": levels["support"],

            "resistance": levels["resistance"]

        }




    # compatibility with old code
    def trend(self, df):

        return self.detect_trend(df)




    def support_resistance(self, df):

        highs, lows = self.find_swings(df)


        resistance = [
            x["price"]
            for x in highs[-5:]
        ]


        support = [
            x["price"]
            for x in lows[-5:]
        ]


        return {

            "support": support,

            "resistance": resistance

        }




    def detect_bos(self, df):

        df = self.normalize_columns(df)

        highs, lows = self.find_swings(df)

        if len(highs) < 2 or len(lows) < 2:
            return "NO BOS"


        previous_high = highs[-2]["price"]
        previous_low = lows[-2]["price"]


        current_close = df["close"].iloc[-1]
        current_high = df["high"].iloc[-1]
        current_low = df["low"].iloc[-1]


        # confirmed bullish break
        if (
            current_close > previous_high
            and current_high > previous_high
        ):
            return "BULLISH BOS"


        # confirmed bearish break
        if (
            current_close < previous_low
            and current_low < previous_low
        ):
            return "BEARISH BOS"


        return "NO BOS"



    def detect_choch(self, df):

        df = self.normalize_columns(df)

        structure = self.detect_structure(df)

        if len(structure) < 4:
            return "NO CHoCH"


        recent = structure[-4:]

        bos = self.detect_bos(df)


        # bearish reversal confirmation
        if (
            "HH" in recent
            and "HL" in recent
            and bos == "BEARISH BOS"
        ):
            return "BEARISH CHoCH"


        # bullish reversal confirmation
        if (
            "LH" in recent
            and "LL" in recent
            and bos == "BULLISH BOS"
        ):
            return "BULLISH CHoCH"


        return "NO CHoCH"




        recent = structure[-4:]



        if (
            "HH" in recent
            and "HL" in recent
            and recent[-1] == "LL"
        ):

            return "BEARISH CHoCH"



        if (
            "LH" in recent
            and "LL" in recent
            and recent[-1] == "HH"
        ):

            return "BULLISH CHoCH"



        return "NO CHoCH"