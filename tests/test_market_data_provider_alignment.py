import pandas as pd

from data.historical import HistoricalDataStore
from data.market_data import MarketData


def _ohlcv(index):
    return pd.DataFrame(
        {
            "open": [100.0 + value for value in range(len(index))],
            "high": [101.0 + value for value in range(len(index))],
            "low": [99.0 + value for value in range(len(index))],
            "close": [100.5 + value for value in range(len(index))],
            "volume": [10.0] * len(index),
        },
        index=pd.DatetimeIndex(index),
    )


def test_provider_alignment_drops_partial_off_grid_hour():
    raw = _ohlcv(
        [
            "2026-08-04T00:00:00Z",
            "2026-08-04T01:00:00Z",
            "2026-08-04T01:30:00Z",
            "2026-08-04T02:00:00Z",
        ]
    )

    aligned = MarketData._align_provider_candles(raw, "1h")
    prepared = HistoricalDataStore().prepare(
        aligned,
        "1h",
        as_of="2026-08-04T03:00:00Z",
    )

    assert len(raw) == 4
    assert list(aligned.index) == list(
        pd.to_datetime(
            [
                "2026-08-04T00:00:00Z",
                "2026-08-04T01:00:00Z",
                "2026-08-04T02:00:00Z",
            ],
            utc=True,
        )
    )
    assert len(prepared) == 3


def test_provider_alignment_preserves_consistent_exchange_offset():
    raw = _ohlcv(
        [
            "2026-08-04T00:30:00Z",
            "2026-08-04T01:30:00Z",
            "2026-08-04T02:30:00Z",
        ]
    )

    aligned = MarketData._align_provider_candles(raw, "1h")

    assert len(aligned) == len(raw)
    HistoricalDataStore().prepare(
        aligned,
        "1h",
        as_of="2026-08-04T04:00:00Z",
    )
