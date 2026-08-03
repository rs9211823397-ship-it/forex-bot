import json

import pytest

from paper.paper_trader import PaperTrader


def test_paper_trader_accepts_a_small_configured_balance(tmp_path):
    trader = PaperTrader(state_dir=tmp_path, starting_balance=100)

    assert trader.starting_balance == pytest.approx(100.0)
    assert trader.balance == pytest.approx(100.0)
    assert trader.equity == pytest.approx(100.0)


def test_paper_starting_balance_persists_with_the_ledger(tmp_path):
    trader = PaperTrader(state_dir=tmp_path, starting_balance=100)
    trader.balance = 103.5
    trader.save_trades()

    restored = PaperTrader(state_dir=tmp_path, starting_balance=999)

    assert restored.starting_balance == pytest.approx(100.0)
    assert restored.balance == pytest.approx(103.5)
    payload = json.loads((tmp_path / "trades.json").read_text(encoding="utf-8"))
    assert payload["starting_balance"] == pytest.approx(100.0)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_paper_trader_rejects_invalid_starting_balance(tmp_path, value):
    with pytest.raises(ValueError, match="starting balance"):
        PaperTrader(state_dir=tmp_path, starting_balance=value)
