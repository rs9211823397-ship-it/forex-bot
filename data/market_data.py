"""
Market Data Module
Version: 2.3
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from config.settings import (
    LOOKBACK_DAYS,
    MT5_SYMBOL_MAP,
    MT5_TERMINAL_PATH,
    SYMBOLS,
)
from data.historical import HistoricalDataError, HistoricalDataStore
from data.timeframes import normalize_timeframe, normalize_timestamp, timeframe_delta


logger = logging.getLogger(__name__)


class MarketDataError(RuntimeError):
    """Raised when trading market data cannot be obtained safely."""


class MarketDataFreshnessError(MarketDataError):
    """Raised when the newest completed candle is too old for new entries."""


class MarketData:
    """Causal OHLCV provider with a broker-native MT5_DEMO path.

    PAPER research may use Yahoo and its deterministic cache. MT5_DEMO uses
    the connected MT5 terminal so analysis and execution share the same broker
    feed. A failed live broker-data read never falls back to cached Yahoo data.
    """

    def __init__(
        self,
        cache_dir="data/cache",
        cache_downloads=True,
        *,
        execution_mode=None,
        allow_cache_fallback=None,
        provider=None,
        max_stale_bars=None,
    ):
        self.history = HistoricalDataStore(cache_dir)
        self.cache_downloads = bool(cache_downloads)
        self.execution_mode = str(
            execution_mode
            if execution_mode is not None
            else os.getenv("AAQTS_EXECUTION_MODE", "PAPER")
        ).upper().strip()
        self.provider = str(
            provider
            if provider is not None
            else os.getenv(
                "AAQTS_MARKET_DATA_PROVIDER",
                "MT5" if self.execution_mode == "MT5_DEMO" else "YAHOO",
            )
        ).upper().strip()
        if self.provider not in {"MT5", "YAHOO"}:
            raise ValueError("AAQTS_MARKET_DATA_PROVIDER must be MT5 or YAHOO")
        if self.execution_mode == "MT5_DEMO" and self.provider != "MT5":
            raise ValueError("MT5_DEMO requires AAQTS_MARKET_DATA_PROVIDER=MT5")
        if allow_cache_fallback is None:
            allow_cache_fallback = self.execution_mode != "MT5_DEMO"
        self.allow_cache_fallback = bool(allow_cache_fallback)
        self.max_stale_bars = float(
            max_stale_bars
            if max_stale_bars is not None
            else os.getenv("AAQTS_MARKET_DATA_MAX_STALE_BARS", "2.5")
        )
        if self.max_stale_bars <= 0:
            raise ValueError("AAQTS_MARKET_DATA_MAX_STALE_BARS must be positive")

    @staticmethod
    def _align_provider_candles(data, timeframe):
        """Drop provider-specific partial bars outside the dominant time grid."""
        if not isinstance(data.index, pd.DatetimeIndex) or len(data) < 2:
            return data
        timestamps = pd.DatetimeIndex(pd.to_datetime(data.index, utc=True, errors="raise"))
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

    @staticmethod
    def _mt5_timeframe(mt5, interval):
        name = {
            "15m": "TIMEFRAME_M15",
            "30m": "TIMEFRAME_M30",
            "1h": "TIMEFRAME_H1",
            "1d": "TIMEFRAME_D1",
        }.get(normalize_timeframe(interval))
        if name is None or not hasattr(mt5, name):
            raise MarketDataError(f"Unsupported MT5 timeframe: {interval}")
        return getattr(mt5, name)

    @staticmethod
    def _mt5_count(interval):
        return {"15m": 6000, "30m": 5000, "1h": 6000, "1d": 2500}.get(
            normalize_timeframe(interval), 2500
        )

    def _download_mt5(self, symbol, interval):
        broker_symbol = MT5_SYMBOL_MAP.get(symbol)
        if not broker_symbol:
            raise MarketDataError(f"No MT5 symbol mapping configured for {symbol}")
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise MarketDataError("MetaTrader5 package is unavailable") from exc

        initialized_here = False
        if mt5.terminal_info() is None:
            initialized_here = bool(mt5.initialize(path=MT5_TERMINAL_PATH))
            if not initialized_here:
                raise MarketDataError(f"MT5 initialization failed: {mt5.last_error()}")
        try:
            info = mt5.symbol_info(broker_symbol)
            if info is None:
                raise MarketDataError(f"Unknown MT5 symbol: {broker_symbol}")
            if not getattr(info, "visible", False) and not mt5.symbol_select(
                broker_symbol, True
            ):
                raise MarketDataError(f"Could not select MT5 symbol: {broker_symbol}")
            rates = mt5.copy_rates_from_pos(
                broker_symbol,
                self._mt5_timeframe(mt5, interval),
                1,  # completed candles only; never consume the forming bar
                self._mt5_count(interval),
            )
            if rates is None or len(rates) == 0:
                raise MarketDataError(
                    f"No completed MT5 candles for {symbol} ({broker_symbol}): "
                    f"{mt5.last_error()}"
                )
            frame = pd.DataFrame(rates)
            required = {"time", "open", "high", "low", "close"}
            missing = required.difference(frame.columns)
            if missing:
                raise MarketDataError(
                    "MT5 candle response missing columns: " + ", ".join(sorted(missing))
                )
            frame.index = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
            frame.index.name = "open_time"
            if "tick_volume" in frame.columns:
                frame["volume"] = pd.to_numeric(frame["tick_volume"], errors="coerce")
            elif "real_volume" in frame.columns:
                frame["volume"] = pd.to_numeric(frame["real_volume"], errors="coerce")
            else:
                frame["volume"] = 0.0
            return frame[["open", "high", "low", "close", "volume"]].copy()
        finally:
            if initialized_here:
                mt5.shutdown()

    def _download_yahoo(self, symbol, interval):
        if interval == "15m":
            return yf.download(
                symbol, period="60d", interval=interval, progress=False, auto_adjust=False
            )
        if interval in ["1h", "30m"]:
            return yf.download(
                symbol, period="730d", interval=interval, progress=False, auto_adjust=False
            )
        return yf.download(symbol, start=LOOKBACK_DAYS, progress=False, auto_adjust=False)

    def _download(self, symbol, interval):
        if self.provider == "MT5":
            return self._download_mt5(symbol, interval)
        return self._download_yahoo(symbol, interval)

    def _cached_or_raise(self, symbol, timeframe, error=None, as_of=None):
        if not self.allow_cache_fallback:
            detail = f": {error}" if error is not None else ""
            raise HistoricalDataError(
                f"Fresh market data unavailable for {symbol}; "
                f"{self.execution_mode} forbids cached fallback{detail}"
            ) from error
        try:
            cached = self.history.load(symbol, timeframe)
            if as_of is not None:
                cutoff = normalize_timestamp(as_of, "as_of")
                cached = cached.loc[cached["close_time"] <= cutoff].copy()
                if cached.empty:
                    raise HistoricalDataError("No cached candles are available at as_of")
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

    def _assert_fresh(self, frame, symbol, timeframe):
        if frame.empty or "close_time" not in frame.columns:
            raise MarketDataFreshnessError(
                f"No completed candle timestamp available for {symbol}"
            )
        last_close = pd.Timestamp(frame["close_time"].iloc[-1])
        if last_close.tzinfo is None:
            last_close = last_close.tz_localize("UTC")
        else:
            last_close = last_close.tz_convert("UTC")
        now = pd.Timestamp(datetime.now(timezone.utc))
        maximum_age = timeframe_delta(timeframe) * self.max_stale_bars
        age = now - last_close
        if age < pd.Timedelta(0) or age > maximum_age:
            raise MarketDataFreshnessError(
                f"Stale {timeframe} data for {symbol}: last completed candle "
                f"closed {last_close.isoformat()} ({age} old; max {maximum_age})"
            )

    def download_data(self, symbol, interval=None, *, as_of=None, use_cache=True):
        timeframe = normalize_timeframe(interval or "1d")
        try:
            data = self._download(symbol, timeframe)
        except Exception as exc:
            if use_cache:
                return self._cached_or_raise(symbol, timeframe, exc, as_of=as_of)
            raise
        if data.empty:
            if use_cache:
                return self._cached_or_raise(symbol, timeframe, as_of=as_of)
            raise MarketDataError(f"No data found for {symbol}")
        data = self._align_provider_candles(data, timeframe)
        if data.empty:
            if use_cache:
                return self._cached_or_raise(symbol, timeframe, as_of=as_of)
            raise MarketDataError(f"No aligned candles found for {symbol}")
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        data.columns = [str(col).lower() for col in data.columns]
        required = ["open", "high", "low", "close", "volume"]
        missing = [col for col in required if col not in data.columns]
        if missing:
            raise MarketDataError(f"{symbol} missing columns: {missing}")
        data = data[required].copy()
        data.dropna(inplace=True)
        prepared = self.history.prepare(
            data,
            timeframe,
            as_of=as_of or pd.Timestamp.now(tz="UTC"),
        )
        if prepared.empty:
            if use_cache:
                return self._cached_or_raise(symbol, timeframe, as_of=as_of)
            raise MarketDataError(f"No completed candles found for {symbol}")
        if self.execution_mode == "MT5_DEMO":
            self._assert_fresh(prepared, symbol, timeframe)
        if self.cache_downloads:
            self.history.save(
                prepared, symbol, timeframe, source=self.provider.lower()
            )
        prepared.attrs["source"] = self.provider
        prepared.attrs["fresh"] = True
        return prepared

    def load_csv(self, path, interval, expected_version=None):
        return self.history.load_csv(path, interval, expected_version=expected_version)

    def download_all_data(self, interval=None):
        market_data = {}
        for category, symbols in SYMBOLS.items():
            for symbol in symbols:
                print(f"Downloading {symbol}...")
                try:
                    market_data[symbol] = self.download_data(symbol, interval)
                except Exception as exc:
                    logger.error(
                        "Fresh market data unavailable for %s %s: %s",
                        symbol,
                        normalize_timeframe(interval or "1d"),
                        exc,
                    )
                    print(f"{symbol} ERROR: {exc}")
        return market_data
