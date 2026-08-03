import pandas as pd

from price_action.candles import CandlePatterns
from structure.market_structure import MarketStructure


def test_structure_and_candles_run_without_network():
    data = pd.DataFrame({
        "open": [
            1.06, 1.09, 1.11, 1.10, 1.13, 1.17, 1.14,
            1.19, 1.22, 1.20, 1.24, 1.28, 1.25, 1.29
        ],
        "high": [
            1.10, 1.12, 1.15, 1.11, 1.18, 1.20, 1.16,
            1.22, 1.25, 1.21, 1.28, 1.30, 1.26, 1.32
        ],
        "low": [
            1.05, 1.08, 1.10, 1.06, 1.12, 1.15, 1.10,
            1.18, 1.20, 1.16, 1.22, 1.25, 1.21, 1.27
        ],
        "close": [
            1.09, 1.11, 1.14, 1.08, 1.17, 1.19, 1.12,
            1.21, 1.24, 1.18, 1.27, 1.29, 1.23, 1.31
        ]
    })

    structure = MarketStructure(lookback=1)
    candles = CandlePatterns()

    assert structure.detect_trend(data) == "BULLISH"
    assert structure.detect_bos(data) == "BULLISH BOS"
    assert structure.detect_choch(data) == "NO CHoCH"
    assert isinstance(candles.analyze(data), list)
