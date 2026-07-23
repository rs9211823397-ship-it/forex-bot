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