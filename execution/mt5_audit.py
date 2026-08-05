"""Broker-backed AAQTS trade ownership, exit classification, and CSV audit."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from execution.mt5_executor import AAQTS_MAGIC, ClosedPositionResult, ExecutionError


@dataclass(frozen=True)
class AuditDeal:
    ticket: int
    position_id: int
    event: str
    side: str
    symbol: str
    volume: float
    price: float
    profit_loss: float
    magic: int
    reason_code: int
    reason: str
    comment: str
    time_utc: datetime


class MT5TradeAuditor:
    """Reconcile AAQTS-owned broker deals without trusting exit-deal magic.

    Some brokers emit exit deals with magic=0 even when the opening deal was
    created by the EA. Ownership is therefore determined by position_id: if a
    position has an entry deal with AAQTS_MAGIC, all later exits for that same
    position belong to AAQTS for journaling and risk accounting.
    """

    FIELDNAMES = (
        "DealTicket",
        "PositionID",
        "Event",
        "Side",
        "Symbol",
        "Volume",
        "Price",
        "PnL",
        "Magic",
        "ReasonCode",
        "Reason",
        "Comment",
        "TimeUTC",
    )

    def __init__(
        self,
        executor,
        path: str | Path = "logs/trade_history.csv",
        ownership_lookback_days: int = 30,
    ) -> None:
        self.executor = executor
        self.path = Path(path)
        self.ownership_lookback_days = max(1, int(ownership_lookback_days))

    @property
    def mt5(self):
        return self.executor.mt5

    def _reason_name(self, reason_code: int) -> str:
        mt5 = self.mt5
        mapping = {
            getattr(mt5, "DEAL_REASON_CLIENT", 0): "MANUAL_DESKTOP",
            getattr(mt5, "DEAL_REASON_MOBILE", 1): "MANUAL_MOBILE",
            getattr(mt5, "DEAL_REASON_WEB", 2): "MANUAL_WEB",
            getattr(mt5, "DEAL_REASON_EXPERT", 3): "AAQTS_EXPERT",
            getattr(mt5, "DEAL_REASON_SL", 4): "STOP_LOSS",
            getattr(mt5, "DEAL_REASON_TP", 5): "TAKE_PROFIT",
            getattr(mt5, "DEAL_REASON_SO", 6): "STOP_OUT",
        }
        return mapping.get(int(reason_code), f"BROKER_REASON_{int(reason_code)}")

    def _side(self, deal: Any) -> str:
        deal_type = getattr(deal, "type", None)
        buy = getattr(self.mt5, "DEAL_TYPE_BUY", getattr(self.mt5, "ORDER_TYPE_BUY", 0))
        sell = getattr(self.mt5, "DEAL_TYPE_SELL", getattr(self.mt5, "ORDER_TYPE_SELL", 1))
        if deal_type == buy:
            return "BUY"
        if deal_type == sell:
            return "SELL"
        return "OTHER"

    @staticmethod
    def _pnl(deal: Any) -> float:
        return sum(
            float(getattr(deal, name, 0.0) or 0.0)
            for name in ("profit", "swap", "commission", "fee")
        )

    @staticmethod
    def _time(deal: Any) -> datetime:
        timestamp = float(getattr(deal, "time", 0.0) or 0.0)
        if timestamp <= 0:
            raise ExecutionError("MT5 deal has an invalid timestamp")
        return datetime.fromtimestamp(timestamp, timezone.utc)

    def _history(self, start: datetime, end: datetime) -> tuple[Any, ...]:
        deals = self.mt5.history_deals_get(start, end)
        if deals is None:
            raise ExecutionError(f"MT5 deal history is unavailable: {self.mt5.last_error()}")
        return tuple(deals)

    def owned_deals(self, start: datetime, end: datetime) -> tuple[AuditDeal, ...]:
        if not self.executor.connected:
            raise ExecutionError("MT5Executor is not connected")
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        ownership_start = start - timedelta(days=self.ownership_lookback_days)
        history = self._history(ownership_start, end)
        entry_code = getattr(self.mt5, "DEAL_ENTRY_IN", 0)
        exit_codes = {
            getattr(self.mt5, "DEAL_ENTRY_OUT", 1),
            getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3),
        }
        owned_positions = {
            int(getattr(deal, "position_id", 0) or 0)
            for deal in history
            if int(getattr(deal, "magic", 0) or 0) == int(AAQTS_MAGIC)
            and getattr(deal, "entry", None) == entry_code
            and int(getattr(deal, "position_id", 0) or 0) > 0
        }

        rows: list[AuditDeal] = []
        for deal in history:
            when = self._time(deal)
            if when < start or when > end:
                continue
            position_id = int(getattr(deal, "position_id", 0) or 0)
            entry = getattr(deal, "entry", None)
            is_owned_entry = (
                int(getattr(deal, "magic", 0) or 0) == int(AAQTS_MAGIC)
                and entry == entry_code
            )
            is_owned_exit = position_id in owned_positions and entry in exit_codes
            if not (is_owned_entry or is_owned_exit):
                continue
            reason_code = int(getattr(deal, "reason", -1) or 0)
            rows.append(
                AuditDeal(
                    ticket=int(getattr(deal, "ticket", 0) or 0),
                    position_id=position_id,
                    event="ENTRY" if entry == entry_code else "EXIT",
                    side=self._side(deal),
                    symbol=str(getattr(deal, "symbol", "") or ""),
                    volume=float(getattr(deal, "volume", 0.0) or 0.0),
                    price=float(getattr(deal, "price", 0.0) or 0.0),
                    profit_loss=self._pnl(deal),
                    magic=int(getattr(deal, "magic", 0) or 0),
                    reason_code=reason_code,
                    reason=self._reason_name(reason_code),
                    comment=str(getattr(deal, "comment", "") or ""),
                    time_utc=when,
                )
            )
        return tuple(sorted(rows, key=lambda row: (row.time_utc, row.ticket)))

    def realized_results(self, start: datetime, end: datetime) -> list[ClosedPositionResult]:
        results = []
        for row in self.owned_deals(start, end):
            if row.event != "EXIT":
                continue
            results.append(
                ClosedPositionResult(
                    closed_at=row.time_utc,
                    profit_loss=row.profit_loss,
                )
            )
        return results

    def _existing_tickets(self) -> set[int]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return set()
        try:
            with self.path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != self.FIELDNAMES:
                    # Legacy file was header-only in prior MT5_DEMO builds. If
                    # it has no rows, safely replace it with the audited schema.
                    rows = list(reader)
                    if not rows:
                        return set()
                    legacy = self.path.with_suffix(self.path.suffix + ".legacy")
                    if not legacy.exists():
                        self.path.replace(legacy)
                    return set()
                return {
                    int(row["DealTicket"])
                    for row in reader
                    if str(row.get("DealTicket", "")).strip().isdigit()
                }
        except (OSError, ValueError):
            return set()

    def reconcile(self, lookback_days: int = 30) -> tuple[AuditDeal, ...]:
        now = datetime.now(timezone.utc)
        rows = self.owned_deals(now - timedelta(days=max(1, int(lookback_days))), now)
        existing = self._existing_tickets()
        new_rows = [row for row in rows if row.ticket not in existing]
        if not new_rows:
            return ()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            if write_header:
                writer.writeheader()
            for row in new_rows:
                writer.writerow(
                    {
                        "DealTicket": row.ticket,
                        "PositionID": row.position_id,
                        "Event": row.event,
                        "Side": row.side,
                        "Symbol": row.symbol,
                        "Volume": f"{row.volume:.8f}",
                        "Price": f"{row.price:.10f}",
                        "PnL": f"{row.profit_loss:.2f}",
                        "Magic": row.magic,
                        "ReasonCode": row.reason_code,
                        "Reason": row.reason,
                        "Comment": row.comment,
                        "TimeUTC": row.time_utc.isoformat(),
                    }
                )
        return tuple(new_rows)
