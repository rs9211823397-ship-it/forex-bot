"""
Technical Indicators
Calculates market indicators for trading decisions.
"""

import pandas as pd
from indicators.supertrend import add_supertrend

class TechnicalIndicators:

    def add_indicators(self, data):

        df = data.copy()

        # Remove extra column levels from Yahoo Finance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ==========================
        # EMA
        # ==========================
        df["EMA_20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()

        # ==========================
        # RSI (14)
        # ==========================
        delta = df["Close"].diff()

        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss
        df["RSI"] = 100 - (100 / (1 + rs))

        # ==========================
        # MACD
        # ==========================
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()

        df["MACD"] = ema12 - ema26
        df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()

        # ==========================
        # ATR (14)
        # ==========================
        high_low = df["High"] - df["Low"]
        high_close = (df["High"] - df["Close"].shift()).abs()
        low_close = (df["Low"] - df["Close"].shift()).abs()

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        # ==========================
        # ADX (14)
        # ==========================
        up_move = df["High"].diff()
        down_move = -df["Low"].diff()

        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        atr14 = tr.rolling(14).mean()

        plus_di = 100 * (plus_dm.rolling(14).mean() / atr14)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr14)

        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di)) * 100
        df["ADX"] = dx.rolling(14).mean()
        df = add_supertrend(df)

        return df
