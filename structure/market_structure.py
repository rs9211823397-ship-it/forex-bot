import pandas as pd


class MarketStructure:



    def normalize_columns(self, df):

        df = df.copy()

        df.columns = [
            str(col).lower()
            for col in df.columns
        ]

        return df

    def __init__(self, lookback=3):

        self.lookback = lookback


    def find_swings(self, df):

        df = self.normalize_columns(df)

        # Use recent candles only for live structure
        df = df.tail(300)

        if len(df) < self.lookback * 2 + 5:
            return [], []

        swing_highs = []
        swing_lows = []

        for i in range(self.lookback, len(df)-self.lookback):

            high = df["high"].iloc[i]
            low = df["low"].iloc[i]


            left_highs = df["high"].iloc[
                i-self.lookback:i
            ]

            right_highs = df["high"].iloc[
                i+1:i+self.lookback+1
            ]


            left_lows = df["low"].iloc[
                i-self.lookback:i
            ]

            right_lows = df["low"].iloc[
                i+1:i+self.lookback+1
            ]


            if high > max(left_highs) and high > max(right_highs):
                swing_highs.append(
                    {
                        "index":i,
                        "price":high
                    }
                )


            if low < min(left_lows) and low < min(right_lows):
                swing_lows.append(
                    {
                        "index":i,
                        "price":low
                    }
                )


        return swing_highs, swing_lows



    def detect_structure(self, df):

        df = self.normalize_columns(df)

        highs, lows = self.find_swings(df)


        structure = []


        for i in range(1,len(highs)):

            previous = highs[i-1]["price"]
            current = highs[i]["price"]


            if current > previous:
                structure.append("HH")

            else:
                structure.append("LH")



        for i in range(1,len(lows)):

            previous = lows[i-1]["price"]
            current = lows[i]["price"]


            if current > previous:
                structure.append("HL")

            else:
                structure.append("LL")


        return structure



    def trend(self, df):

        df = self.normalize_columns(df)

        structure = self.detect_structure(df)


        bullish = structure.count("HH") + structure.count("HL")
        bearish = structure.count("LH") + structure.count("LL")


        if bullish > bearish:
            return "BULLISH"


        elif bearish > bullish:
            return "BEARISH"


        else:
            return "SIDEWAYS"



    def support_resistance(self, df):

        df = self.normalize_columns(df)

        highs, lows = self.find_swings(df)


        resistance = [
            x["price"] for x in highs[-5:]
        ]

        support = [
            x["price"] for x in lows[-5:]
        ]


        return {
            "support":support,
            "resistance":resistance
        }

    def detect_bos(self, df):

        df = self.normalize_columns(df)

        highs, lows = self.find_swings(df)

        if len(highs) < 2 or len(lows) < 2:
            return "NO BOS"


        last_high = highs[-2]["price"]
        last_low = lows[-2]["price"]

        current_price = df["close"].iloc[-1]


        if current_price > last_high:
            return "BULLISH BOS"


        if current_price < last_low:
            return "BEARISH BOS"


        return "NO BOS"



    def detect_choch(self, df):

        structure = self.detect_structure(df)


        if len(structure) < 4:
            return "NO CHoCH"


        recent = structure[-4:]


        if "HH" in recent and "HL" in recent and recent[-1] == "LL":
            return "BEARISH CHoCH"


        if "LH" in recent and "LL" in recent and recent[-1] == "HH":
            return "BULLISH CHoCH"


        return "NO CHoCH"
