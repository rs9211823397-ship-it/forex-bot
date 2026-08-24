import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

import data.market_data as market_data_module
from data.historical import HistoricalDataError
from data.market_data import MarketData


def _frame():
    index = pd.date_range("2026-08-05T00:00:00Z", periods=4, freq="15min")
    return pd.DataFrame(
        {
            "open": [1.0, 1.1, 1.2, 1.3],
            "high": [1.1, 1.2, 1.3, 1.4],
            "low": [0.9, 1.0, 1.1, 1.2],
            "close": [1.05, 1.15, 1.25, 1.35],
            "volume": [10.0, 10.0, 10.0, 10.0],
        },
        index=index,
    )


def test_mt5_demo_never_falls_back_to_cached_candles(tmp_path):
    market = MarketData(
        cache_dir=tmp_path,
        execution_mode="MT5_DEMO",
        provider="MT5",
    )
    market.history.save(_frame(), "EURUSD=X", "15m", source="fixture")
    market._download = lambda *_args, **_kwargs: pd.DataFrame()

    with pytest.raises(HistoricalDataError, match="forbids cached fallback"):
        market.download_data("EURUSD=X", "15m")


def test_mt5_live_requires_broker_native_data_and_forbids_cache(tmp_path):
    with pytest.raises(ValueError, match="MT5_LIVE requires"):
        MarketData(
            cache_dir=tmp_path,
            execution_mode="MT5_LIVE",
            provider="YAHOO",
        )

    with pytest.raises(ValueError, match="forbids cached"):
        MarketData(
            cache_dir=tmp_path,
            execution_mode="MT5_LIVE",
            provider="MT5",
            allow_cache_fallback=True,
        )

    market = MarketData(
        cache_dir=tmp_path,
        execution_mode="MT5_LIVE",
        provider="MT5",
    )
    assert market.provider == "MT5"
    assert market.allow_cache_fallback is False


def test_paper_mode_may_use_cached_candles_after_provider_failure(tmp_path):
    market = MarketData(
        cache_dir=tmp_path,
        execution_mode="PAPER",
        provider="YAHOO",
    )
    market.history.save(_frame(), "EURUSD=X", "15m", source="fixture")
    market._download = lambda *_args, **_kwargs: pd.DataFrame()

    result = market.download_data("EURUSD=X", "15m")

    assert not result.empty
    assert float(result.iloc[-1]["close"]) == 1.35


def test_mt5_server_clock_is_normalized_before_causal_filtering(
    tmp_path,
    monkeypatch,
):
    actual_open = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)
    broker_open = actual_open.timestamp() + (3 * 60 * 60)
    fake_mt5 = SimpleNamespace(
        TIMEFRAME_M15=15,
        terminal_info=lambda: SimpleNamespace(),
        symbol_info=lambda _symbol: SimpleNamespace(visible=True),
        symbol_select=lambda *_args: True,
        copy_rates_from_pos=lambda *_args: [
            {
                "time": broker_open,
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "tick_volume": 10,
            }
        ],
        last_error=lambda: (1, "Success"),
    )
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)
    monkeypatch.setattr(
        market_data_module,
        "MT5_SERVER_UTC_OFFSET_MINUTES",
        180,
    )
    market = MarketData(
        cache_dir=tmp_path,
        execution_mode="MT5_LIVE",
        provider="MT5",
    )

    result = market._download_mt5("EURUSD=X", "15m")

    assert result.index[0] == actual_open
