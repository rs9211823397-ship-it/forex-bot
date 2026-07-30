"""Live account dashboard metrics for the AAQTS Telegram manager."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from config.settings import EXECUTION_MODE, MT5_TERMINAL_PATH
from execution.mt5_executor import AAQTS_MAGIC


def _money(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _closed_position_results(deals: list[Any]) -> list[float]:
    """Aggregate closing deals by MT5 position id.

    MT5 can create more than one closing deal for a partially closed position, so
    dashboard win-rate calculations use one net result per position rather than
    counting every deal as a separate trade.
    """
    results: dict[int, float] = defaultdict(float)
    for deal in deals:
        position_id = int(getattr(deal, "position_id", 0) or 0)
        if not position_id:
            continue
        results[position_id] += (
            _money(getattr(deal, "profit", 0.0))
            + _money(getattr(deal, "swap", 0.0))
            + _money(getattr(deal, "commission", 0.0))
            + _money(getattr(deal, "fee", 0.0))
        )
    return list(results.values())


def mt5_dashboard_snapshot() -> dict[str, Any]:
    """Return live AAQTS account, daily-performance, and exposure metrics."""
    if EXECUTION_MODE != "MT5_DEMO":
        raise RuntimeError("The live dashboard currently requires MT5_DEMO mode.")

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package is not installed.") from exc

    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")

    try:
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("MT5 account information is unavailable.")

        positions = [
            position
            for position in list(mt5.positions_get() or [])
            if getattr(position, "magic", None) == AAQTS_MAGIC
        ]

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        history = list(mt5.history_deals_get(day_start, now) or [])
        closing_entries = {
            getattr(mt5, "DEAL_ENTRY_OUT", 1),
            getattr(mt5, "DEAL_ENTRY_OUT_BY", 3),
        }
        closed_deals = [
            deal
            for deal in history
            if getattr(deal, "magic", None) == AAQTS_MAGIC
            and getattr(deal, "entry", None) in closing_entries
        ]
        closed_results = _closed_position_results(closed_deals)

        wins = sum(result > 0 for result in closed_results)
        losses = sum(result < 0 for result in closed_results)
        breakeven = sum(result == 0 for result in closed_results)
        closed_count = len(closed_results)
        win_rate = (wins / closed_count * 100.0) if closed_count else 0.0
        realized_pnl = sum(closed_results)

        balance = _money(getattr(account, "balance", 0.0))
        equity = _money(getattr(account, "equity", 0.0))
        floating_pnl = sum(_money(getattr(position, "profit", 0.0)) for position in positions)
        drawdown = max(0.0, balance - equity)
        drawdown_pct = (drawdown / balance * 100.0) if balance > 0 else 0.0
        total_volume = sum(_money(getattr(position, "volume", 0.0)) for position in positions)
        symbols = sorted({str(getattr(position, "symbol", "Unknown")) for position in positions})
        margin = _money(getattr(account, "margin", 0.0))
        margin_free = _money(getattr(account, "margin_free", 0.0))
        margin_level = _money(getattr(account, "margin_level", 0.0))

        return {
            "as_of_utc": now.isoformat(),
            "balance": balance,
            "equity": equity,
            "account_profit": _money(getattr(account, "profit", 0.0)),
            "aaqts_floating_pnl": floating_pnl,
            "today_realized_pnl": realized_pnl,
            "today_net_pnl": realized_pnl + floating_pnl,
            "today_closed_trades": closed_count,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": win_rate,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
            "open_positions": len(positions),
            "total_volume": total_volume,
            "symbols": symbols,
            "margin": margin,
            "margin_free": margin_free,
            "margin_level": margin_level,
        }
    finally:
        mt5.shutdown()


def format_dashboard(snapshot: dict[str, Any]) -> str:
    """Format a compact Telegram dashboard message."""
    symbols = ", ".join(snapshot["symbols"]) if snapshot["symbols"] else "None"
    return (
        "📊 AAQTS LIVE DASHBOARD\n\n"
        "ACCOUNT\n"
        f"Balance: ${snapshot['balance']:,.2f}\n"
        f"Equity: ${snapshot['equity']:,.2f}\n"
        f"AAQTS floating P/L: ${snapshot['aaqts_floating_pnl']:,.2f}\n\n"
        "TODAY (UTC)\n"
        f"Closed trades: {snapshot['today_closed_trades']}\n"
        f"Wins / Losses / BE: {snapshot['wins']} / {snapshot['losses']} / {snapshot['breakeven']}\n"
        f"Win rate: {snapshot['win_rate']:.1f}%\n"
        f"Realized P/L: ${snapshot['today_realized_pnl']:,.2f}\n"
        f"Net P/L incl. open: ${snapshot['today_net_pnl']:,.2f}\n\n"
        "RISK & EXPOSURE\n"
        f"Current drawdown: ${snapshot['drawdown']:,.2f} ({snapshot['drawdown_pct']:.2f}%)\n"
        f"Open positions: {snapshot['open_positions']}\n"
        f"Total volume: {snapshot['total_volume']:.2f} lots\n"
        f"Symbols: {symbols}\n"
        f"Margin used: ${snapshot['margin']:,.2f}\n"
        f"Free margin: ${snapshot['margin_free']:,.2f}\n"
        f"Margin level: {snapshot['margin_level']:.2f}%"
    )
