import pandas as pd

from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine


def _market_frame(rows=260):
    index = pd.date_range("2026-08-01T00:00:00Z", periods=rows, freq="15min")
    close = pd.Series(range(rows), index=index, dtype=float) / 1000.0 + 1.0
    frame = pd.DataFrame(
        {
            "open": close - 0.0002,
            "high": close + 0.0005,
            "low": close - 0.0005,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )
    frame.attrs["source"] = "MT5"
    frame.attrs["fresh"] = True
    return frame


def test_indicator_enrichment_preserves_mt5_provenance():
    raw = _market_frame()
    enriched = TechnicalIndicators().add_indicators(raw)

    assert enriched.attrs["source"] == "MT5"
    assert enriched.attrs["fresh"] is True


def test_preserved_metadata_keeps_telegram_style_analysis_on_production_path():
    raw = _market_frame()
    lower = TechnicalIndicators().add_indicators(raw)
    higher = _market_frame()
    engine = SignalEngine()

    assert engine._should_delegate_fresh_mt5_analysis(lower, higher) is True
