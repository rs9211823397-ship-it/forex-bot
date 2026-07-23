"""
Technical Indicators
Calculates market indicators for trading decisions.
"""

import pandas as pd


class TechnicalIndicators:

    def add_indicators(self, data):

        df = data.copy()

        # Remove extra column levels from Yahoo Finance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # EMA trend
        df["EMA_20"] = df["Close"].ewm(span=20).mean()
        df["EMA_50"] = df["Close"].ewm(span=50).mean()

        # RSI
        delta = df["Close"].diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss
        df["RSI"] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()

        df["MACD"] = ema12 - ema26
        df["MACD_SIGNAL"] = df["MACD"].ewm(span=9).mean()

        return df

