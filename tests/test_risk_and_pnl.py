import unittest

from paper.paper_trader import PaperTrader
from risk.instrument_specs import get_instrument_spec
from risk.risk_manager import RiskManager


class RiskAndPnlTests(unittest.TestCase):
    def test_forex_position_size_respects_account_risk(self):
        manager = RiskManager(risk_percent=1)
        lots = manager.position_size(
            account_balance=1000,
            entry_price=1.10000,
            stop_loss=1.09900,
            symbol="EURUSD=X",
        )
        self.assertEqual(lots, 0.1)

    def test_gold_position_size_uses_contract_tick_value(self):
        manager = RiskManager(risk_percent=1)
        lots = manager.position_size(
            account_balance=1000,
            entry_price=2000.0,
            stop_loss=1999.0,
            symbol="GC=F",
        )
        self.assertEqual(lots, 0.1)

    def test_lot_size_is_rounded_down_to_step(self):
        spec = get_instrument_spec("BTC-USD")
        self.assertEqual(spec.normalize_lot(0.1239), 0.123)

    def test_forex_pnl_is_tick_aware(self):
        pnl = PaperTrader.calculate_pnl(
            "EURUSD=X", "BUY", 1.10000, 1.10100, 0.1
        )
        self.assertAlmostEqual(pnl, 10.0, places=4)

    def test_gold_pnl_is_tick_aware(self):
        pnl = PaperTrader.calculate_pnl(
            "GC=F", "SELL", 2000.0, 1999.0, 0.1
        )
        self.assertAlmostEqual(pnl, 10.0, places=4)

    def test_unknown_instrument_is_rejected(self):
        with self.assertRaises(ValueError):
            get_instrument_spec("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
