"""
Market Data Module
Version: 2.1
"""

import yfinance as yf
import pandas as pd
from config.settings import SYMBOLS, LOOKBACK_DAYS


class MarketData:


    def download_data(self, symbol, interval=None):

        if interval == "15m":

            data = yf.download(
                symbol,
                period="60d",
                interval=interval,
                progress=False,
                auto_adjust=False
            )


        elif interval in ["1h", "30m"]:

            data = yf.download(
                symbol,
                period="730d",
                interval=interval,
                progress=False,
                auto_adjust=False
            )

        else:

            data = yf.download(
                symbol,
                start=LOOKBACK_DAYS,
                progress=False,
                auto_adjust=False
            )


        if data.empty:
            raise Exception(f"No data found for {symbol}")


        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)


        data.columns = [
            str(col).lower()
            for col in data.columns
        ]


        required = [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]


        missing = [
            col for col in required
            if col not in data.columns
        ]


        if missing:
            raise Exception(
                f"{symbol} missing columns: {missing}"
            )


        data = data[required]

        data.dropna(inplace=True)

        return data


    def download_all_data(self, interval=None):

        market_data = {}


        for category, symbols in SYMBOLS.items():

            for symbol in symbols:

                print(f"Downloading {symbol}...")


                try:

                    data = self.download_data(symbol, interval)

                    market_data[symbol] = data


                except Exception as e:

                    print(
                        f"{symbol} ERROR: {e}"
                    )


        return market_data
