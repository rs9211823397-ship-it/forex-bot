from telegram_bot import alert_monitor
from telegram_bot.alert_monitor import PositionSnapshot


def sample_position() -> PositionSnapshot:
    return PositionSnapshot(
        ticket=12345,
        symbol="EURUSD",
        side="BUY",
        volume=0.1,
        entry=1.1000,
        current=1.1010,
        stop_loss=1.0950,
        take_profit=1.1100,
        profit=10.0,
        opened_at=1_700_000_000,
        comment="AAQTS test",
    )


def test_subscriber_round_trip(tmp_path, monkeypatch):
    subscriber_file = tmp_path / "telegram_subscribers.json"
    monkeypatch.setattr(alert_monitor, "SUBSCRIBERS_FILE", subscriber_file)

    assert alert_monitor.load_subscribers() == set()
    assert alert_monitor.subscribe(1001) is True
    assert alert_monitor.subscribe(1001) is False
    assert alert_monitor.is_subscribed(1001) is True
    assert alert_monitor.unsubscribe(1001) is True
    assert alert_monitor.unsubscribe(1001) is False
    assert alert_monitor.load_subscribers() == set()


def test_open_alert_contains_trade_protection():
    text = alert_monitor.format_open_alert(sample_position())
    assert "TRADE OPENED" in text
    assert "EURUSD" in text
    assert "BUY" in text
    assert "Stop loss: 1.095" in text
    assert "Take profit: 1.11" in text
    assert "12345" in text


def test_close_alert_contains_result_and_reason():
    text = alert_monitor.format_close_alert(
        sample_position(),
        {
            "exit": 1.11,
            "profit": 100.0,
            "reason": "TAKE PROFIT",
            "closed_at": 1_700_003_600,
        },
    )
    assert "TRADE CLOSED" in text
    assert "TAKE PROFIT" in text
    assert "+$100.00" in text
    assert "1h 0m" in text


def test_daily_summary_format():
    text = alert_monitor.format_daily_summary(
        {
            "trades": 3,
            "wins": 2,
            "losses": 1,
            "win_rate": 66.666,
            "net_pnl": 75.0,
            "best": 100.0,
            "worst": -25.0,
            "open_positions": 1,
            "floating_pnl": 5.0,
            "balance": 100075.0,
            "equity": 100080.0,
        }
    )
    assert "DAILY SUMMARY" in text
    assert "66.7%" in text
    assert "+$75.00" in text
    assert "Open positions: 1" in text
