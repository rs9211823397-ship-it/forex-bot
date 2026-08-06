"""Automatic Telegram alerts for AAQTS-managed MT5 trades.

The monitor compares broker-side positions between polls and reads MT5 deal
history when a managed position disappears. Closing deals are attributed by
MT5 position_id, because brokers may stamp the closing deal with magic=0 even
when the opening deal belongs to AAQTS.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

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
    try: amount = float(value)
    except (TypeError, ValueError): amount = 0.0
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
    temp.write_text(json.dumps({"chat_ids": sorted({int(chat_id) for chat_id in chat_ids})}, indent=2), encoding="utf-8")
    temp.replace(SUBSCRIBERS_FILE)


def subscribe(chat_id: int) -> bool:
    chat_ids = load_subscribers(); before = len(chat_ids); chat_ids.add(int(chat_id)); save_subscribers(chat_ids); return len(chat_ids) > before


def unsubscribe(chat_id: int) -> bool:
    chat_ids = load_subscribers(); existed = int(chat_id) in chat_ids; chat_ids.discard(int(chat_id)); save_subscribers(chat_ids); return existed


def is_subscribed(chat_id: int) -> bool:
    return int(chat_id) in load_subscribers()


def _connect_mt5() -> Any:
    try: import MetaTrader5 as mt5
    except ImportError as exc: raise RuntimeError("MetaTrader5 package is not installed.") from exc
    if not mt5.initialize(path=MT5_TERMINAL_PATH): raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    return mt5


def read_positions() -> dict[int, PositionSnapshot]:
    mt5 = _connect_mt5()
    try:
        positions = {}
        for position in list(mt5.positions_get() or []):
            if int(getattr(position, "magic", 0) or 0) != AAQTS_MAGIC: continue
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
    finally: mt5.shutdown()


def _paper_ledger(state_dir: str | Path) -> dict[str, Any]:
    path = Path(state_dir) / "trades.json"
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError: return {}
    except (OSError, json.JSONDecodeError) as exc: raise RuntimeError("Paper trade ledger is unreadable") from exc
    if not isinstance(payload, dict): raise RuntimeError("Paper trade ledger is invalid")
    return payload


def _paper_ticket(trade: dict[str, Any]) -> int:
    identity = {key: trade.get(key) for key in ("opened_at", "symbol", "signal", "entry", "stop_loss", "take_profit", "position")}
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


def _paper_time(value: Any) -> int:
    try: timestamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError): return 0
    if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=timezone.utc)
    return int(timestamp.timestamp())


def read_paper_positions(state_dir: str | Path) -> dict[int, PositionSnapshot]:
    positions = {}
    for trade in _paper_ledger(state_dir).get("open_trades", []):
        if not isinstance(trade, dict) or trade.get("status") != "OPEN": continue
        ticket = _paper_ticket(trade)
        positions[ticket] = PositionSnapshot(ticket=ticket, symbol=str(trade.get("symbol", "Unknown")), side=str(trade.get("signal", "UNKNOWN")).upper(), volume=float(trade.get("position", 0.0)), entry=float(trade.get("entry", 0.0)), current=float(trade.get("entry", 0.0)), stop_loss=float(trade.get("stop_loss", 0.0)), take_profit=float(trade.get("take_profit", 0.0)), profit=float(trade.get("pnl", 0.0)), opened_at=_paper_time(trade.get("opened_at")), comment="AAQTS PAPER")
    return positions


def paper_closed_position_details(state_dir: str | Path, position: PositionSnapshot) -> dict[str, Any]:
    for trade in _paper_ledger(state_dir).get("closed_trades", []):
        if isinstance(trade, dict) and _paper_ticket(trade) == position.ticket:
            return {"exit": float(trade.get("exit", position.current)), "profit": float(trade.get("pnl", position.profit)), "reason": str(trade.get("status", "CLOSED")), "closed_at": _paper_time(trade.get("closed_at"))}
    return {"exit": position.current, "profit": position.profit, "reason": "CLOSED", "closed_at": int(datetime.now(timezone.utc).timestamp())}


def paper_daily_summary_snapshot(state_dir: str | Path, runtime_state_path: str | Path | None = None) -> dict[str, Any]:
    ledger = _paper_ledger(state_dir); today = datetime.now(timezone.utc).date()
    trades = [trade for trade in ledger.get("closed_trades", []) if isinstance(trade, dict) and datetime.fromtimestamp(_paper_time(trade.get("closed_at")), tz=timezone.utc).date() == today]
    pnls = [float(trade.get("pnl", 0.0)) for trade in trades]
    wins = sum(1 for pnl in pnls if pnl > 0); losses = sum(1 for pnl in pnls if pnl < 0)
    runtime = {}
    if runtime_state_path is not None:
        try: runtime = json.loads(Path(runtime_state_path).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError): runtime = {}
    if not isinstance(runtime, dict): runtime = {}
    balance = float(runtime.get("balance", ledger.get("balance", 0.0))); equity = float(runtime.get("equity", balance)); floating = float(runtime.get("floating_pnl", equity - balance))
    return {"trades": len(pnls), "wins": wins, "losses": losses, "win_rate": (wins / len(pnls) * 100.0) if pnls else 0.0, "net_pnl": sum(pnls), "best": max(pnls, default=0.0), "worst": min(pnls, default=0.0), "open_positions": len(ledger.get("open_trades", [])), "floating_pnl": floating, "balance": balance, "equity": equity}


def _deal_reason(mt5: Any, deal: Any) -> str:
    reason = getattr(deal, "reason", None)
    mapping = {getattr(mt5, "DEAL_REASON_SL", -1001): "STOP LOSS", getattr(mt5, "DEAL_REASON_TP", -1002): "TAKE PROFIT", getattr(mt5, "DEAL_REASON_CLIENT", -1003): "MANUAL / CLIENT", getattr(mt5, "DEAL_REASON_MOBILE", -1004): "MANUAL / MOBILE", getattr(mt5, "DEAL_REASON_WEB", -1005): "MANUAL / WEB", getattr(mt5, "DEAL_REASON_EXPERT", -1006): "STRATEGY / EXPERT", getattr(mt5, "DEAL_REASON_SO", -1007): "STOP OUT"}
    return mapping.get(reason, "CLOSED")


def _entry_values(mt5: Any) -> set[int]:
    return {int(getattr(mt5, "DEAL_ENTRY_IN", 0)), int(getattr(mt5, "DEAL_ENTRY_INOUT", 2))}


def _exit_values(mt5: Any) -> set[int]:
    return {int(getattr(mt5, "DEAL_ENTRY_OUT", 1)), int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3))}


def _managed_position_ids(mt5: Any, deals: Iterable[Any]) -> set[int]:
    entries = _entry_values(mt5)
    return {int(getattr(deal, "position_id", 0) or 0) for deal in deals if int(getattr(deal, "entry", -1)) in entries and int(getattr(deal, "magic", 0) or 0) == AAQTS_MAGIC and int(getattr(deal, "position_id", 0) or 0) > 0}


def closed_position_details(position: PositionSnapshot) -> dict[str, Any]:
    mt5 = _connect_mt5()
    try:
        start = datetime.fromtimestamp(position.opened_at or 0, tz=timezone.utc) - timedelta(minutes=5)
        end = datetime.now(timezone.utc) + timedelta(minutes=1)
        deals = [deal for deal in list(mt5.history_deals_get(start, end) or []) if int(getattr(deal, "position_id", 0) or 0) == position.ticket]
        # The snapshot itself came from a magic-filtered AAQTS position. Still,
        # require either an AAQTS opening deal or the tracked snapshot ticket.
        managed = position.ticket in _managed_position_ids(mt5, deals)
        if not managed and not deals:
            return {"exit": position.current, "profit": position.profit, "reason": "CLOSED", "closed_at": int(datetime.now(timezone.utc).timestamp())}
        exit_deals = [deal for deal in deals if int(getattr(deal, "entry", -1)) in _exit_values(mt5)]
        chosen = max(exit_deals or deals, key=lambda deal: int(getattr(deal, "time_msc", 0) or 0), default=None)
        if chosen is None:
            return {"exit": position.current, "profit": position.profit, "reason": "CLOSED", "closed_at": int(datetime.now(timezone.utc).timestamp())}
        total_profit = sum(sum(float(getattr(deal, field, 0.0) or 0.0) for field in ("profit", "swap", "commission", "fee")) for deal in (exit_deals or [chosen]))
        return {"exit": float(getattr(chosen, "price", position.current)), "profit": total_profit, "reason": _deal_reason(mt5, chosen), "closed_at": int(getattr(chosen, "time", datetime.now(timezone.utc).timestamp()))}
    finally: mt5.shutdown()


def daily_summary_snapshot() -> dict[str, Any]:
    mt5 = _connect_mt5()
    try:
        account = mt5.account_info(); now = datetime.now(timezone.utc); start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        discovery_start = start - timedelta(days=30)
        all_deals = list(mt5.history_deals_get(discovery_start, now) or [])
        managed_ids = _managed_position_ids(mt5, all_deals)
        exits = [deal for deal in all_deals if int(getattr(deal, "position_id", 0) or 0) in managed_ids and int(getattr(deal, "entry", -1)) in _exit_values(mt5) and int(getattr(deal, "time", 0) or 0) >= int(start.timestamp())]
        per_position: dict[int, float] = {}
        for deal in exits:
            pid = int(getattr(deal, "position_id", 0) or 0)
            per_position[pid] = per_position.get(pid, 0.0) + sum(float(getattr(deal, field, 0.0) or 0.0) for field in ("profit", "swap", "commission", "fee"))
        pnls = list(per_position.values())
        positions = [p for p in list(mt5.positions_get() or []) if int(getattr(p, "magic", 0) or 0) == AAQTS_MAGIC]
        wins = sum(1 for pnl in pnls if pnl > 0); losses = sum(1 for pnl in pnls if pnl < 0)
        return {"trades": len(pnls), "wins": wins, "losses": losses, "win_rate": (wins / len(pnls) * 100.0) if pnls else 0.0, "net_pnl": sum(pnls), "best": max(pnls, default=0.0), "worst": min(pnls, default=0.0), "open_positions": len(positions), "floating_pnl": sum(float(getattr(p, "profit", 0.0) or 0.0) for p in positions), "balance": float(getattr(account, "balance", 0.0)) if account else 0.0, "equity": float(getattr(account, "equity", 0.0)) if account else 0.0}
    finally: mt5.shutdown()


def format_open_alert(position: PositionSnapshot) -> str:
    opened = datetime.fromtimestamp(position.opened_at, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "🟢 AAQTS TRADE OPENED\n\n" + f"Symbol: {position.symbol}\nSide: {position.side}\nVolume: {position.volume:g}\nEntry: {position.entry}\nStop loss: {position.stop_loss}\nTake profit: {position.take_profit}\nTicket: {position.ticket}\nOpened: {opened}\nComment: {position.comment or 'AAQTS'}"


def format_close_alert(position: PositionSnapshot, details: dict[str, Any]) -> str:
    profit = float(details.get("profit", 0.0)); emoji = "🎯" if profit > 0 else "🛑" if profit < 0 else "⚪"
    opened_at = datetime.fromtimestamp(position.opened_at, tz=timezone.utc); closed_at = datetime.fromtimestamp(int(details.get("closed_at", 0)), tz=timezone.utc)
    total_minutes = int(max(timedelta(0), closed_at - opened_at).total_seconds() // 60); duration_text = f"{total_minutes // 60}h {total_minutes % 60}m"
    return f"{emoji} AAQTS TRADE CLOSED\n\nSymbol: {position.symbol}\nSide: {position.side}\nEntry: {position.entry}\nExit: {details.get('exit', position.current)}\nResult: {money(profit)}\nReason: {details.get('reason', 'CLOSED')}\nDuration: {duration_text}\nTicket: {position.ticket}"


def format_daily_summary(snapshot: dict[str, Any]) -> str:
    return "📅 AAQTS DAILY SUMMARY (UTC)\n\n" + f"Closed trades: {snapshot['trades']}\nWins / Losses: {snapshot['wins']} / {snapshot['losses']}\nWin rate: {snapshot['win_rate']:.1f}%\nRealized P/L: {money(snapshot['net_pnl'])}\nBest trade: {money(snapshot['best'])}\nWorst trade: {money(snapshot['worst'])}\nOpen positions: {snapshot['open_positions']}\nFloating P/L: {money(snapshot['floating_pnl'])}\nBalance: {money(snapshot['balance'])}\nEquity: {money(snapshot['equity'])}"


class TradeAlertMonitor:
    def __init__(self, bot: Any, *, read_positions_fn: Callable[[], dict[int, PositionSnapshot]] = read_positions, closed_position_details_fn: Callable[[PositionSnapshot], dict[str, Any]] = closed_position_details, daily_summary_snapshot_fn: Callable[[], dict[str, Any]] = daily_summary_snapshot):
        self.bot = bot; self._read_positions = read_positions_fn; self._closed_position_details = closed_position_details_fn; self._daily_summary_snapshot = daily_summary_snapshot_fn
        self._positions: dict[int, PositionSnapshot] | None = None; self._last_summary_date: str | None = None; self._stopping = False

    async def stop(self) -> None: self._stopping = True

    async def _broadcast(self, text: str) -> None:
        for chat_id in load_subscribers():
            try: await self.bot.send_message(chat_id=chat_id, text=text)
            except Exception: logger.exception("Could not send alert to Telegram chat %s", chat_id)

    async def run(self) -> None:
        logger.info("AAQTS trade alert monitor started; polling every %ss", POLL_SECONDS)
        while not self._stopping:
            try:
                current = await asyncio.to_thread(self._read_positions)
                if self._positions is None: self._positions = current
                else:
                    opened_tickets = current.keys() - self._positions.keys(); closed_tickets = self._positions.keys() - current.keys()
                    for ticket in sorted(opened_tickets): await self._broadcast(format_open_alert(current[ticket]))
                    for ticket in sorted(closed_tickets):
                        old_position = self._positions[ticket]; details = await asyncio.to_thread(self._closed_position_details, old_position); await self._broadcast(format_close_alert(old_position, details))
                    self._positions = current
                now = datetime.now(timezone.utc); today = now.date().isoformat()
                if now.hour >= DAILY_SUMMARY_HOUR_UTC and self._last_summary_date != today:
                    snapshot = await asyncio.to_thread(self._daily_summary_snapshot); await self._broadcast(format_daily_summary(snapshot)); self._last_summary_date = today
            except asyncio.CancelledError: raise
            except Exception: logger.exception("Trade alert monitor iteration failed")
            await asyncio.sleep(POLL_SECONDS)
