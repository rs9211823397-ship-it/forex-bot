"""
Market Data Module
Version: 2.1
"""

import yfinance as yf
import pandas as pd
from config.settings import SYMBOLS, LOOKBACK_DAYS


class MarketData:


    def download_data(self, symbol, start=LOOKBACK_DAYS):

        data = yf.download(
            symbol,
            start=start,
            progress=False,
            auto_adjust=False
        )


        if data.empty:
            raise Exception(f"No data found for {symbol}")


        # Fix Yahoo multi-level columns
        if isinstance(data.columns, pd.MultiIndex):

            data.columns = data.columns.get_level_values(0)


        # Keep Yahoo style column names
        data.columns = [
            str(col)
            for col in data.columns
        ]


        # Keep required columns only
        required = [
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
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


        # Remove bad rows
        data.dropna(inplace=True)


        return data



    def download_all_data(self):

        market_data = {}


        for category, symbols in SYMBOLS.items():

            for symbol in symbols:

                print(f"Downloading {symbol}...")


                try:

                    data = self.download_data(symbol)

                    market_data[symbol] = data


                except Exception as e:

                    print(
                        f"{symbol} ERROR: {e}"
                    )


        return market_data
