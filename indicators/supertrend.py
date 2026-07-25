import pandas as pd


def add_supertrend(df, period=10, multiplier=3):

    hl2 = (df["high"] + df["low"]) / 2

    atr = df["ATR"]

    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)

    supertrend = [True] * len(df)

    final_upper = upperband.copy()
    final_lower = lowerband.copy()

    for i in range(1, len(df)):

        if df["close"].iloc[i] > final_upper.iloc[i - 1]:
            supertrend[i] = True

        elif df["close"].iloc[i] < final_lower.iloc[i - 1]:
            supertrend[i] = False

        else:
            supertrend[i] = supertrend[i - 1]

            if supertrend[i]:
                final_lower.iloc[i] = max(final_lower.iloc[i], final_lower.iloc[i - 1])
            else:
                final_upper.iloc[i] = min(final_upper.iloc[i], final_upper.iloc[i - 1])

    df["SUPERTREND"] = supertrend

    return df
