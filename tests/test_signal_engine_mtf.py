import unittest
from unittest.mock import Mock

import pandas as pd

from strategy.signal_engine import SignalEngine


class SignalEngineMtfTests(unittest.TestCase):
    def setUp(self):
        self.engine = SignalEngine()
        self.engine.candles = Mock()
        self.engine.market_structure = Mock()
        self.engine.mtf = Mock()
        self.engine.trade_quality = Mock()

        self.engine.candles.analyze.return_value = ["Bullish engulfing"]
        self.engine.market_structure.trend.return_value = "BULLISH"
        self.engine.market_structure.detect_bos.return_value = None
        self.engine.market_structure.detect_choch.return_value = None
        self.engine.trade_quality.evaluate.return_value = {
            "quality": 90,
            "approved": True,
        }

        self.data = pd.DataFrame([
            {
                "ADX": 35,
                "EMA_20": 3,
                "EMA_50": 2,
                "EMA_200": 1,
                "SUPERTREND": True,
                "MACD": 2,
                "MACD_SIGNAL": 1,
                "RSI": 60,
                "STOCH_RSI": 50,
                "volume": 100,
                "VOL_SMA20": 90,
                "OBV": 100,
            },
            {
                "ADX": 35,
                "EMA_20": 3,
                "EMA_50": 2,
                "EMA_200": 1,
                "SUPERTREND": True,
                "MACD": 2,
                "MACD_SIGNAL": 1,
                "RSI": 60,
                "STOCH_RSI": 50,
                "volume": 110,
                "VOL_SMA20": 90,
                "OBV": 110,
            },
        ])

    def test_opposite_higher_timeframe_rejects_buy(self):
        self.engine.mtf.analyze.return_value = {"confirmation": "SELL"}
        result = self.engine.generate_signal(self.data, "EURUSD=X", self.data)
        self.assertEqual(result["signal"], "HOLD")
        self.assertTrue(any("rejected BUY" in reason for reason in result["reasons"]))

    def test_matching_higher_timeframe_allows_buy(self):
        self.engine.mtf.analyze.return_value = {"confirmation": "BUY"}
        result = self.engine.generate_signal(self.data, "EURUSD=X", self.data)
        self.assertEqual(result["signal"], "BUY")


if __name__ == "__main__":
    unittest.main()
