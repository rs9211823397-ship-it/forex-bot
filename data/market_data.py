"""
Market Data Module
Version: 1.0

Purpose:
Handles downloading and loading forex market data.
"""

import yfinance as yf
import pandas as pd


class MarketData:

    def download_data(self, symbol="EURUSD=X", start="2020-01-01", end=None):
        """
        Download historical market data from Yahoo Finance.
        """
        data = yf.download(symbol, start=start, end=end)

        if data.empty:
            raise Exception("No market data downloaded.")

        return data


import yfinance as yf
from config.settings import SYMBOLS, LOOKBACK_DAYS


class MarketData:

    def download_all_data(self):
        market_data = {}

        for category, symbols in SYMBOLS.items():
            for symbol in symbols:
                print(f"Downloading {symbol}...")

                data = yf.download(
                    symbol,
                    start=LOOKBACK_DAYS,
                    progress=False
                )

                if not data.empty:
                    market_data[symbol] = data

        return market_data
