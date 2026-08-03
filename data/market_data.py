"""
Market Data Module
Version: 2.1
"""

import yfinance as yf
import pandas as pd
from config.settings import SYMBOLS, LOOKBACK_DAYS
from data.historical import (
    HistoricalDataError,
    HistoricalDataStore
)
from data.timeframes import (
    normalize_timeframe,
    normalize_timestamp
)


class MarketData:

    def __init__(
        self,
        cache_dir="data/cache",
        cache_downloads=True
    ):
        self.history = HistoricalDataStore(cache_dir)
        self.cache_downloads = bool(cache_downloads)

    def _download(self, symbol, interval):

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


        return data

    def _cached_or_raise(
        self,
        symbol,
        timeframe,
        error=None,
        as_of=None
    ):
        try:
            cached = self.history.load(
                symbol,
                timeframe
            )

            if as_of is not None:
                cutoff = normalize_timestamp(
                    as_of,
                    "as_of"
                )
                cached = cached.loc[
                    cached["close_time"] <= cutoff
                ].copy()

                if cached.empty:
                    raise HistoricalDataError(
                        "No cached candles are available at as_of"
                    )

            return cached
        except HistoricalDataError:
            message = f"No data found for {symbol}"

            if error is None:
                raise Exception(message)

            raise Exception(message) from error

    def download_data(
        self,
        symbol,
        interval=None,
        *,
        as_of=None,
        use_cache=True
    ):
        timeframe = normalize_timeframe(
            interval or "1d"
        )

        try:
            data = self._download(symbol, interval)
        except Exception as exc:
            if use_cache:
                return self._cached_or_raise(
                    symbol,
                    timeframe,
                    exc,
                    as_of=as_of
                )

            raise

        if data.empty:
            if use_cache:
                return self._cached_or_raise(
                    symbol,
                    timeframe,
                    as_of=as_of
                )

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


        data = data[required].copy()
        data.dropna(inplace=True)
        prepared = self.history.prepare(
            data,
            timeframe,
            as_of=as_of or pd.Timestamp.now(tz="UTC")
        )

        if prepared.empty:
            if use_cache:
                return self._cached_or_raise(
                    symbol,
                    timeframe,
                    as_of=as_of
                )

            raise Exception(
                f"No completed candles found for {symbol}"
            )

        if self.cache_downloads:
            self.history.save(
                prepared,
                symbol,
                timeframe,
                source="yahoo"
            )

        return prepared

    def load_csv(
        self,
        path,
        interval,
        expected_version=None
    ):
        """Load a deterministic local CSV replay dataset."""

        return self.history.load_csv(
            path,
            interval,
            expected_version=expected_version
        )


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
