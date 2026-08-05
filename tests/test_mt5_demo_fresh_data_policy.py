import pandas as pd
import pytest

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
    )
    market.history.save(_frame(), "EURUSD=X", "15m", source="fixture")
    market._download = lambda *_args, **_kwargs: pd.DataFrame()

    with pytest.raises(HistoricalDataError, match="forbids cached fallback"):
        market.download_data("EURUSD=X", "15m")


def test_paper_mode_may_use_cached_candles_after_provider_failure(tmp_path):
    market = MarketData(
        cache_dir=tmp_path,
        execution_mode="PAPER",
    )
    market.history.save(_frame(), "EURUSD=X", "15m", source="fixture")
    market._download = lambda *_args, **_kwargs: pd.DataFrame()

    result = market.download_data("EURUSD=X", "15m")

    assert not result.empty
    assert float(result.iloc[-1]["close"]) == 1.35
