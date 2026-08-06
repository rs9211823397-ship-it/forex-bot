import json
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram_bot import alert_monitor
from telegram_bot.alert_monitor import PositionSnapshot
from execution.mt5_executor import AAQTS_MAGIC


def sample_position() -> PositionSnapshot:
    return PositionSnapshot(ticket=12345, symbol="EURUSD", side="BUY", volume=0.1, entry=1.1000, current=1.1010, stop_loss=1.0950, take_profit=1.1100, profit=10.0, opened_at=1_700_000_000, comment="AAQTS test")


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
    assert "TRADE OPENED" in text and "EURUSD" in text and "BUY" in text
    assert "Stop loss: 1.095" in text and "Take profit: 1.11" in text and "12345" in text


def test_close_alert_contains_result_and_reason():
    text = alert_monitor.format_close_alert(sample_position(), {"exit": 1.11, "profit": 100.0, "reason": "TAKE PROFIT", "closed_at": 1_700_003_600})
    assert "TRADE CLOSED" in text and "TAKE PROFIT" in text and "+$100.00" in text and "1h 0m" in text


def test_daily_summary_format():
    text = alert_monitor.format_daily_summary({"trades": 3, "wins": 2, "losses": 1, "win_rate": 66.666, "net_pnl": 75.0, "best": 100.0, "worst": -25.0, "open_positions": 1, "floating_pnl": 5.0, "balance": 100075.0, "equity": 100080.0})
    assert "DAILY SUMMARY" in text and "66.7%" in text and "+$75.00" in text and "Open positions: 1" in text


def test_paper_alerts_read_open_close_and_daily_performance(tmp_path):
    opened_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat(); closed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    open_trade = {"symbol": "EURUSD=X", "signal": "BUY", "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12, "position": 0.01, "status": "OPEN", "pnl": 0.0, "opened_at": opened_at}
    closed_trade = {**open_trade, "status": "TAKE PROFIT", "exit": 1.12, "pnl": 2.5, "closed_at": closed_at}
    (tmp_path / "trades.json").write_text(json.dumps({"starting_balance": 100.0, "balance": 102.5, "open_trades": [open_trade], "closed_trades": [closed_trade]}), encoding="utf-8")
    runtime_path = tmp_path / "status.json"; runtime_path.write_text(json.dumps({"balance": 102.5, "equity": 103.0, "floating_pnl": 0.5}), encoding="utf-8")
    positions = alert_monitor.read_paper_positions(tmp_path); position = next(iter(positions.values()))
    assert len(positions) == 1 and position.symbol == "EURUSD=X" and position.comment == "AAQTS PAPER"
    details = alert_monitor.paper_closed_position_details(tmp_path, position)
    assert details["reason"] == "TAKE PROFIT" and details["profit"] == 2.5
    summary = alert_monitor.paper_daily_summary_snapshot(tmp_path, runtime_path)
    assert summary["trades"] == 1 and summary["wins"] == 1 and summary["net_pnl"] == 2.5
    assert summary["balance"] == 102.5 and summary["equity"] == 103.0 and summary["floating_pnl"] == 0.5


class FakeMT5:
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3
    DEAL_REASON_CLIENT = 0
    DEAL_REASON_MOBILE = 1
    DEAL_REASON_WEB = 2
    DEAL_REASON_EXPERT = 3
    DEAL_REASON_SL = 4
    DEAL_REASON_TP = 5
    DEAL_REASON_SO = 6
    POSITION_TYPE_BUY = 0

    def __init__(self, deals):
        self._deals = deals

    def history_deals_get(self, *_args): return tuple(self._deals)
    def positions_get(self): return ()
    def account_info(self): return SimpleNamespace(balance=100.0, equity=100.0)
    def shutdown(self): return None


def test_closed_alert_counts_magic_zero_exit_by_position_id(monkeypatch):
    opened = SimpleNamespace(position_id=12345, entry=0, magic=AAQTS_MAGIC, time=1_700_000_000, time_msc=1_700_000_000_000, price=1.10, profit=0.0, swap=0.0, commission=0.0, fee=0.0, reason=3)
    closed = SimpleNamespace(position_id=12345, entry=1, magic=0, time=1_700_003_600, time_msc=1_700_003_600_000, price=1.11, profit=2.5, swap=0.0, commission=-0.1, fee=0.0, reason=5)
    fake = FakeMT5([opened, closed]); monkeypatch.setattr(alert_monitor, "_connect_mt5", lambda: fake)
    details = alert_monitor.closed_position_details(sample_position())
    assert details["reason"] == "TAKE PROFIT"
    assert details["profit"] == 2.4
    assert details["exit"] == 1.11


def test_daily_summary_counts_magic_zero_exit_by_owned_position(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp())
    opened = SimpleNamespace(position_id=77, entry=0, magic=AAQTS_MAGIC, time=now - 3600, time_msc=(now - 3600) * 1000, price=1.10, profit=0.0, swap=0.0, commission=0.0, fee=0.0, reason=3)
    closed = SimpleNamespace(position_id=77, entry=1, magic=0, time=now - 60, time_msc=(now - 60) * 1000, price=1.11, profit=3.0, swap=0.0, commission=-0.2, fee=0.0, reason=5)
    fake = FakeMT5([opened, closed]); monkeypatch.setattr(alert_monitor, "_connect_mt5", lambda: fake)
    summary = alert_monitor.daily_summary_snapshot()
    assert summary["trades"] == 1
    assert summary["wins"] == 1
    assert summary["net_pnl"] == 2.8
