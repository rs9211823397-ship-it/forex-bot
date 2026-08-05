"""
Market Data Module
Version: 2.2
"""

import logging
import os

import yfinance as yf
import pandas as pd
from config.settings import SYMBOLS, LOOKBACK_DAYS
from data.historical import (
    HistoricalDataError,
    HistoricalDataStore
)
from data.timeframes import (
    normalize_timeframe,
    normalize_timestamp,
    timeframe_delta,
)


logger = logging.getLogger(__name__)


class MarketData:

    def __init__(
        self,
        cache_dir="data/cache",
        cache_downloads=True,
        *,
        execution_mode=None,
        allow_cache_fallback=None,
    ):
        self.history = HistoricalDataStore(cache_dir)
        self.cache_downloads = bool(cache_downloads)
        self.execution_mode = str(
            execution_mode
            if execution_mode is not None
            else os.getenv("AAQTS_EXECUTION_MODE", "PAPER")
        ).upper().strip()
        if allow_cache_fallback is None:
            # Cached candles are useful for research/PAPER continuity, but a
            # broker-connected demo must never create a new trade from stale
            # analytical data while executing against a live MT5 quote.
            allow_cache_fallback = self.execution_mode != "MT5_DEMO"
        self.allow_cache_fallback = bool(allow_cache_fallback)

    @staticmethod
    def _align_provider_candles(data, timeframe):
        """Drop provider-specific partial bars outside the dominant time grid."""

        if not isinstance(data.index, pd.DatetimeIndex) or len(data) < 2:
            return data

        timestamps = pd.DatetimeIndex(
            pd.to_datetime(data.index, utc=True, errors="raise")
        )
        delta_ns = int(timeframe_delta(timeframe).value)
        offsets = timestamps.asi8 % delta_ns
        counts = pd.Series(offsets).value_counts()
        maximum = int(counts.max())
        dominant_offset = int(min(counts[counts == maximum].index))
        aligned_mask = offsets == dominant_offset

        aligned = data.loc[aligned_mask].copy()
        aligned.index = timestamps[aligned_mask]
        if not aligned_mask.all():
            logger.warning(
                "Dropped %s off-grid partial provider candle(s) for %s",
                int((~aligned_mask).sum()),
                normalize_timeframe(timeframe),
            )
        return aligned

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
        if not self.allow_cache_fallback:
            detail = f": {error}" if error is not None else ""
            raise HistoricalDataError(
                f"Fresh market data unavailable for {symbol}; "
                f"{self.execution_mode} forbids cached fallback{detail}"
            ) from error
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

            logger.warning(
                "Using cached market data for %s %s after provider failure",
                symbol,
                timeframe,
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


        data = self._align_provider_candles(data, timeframe)
        if data.empty:
            if use_cache:
                return self._cached_or_raise(
                    symbol,
                    timeframe,
                    as_of=as_of
                )
            raise Exception(
                f"No aligned candles found for {symbol}"
            )

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

                    logger.error(
                        "Fresh market data unavailable for %s %s: %s",
                        symbol,
                        normalize_timeframe(interval or "1d"),
                        e,
                    )
                    print(
                        f"{symbol} ERROR: {e}"
                    )


        return market_data
