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


def test_paper_pnl_uses_contract_size_spread_slippage_and_commission(tmp_path):
    trader = PaperTrader(state_dir=tmp_path, starting_balance=100)
    trade = trader.open_trade(
        "EURUSD=X",
        "BUY",
        entry=1.10000,
        stop_loss=1.09900,
        take_profit=1.10100,
        position=0.01,
    )

    assert trade["entry_reference"] == pytest.approx(1.10000)
    assert trade["entry"] == pytest.approx(1.10007)

    trader.update_equity({"EURUSD=X": 1.10100})
    assert trader.floating_pnl == pytest.approx(0.78)
    assert trader.equity == pytest.approx(100.78)

    trader.check_trade("EURUSD=X", 1.10100)
    assert trader.balance == pytest.approx(100.78)
    assert trader.closed_trades[0]["exit_reference"] == pytest.approx(1.10100)
    assert trader.closed_trades[0]["exit"] == pytest.approx(1.10092)
    assert trader.closed_trades[0]["pnl"] == pytest.approx(0.78)


def test_paper_mark_to_market_preserves_loss_direction(tmp_path):
    trader = PaperTrader(state_dir=tmp_path, starting_balance=100)
    trader.open_trade(
        "EURUSD=X",
        "BUY",
        entry=1.10000,
        stop_loss=1.09900,
        take_profit=1.10100,
        position=0.01,
    )

    trader.update_equity({"EURUSD=X": 1.09900})

    assert trader.floating_pnl == pytest.approx(-1.22)
    assert trader.equity == pytest.approx(98.78)
