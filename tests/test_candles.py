import pandas as pd

from price_action.candles import CandlePatterns


df = pd.DataFrame({

    "Open":[110,100],
    "High":[112,115],
    "Low":[98,97],
    "Close":[100,114]

})


cp = CandlePatterns()

print(
    cp.analyze(df)
)
