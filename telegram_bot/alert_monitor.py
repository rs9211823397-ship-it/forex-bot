"""Automatic Telegram alerts for AAQTS-managed MT5 trades.

The monitor compares broker-side positions between polls and reads MT5 deal
history when a managed position disappears. Subscribed Telegram chat IDs are
persisted locally so alerts survive bot restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from config.settings import MT5_TERMINAL_PATH
from execution.mt5_executor import AAQTS_MAGIC

logger = logging.getLogger("aaqts.telegram.alerts")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUBSCRIBERS_FILE = PROJECT_ROOT / "runtime" / "telegram_subscribers.json"
POLL_SECONDS = max(10, int(os.getenv("TELEGRAM_ALERT_POLL_SECONDS", "20")))
DAILY_SUMMARY_HOUR_UTC = min(23, max(0, int(os.getenv("TELEGRAM_DAILY_SUMMARY_HOUR_UTC", "18"))))


@dataclass(frozen=True)
class PositionSnapshot:
    ticket: int
    symbol: str
    side: str
    volume: float
    entry: float
    current: float
    stop_loss: float
    take_profit: float
    profit: float
    opened_at: int
    comment: str


def money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    sign = "+" if amount > 0 else ""
    return f"{sign}${amount:,.2f}"


def load_subscribers() -> set[int]:
    try:
        payload = json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
        return {int(chat_id) for chat_id in payload.get("chat_ids", [])}
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return set()


def save_subscribers(chat_ids: Iterable[int]) -> None:
    SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = SUBSCRIBERS_FILE.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"chat_ids": sorted({int(chat_id) for chat_id in chat_ids})}, indent=2),
        encoding="utf-8",
    )
    temp.replace(SUBSCRIBERS_FILE)


def subscribe(chat_id: int) -> bool:
    chat_ids = load_subscribers()
    before = len(chat_ids)
    chat_ids.add(int(chat_id))
    save_subscribers(chat_ids)
    return len(chat_ids) > before


def unsubscribe(chat_id: int) -> bool:
    chat_ids = load_subscribers()
    existed = int(chat_id) in chat_ids
    chat_ids.discard(int(chat_id))
    save_subscribers(chat_ids)
    return existed


def is_subscribed(chat_id: int) -> bool:
    return int(chat_id) in load_subscribers()


def _connect_mt5() -> Any:
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package is not installed.") from exc
    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    return mt5


def read_positions() -> dict[int, PositionSnapshot]:
    mt5 = _connect_mt5()
    try:
        positions = {}
        for position in list(mt5.positions_get() or []):
            if getattr(position, "magic", None) != AAQTS_MAGIC:
                continue
            ticket = int(getattr(position, "ticket", 0))
            positions[ticket] = PositionSnapshot(
                ticket=ticket,
                symbol=str(getattr(position, "symbol", "Unknown")),
                side="BUY" if int(getattr(position, "type", 0)) == int(mt5.POSITION_TYPE_BUY) else "SELL",
                volume=float(getattr(position, "volume", 0.0)),
                entry=float(getattr(position, "price_open", 0.0)),
                current=float(getattr(position, "price_current", 0.0)),
                stop_loss=float(getattr(position, "sl", 0.0)),
                take_profit=float(getattr(position, "tp", 0.0)),
                profit=float(getattr(position, "profit", 0.0)),
                opened_at=int(getattr(position, "time", 0)),
                comment=str(getattr(position, "comment", "AAQTS")),
            )
        return positions
    finally:
        mt5.shutdown()


def _deal_reason(mt5: Any, deal: Any) -> str:
    reason = getattr(deal, "reason", None)
    mapping = {
        getattr(mt5, "DEAL_REASON_SL", -1001): "STOP LOSS",
        getattr(mt5, "DEAL_REASON_TP", -1002): "TAKE PROFIT",
        getattr(mt5, "DEAL_REASON_CLIENT", -1003): "MANUAL / CLIENT",
        getattr(mt5, "DEAL_REASON_MOBILE", -1004): "MANUAL / MOBILE",
        getattr(mt5, "DEAL_REASON_WEB", -1005): "MANUAL / WEB",
        getattr(mt5, "DEAL_REASON_EXPERT", -1006): "STRATEGY / EXPERT",
        getattr(mt5, "DEAL_REASON_SO", -1007): "STOP OUT",
    }
    return mapping.get(reason, "CLOSED")


def closed_position_details(position: PositionSnapshot) -> dict[str, Any]:
    mt5 = _connect_mt5()
    try:
        start = datetime.fromtimestamp(position.opened_at or 0, tz=timezone.utc) - timedelta(minutes=5)
        end = datetime.now(timezone.utc) + timedelta(minutes=1)
        deals = [
            deal
            for deal in list(mt5.history_deals_get(start, end) or [])
            if int(getattr(deal, "position_id", 0)) == position.ticket
            and int(getattr(deal, "magic", 0)) == AAQTS_MAGIC
        ]
        exit_deals = [
            deal for deal in deals
            if int(getattr(deal, "entry", -1)) in {
                int(getattr(mt5, "DEAL_ENTRY_OUT", 1)),
                int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)),
            }
        ]
        chosen = max(exit_deals or deals, key=lambda deal: int(getattr(deal, "time_msc", 0)), default=None)
        if chosen is None:
            return {
                "exit": position.current,
                "profit": position.profit,
                "reason": "CLOSED",
                "closed_at": int(datetime.now(timezone.utc).timestamp()),
            }
        total_profit = sum(
            float(getattr(deal, "profit", 0.0))
            + float(getattr(deal, "swap", 0.0))
            + float(getattr(deal, "commission", 0.0))
            + float(getattr(deal, "fee", 0.0))
            for deal in exit_deals or [chosen]
        )
        return {
            "exit": float(getattr(chosen, "price", position.current)),
            "profit": total_profit,
            "reason": _deal_reason(mt5, chosen),
            "closed_at": int(getattr(chosen, "time", datetime.now(timezone.utc).timestamp())),
        }
    finally:
        mt5.shutdown()


def daily_summary_snapshot() -> dict[str, Any]:
    mt5 = _connect_mt5()
    try:
        account = mt5.account_info()
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = [
            deal for deal in list(mt5.history_deals_get(start, now) or [])
            if int(getattr(deal, "magic", 0)) == AAQTS_MAGIC
            and int(getattr(deal, "entry", -1)) in {
                int(getattr(mt5, "DEAL_ENTRY_OUT", 1)),
                int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)),
            }
        ]
        pnls = [
            float(getattr(deal, "profit", 0.0))
            + float(getattr(deal, "swap", 0.0))
            + float(getattr(deal, "commission", 0.0))
            + float(getattr(deal, "fee", 0.0))
            for deal in deals
        ]
        positions = [
            p for p in list(mt5.positions_get() or [])
            if int(getattr(p, "magic", 0)) == AAQTS_MAGIC
        ]
        wins = sum(1 for pnl in pnls if pnl > 0)
        losses = sum(1 for pnl in pnls if pnl < 0)
        return {
            "trades": len(pnls),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(pnls) * 100.0) if pnls else 0.0,
            "net_pnl": sum(pnls),
            "best": max(pnls, default=0.0),
            "worst": min(pnls, default=0.0),
            "open_positions": len(positions),
            "floating_pnl": sum(float(getattr(p, "profit", 0.0)) for p in positions),
            "balance": float(getattr(account, "balance", 0.0)) if account else 0.0,
            "equity": float(getattr(account, "equity", 0.0)) if account else 0.0,
        }
    finally:
        mt5.shutdown()


def format_open_alert(position: PositionSnapshot) -> str:
    opened = datetime.fromtimestamp(position.opened_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        "🟢 AAQTS TRADE OPENED\n\n"
        f"Symbol: {position.symbol}\n"
        f"Side: {position.side}\n"
        f"Volume: {position.volume:g}\n"
        f"Entry: {position.entry}\n"
        f"Stop loss: {position.stop_loss}\n"
        f"Take profit: {position.take_profit}\n"
        f"Ticket: {position.ticket}\n"
        f"Opened: {opened}\n"
        f"Comment: {position.comment or 'AAQTS'}"
    )


def format_close_alert(position: PositionSnapshot, details: dict[str, Any]) -> str:
    profit = float(details.get("profit", 0.0))
    emoji = "🎯" if profit > 0 else "🛑" if profit < 0 else "⚪"
    opened_at = datetime.fromtimestamp(position.opened_at, tz=timezone.utc)
    closed_at = datetime.fromtimestamp(int(details.get("closed_at", 0)), tz=timezone.utc)
    duration = max(timedelta(0), closed_at - opened_at)
    total_minutes = int(duration.total_seconds() // 60)
    duration_text = f"{total_minutes // 60}h {total_minutes % 60}m"
    return (
        f"{emoji} AAQTS TRADE CLOSED\n\n"
        f"Symbol: {position.symbol}\n"
        f"Side: {position.side}\n"
        f"Entry: {position.entry}\n"
        f"Exit: {details.get('exit', position.current)}\n"
        f"Result: {money(profit)}\n"
        f"Reason: {details.get('reason', 'CLOSED')}\n"
        f"Duration: {duration_text}\n"
        f"Ticket: {position.ticket}"
    )


def format_daily_summary(snapshot: dict[str, Any]) -> str:
    return (
        "📅 AAQTS DAILY SUMMARY (UTC)\n\n"
        f"Closed trades: {snapshot['trades']}\n"
        f"Wins / Losses: {snapshot['wins']} / {snapshot['losses']}\n"
        f"Win rate: {snapshot['win_rate']:.1f}%\n"
        f"Realized P/L: {money(snapshot['net_pnl'])}\n"
        f"Best trade: {money(snapshot['best'])}\n"
        f"Worst trade: {money(snapshot['worst'])}\n"
        f"Open positions: {snapshot['open_positions']}\n"
        f"Floating P/L: {money(snapshot['floating_pnl'])}\n"
        f"Balance: {money(snapshot['balance'])}\n"
        f"Equity: {money(snapshot['equity'])}"
    )


class TradeAlertMonitor:
    def __init__(self, bot: Any):
        self.bot = bot
        self._positions: dict[int, PositionSnapshot] | None = None
        self._last_summary_date: str | None = None
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True

    async def _broadcast(self, text: str) -> None:
        for chat_id in load_subscribers():
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                logger.exception("Could not send alert to Telegram chat %s", chat_id)

    async def run(self) -> None:
        logger.info("AAQTS trade alert monitor started; polling every %ss", POLL_SECONDS)
        while not self._stopping:
            try:
                current = await asyncio.to_thread(read_positions)
                if self._positions is None:
                    # Baseline existing positions without replaying old open alerts.
                    self._positions = current
                else:
                    opened_tickets = current.keys() - self._positions.keys()
                    closed_tickets = self._positions.keys() - current.keys()
                    for ticket in sorted(opened_tickets):
                        await self._broadcast(format_open_alert(current[ticket]))
                    for ticket in sorted(closed_tickets):
                        old_position = self._positions[ticket]
                        details = await asyncio.to_thread(closed_position_details, old_position)
                        await self._broadcast(format_close_alert(old_position, details))
                    self._positions = current

                now = datetime.now(timezone.utc)
                today = now.date().isoformat()
                if now.hour >= DAILY_SUMMARY_HOUR_UTC and self._last_summary_date != today:
                    snapshot = await asyncio.to_thread(daily_summary_snapshot)
                    await self._broadcast(format_daily_summary(snapshot))
                    self._last_summary_date = today
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Trade alert monitor iteration failed")
            await asyncio.sleep(POLL_SECONDS)
