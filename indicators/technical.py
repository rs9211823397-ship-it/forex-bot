"""
Technical Indicators
Professional indicator engine.
"""

import pandas as pd
from indicators.supertrend import add_supertrend


class TechnicalIndicators:

    def add_indicators(self, data):

        df = data.copy()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ==========================
        # EMA
        # ==========================

        df["EMA_20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["EMA_50"] = df["close"].ewm(span=50, adjust=False).mean()
        df["EMA_200"] = df["close"].ewm(span=200, adjust=False).mean()

        # ==========================
        # RSI
        # ==========================

        delta = df["close"].diff()

        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss

        df["RSI"] = 100 - (100 / (1 + rs))

        # ==========================
        # Stochastic RSI
        # ==========================

        rsi_min = df["RSI"].rolling(14).min()
        rsi_max = df["RSI"].rolling(14).max()

        df["STOCH_RSI"] = (
            (df["RSI"] - rsi_min)
            / (rsi_max - rsi_min)
        ) * 100

        # ==========================
        # MACD
        # ==========================

        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()

        df["MACD"] = ema12 - ema26
        df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()

        # ==========================
        # ATR
        # ==========================

        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()

        tr = pd.concat(
            [high_low, high_close, low_close],
            axis=1
        ).max(axis=1)

        df["ATR"] = tr.rolling(14).mean()

        # ==========================
        # ADX
        # ==========================

        up_move = df["high"].diff()
        down_move = -df["low"].diff()

        plus_dm = up_move.where(
            (up_move > down_move) & (up_move > 0),
            0.0
        )

        minus_dm = down_move.where(
            (down_move > up_move) & (down_move > 0),
            0.0
        )

        atr14 = tr.rolling(14).mean()

        plus_di = 100 * (
            plus_dm.rolling(14).mean() / atr14
        )

        minus_di = 100 * (
            minus_dm.rolling(14).mean() / atr14
        )

        dx = (
            (plus_di - minus_di).abs()
            / (plus_di + minus_di)
        ) * 100

        df["ADX"] = dx.rolling(14).mean()

        # ==========================
        # Bollinger Bands
        # ==========================

        sma20 = df["close"].rolling(20).mean()

        std20 = df["close"].rolling(20).std()

        df["BB_MIDDLE"] = sma20
        df["BB_UPPER"] = sma20 + (2 * std20)
        df["BB_LOWER"] = sma20 - (2 * std20)

        # ==========================
        # Volume SMA
        # ==========================

        if "volume" in df.columns:

            df["VOL_SMA20"] = df["volume"].rolling(20).mean()

            direction = df["close"].diff().fillna(0)

            obv = [0]

            for i in range(1, len(df)):

                if direction.iloc[i] > 0:
                    obv.append(
                        obv[-1] + df["volume"].iloc[i]
                    )

                elif direction.iloc[i] < 0:
                    obv.append(
                        obv[-1] - df["volume"].iloc[i]
                    )
                    
                else:
                    obv.append(obv[-1])

            df["OBV"] = obv

        else:

            df["VOL_SMA20"] = 0
            df["OBV"] = 0

        # ==========================
        # Supertrend
        # ==========================

        df = add_supertrend(df)

        return df