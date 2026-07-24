"""
Market Data Module
Version: 2.0
"""

import yfinance as yf
from config.settings import SYMBOLS, LOOKBACK_DAYS


class MarketData:

    def download_data(self, symbol, start=LOOKBACK_DAYS):

        data = yf.download(
            symbol,
            start=start,
            progress=False
        )

        if data.empty:
            raise Exception(f"No data found for {symbol}")

        return data


    def download_all_data(self):

        market_data = {}

        for category, symbols in SYMBOLS.items():

            for symbol in symbols:

                print(f"Downloading {symbol}...")

                data = self.download_data(symbol)

                market_data[symbol] = data

        return market_data
