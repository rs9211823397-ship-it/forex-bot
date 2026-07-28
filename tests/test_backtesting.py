import math
import unittest

import pandas as pd

from backtesting.backtest_engine import BacktestCosts, BacktestEngine
from backtesting.performance import PerformanceReport


class BacktestEngineTests(unittest.TestCase):
    def test_take_profit_uses_intrabar_high_and_costs(self):
        data = pd.DataFrame(
            [
                {"close": 100.0, "high": 100.0, "low": 100.0, "ATR": 1.0, "ADX": 20.0},
                {"close": 101.0, "high": 104.0, "low": 100.5, "ATR": 1.0, "ADX": 20.0},
            ]
        )
        signals = ["BUY", "HOLD"]
        engine = BacktestEngine(
            data,
            lambda index: signals[index],
            initial_balance=10_000,
            position_size=2,
            costs=BacktestCosts(spread=0.2, slippage=0.05, commission_per_unit=0.5),
        )

        trades = engine.run()

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "TAKE_PROFIT")
        self.assertLess(trades[0]["net_pnl"], trades[0]["gross_pnl"])
        self.assertAlmostEqual(trades[0]["commission"], 2.0)

    def test_stop_loss_uses_intrabar_low(self):
        data = pd.DataFrame(
            [
                {"close": 100.0, "high": 100.0, "low": 100.0, "ATR": 1.0, "ADX": 20.0},
                {"close": 100.0, "high": 101.0, "low": 98.0, "ATR": 1.0, "ADX": 20.0},
            ]
        )
        engine = BacktestEngine(data, lambda index: ["BUY", "HOLD"][index])

        trades = engine.run()

        self.assertEqual(trades[0]["exit_reason"], "STOP_LOSS")
        self.assertLess(trades[0]["net_pnl"], 0)


class PerformanceReportTests(unittest.TestCase):
    def test_metrics_are_based_on_net_pnl(self):
        trades = [
            {"net_pnl": 100.0},
            {"net_pnl": -50.0},
            {"net_pnl": 25.0},
        ]
        report = PerformanceReport(trades, initial_balance=1_000)
        summary = report.summary()

        self.assertEqual(summary["Completed Trades"], 3)
        self.assertEqual(summary["Net Profit"], 75.0)
        self.assertEqual(summary["Profit Factor"], 2.5)
        self.assertGreater(summary["Max Drawdown"]["amount"], 0)
        self.assertFalse(math.isnan(summary["Sharpe Ratio"]))


if __name__ == "__main__":
    unittest.main()
