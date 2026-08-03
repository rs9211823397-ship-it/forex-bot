import pandas as pd

from price_action.candles import CandlePatterns


def test_candle_pattern_analysis_is_pytest_discoverable():
    data = pd.DataFrame({
        "Open": [110, 100],
        "High": [112, 115],
        "Low": [98, 97],
        "Close": [100, 114]
    })

    patterns = CandlePatterns().analyze(data)

    assert patterns == ["STRONG BULLISH CANDLE"]
