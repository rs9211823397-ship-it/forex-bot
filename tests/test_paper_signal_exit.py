from paper.paper_trader import PaperTrader


def test_paper_signal_lifecycle_ignores_zero_protection_and_closes_on_opposite(tmp_path):
    trader = PaperTrader(state_dir=tmp_path, starting_balance=1000.0)
    opened = trader.open_trade(
        "EURUSD=X",
        "BUY",
        entry=1.1000,
        stop_loss=0.0,
        take_profit=0.0,
        position=0.01,
    )

    trader.check_trade("EURUSD=X", 1.1010)
    assert opened in trader.open_trades

    assert trader.close_trade_on_signal(
        "EURUSD=X",
        "BUY",
        current_price=1.1010,
    ) is None
    closed = trader.close_trade_on_signal(
        "EURUSD=X",
        "SELL",
        current_price=1.1010,
    )

    assert closed is not None
    assert closed["status"] == "OPPOSITE SIGNAL"
    assert closed not in trader.open_trades
    assert closed in trader.closed_trades
    assert trader.get_stats()["total_trades"] == 1
