import pandas as pd

from structure.market_structure import MarketStructure


def structure_data():
    data = pd.DataFrame({
        "high": [
            1.10, 1.12, 1.15, 1.11, 1.18, 1.20, 1.16,
            1.22, 1.25, 1.21, 1.28, 1.30, 1.26, 1.32
        ],
        "low": [
            1.05, 1.08, 1.10, 1.06, 1.12, 1.15, 1.10,
            1.18, 1.20, 1.16, 1.22, 1.25, 1.21, 1.27
        ]
    })
    data["close"] = data["high"]
    return data


def test_structure_helpers_are_pytest_discoverable():
    data = structure_data()
    structure = MarketStructure(lookback=1)

    swing_highs, swing_lows = structure.find_swings(data)
    support_resistance = structure.support_resistance(data)

    assert swing_highs
    assert swing_lows
    assert structure.trend(data) == "BULLISH"
    assert support_resistance["support"][-1] == swing_lows[-1]["price"]
    assert (
        support_resistance["resistance"][-1]
        == swing_highs[-1]["price"]
    )
    assert structure.detect_bos(data) == "BULLISH BOS"
    assert structure.detect_choch(data) == "NO CHoCH"
