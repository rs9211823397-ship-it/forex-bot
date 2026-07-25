import sys
sys.path.append(".")

import pandas as pd
from structure.market_structure import MarketStructure


data = {

    "high":[
        1.10,
        1.12,
        1.15,
        1.11,
        1.18,
        1.20,
        1.16,
        1.22,
        1.25,
        1.21,
        1.28,
        1.30,
        1.26,
        1.32
    ],


    "low":[
        1.05,
        1.08,
        1.10,
        1.06,
        1.12,
        1.15,
        1.10,
        1.18,
        1.20,
        1.16,
        1.22,
        1.25,
        1.21,
        1.27
    ]
}


df = pd.DataFrame(data)
df["close"] = df["high"]

ms = MarketStructure(lookback=1)


print("Swing Highs:")
print(ms.find_swings(df)[0])


print("\nSwing Lows:")
print(ms.find_swings(df)[1])


print("\nTrend:")
print(ms.trend(df))


print("\nLevels:")
print(ms.support_resistance(df))

print("\nBOS:")
print(ms.detect_bos(df))


print("\nCHoCH:")
print(ms.detect_choch(df))
