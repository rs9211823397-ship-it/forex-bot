"""Persistent broker-grounded audit trail for AAQTS MT5 demo trades."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config.settings import MT5_RISK_BASELINE_UTC
from execution.mt5_executor import ClosedPositionResult, ExecutionError


@dataclass(frozen=True)
class ManagedClosedDeal:
    closed_at: datetime
    profit_loss: float
    position_id: int
    deal_ticket: int
    symbol: str
    volume: float
    exit_price: float
    exit_reason: str
    broker_reason: int | None
    comment: str


class MT5TradeAudit:
    """Write deduplicated entry/exit records and classify broker exit origin.

    Broker exit deals may have magic=0. Ownership is therefore discovered from
    the opening deal's magic and retained by MT5 position_id for all exits.

    When an explicit demo risk baseline is configured, realized-risk queries
    ignore closes before that timestamp. This starts a fresh protection epoch
    without disabling daily/weekly loss, drawdown, or consecutive-loss guards.
    """

    HEADER = (
        "Event", "TimeUTC", "PositionID", "DealTicket", "Symbol", "Side",
        "Volume", "Price", "StopLoss", "TakeProfit", "PnL", "ExitReason",
        "BrokerReason", "Magic", "Comment",
    )

    def __init__(self, executor: Any, path: str | Path = "logs/trade_history.csv"):
        self.executor = executor
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            with self.path.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(self.HEADER)
            return
        try:
            with self.path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                fieldnames = tuple(reader.fieldnames or ())
                rows = list(reader)
        except OSError:
            return
        if fieldnames == self.HEADER:
            return
        # Older builds created a paper-style header but never wrote MT5 rows.
        # Replace that empty legacy schema; preserve any non-empty legacy data.
        if rows:
            legacy = self.path.with_suffix(self.path.suffix + ".legacy")
            counter = 1
            while legacy.exists():
                legacy = self.path.with_suffix(self.path.suffix + f".legacy{counter}")
                counter += 1
            self.path.replace(legacy)
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(self.HEADER)

    @staticmethod
    def _as_utc(value: datetime, field_name: str) -> datetime:
        if not isinstance(value, datetime):
            raise ExecutionError(f"{field_name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ExecutionError(f"{field_name} must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _apply_risk_baseline(start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
        baseline = MT5_RISK_BASELINE_UTC
        if baseline is None:
            return start, end
        if end < baseline:
            return None
        return max(start, baseline), end

    def _existing_keys(self) -> set[tuple[str, str, str]]:
        keys: set[tuple[str, str, str]] = set()
        try:
            with self.path.open("r", newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    keys.add((str(row.get("Event", "")), str(row.get("PositionID", "")), str(row.get("DealTicket", ""))))
        except OSError:
            return set()
        return keys

    def _append(self, row: dict[str, object]) -> None:
        key = (str(row.get("Event", "")), str(row.get("PositionID", "")), str(row.get("DealTicket", "")))
        if key in self._existing_keys():
            return
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.HEADER)
            writer.writerow({name: row.get(name, "") for name in self.HEADER})

    def record_entry(self, *, source_symbol: str, side: str, risk_plan: dict[str, float], result: Any, managed_position: Any = None) -> None:
        position_id = int(getattr(managed_position, "ticket", 0) or getattr(result, "position", 0) or getattr(result, "order", 0) or 0)
        broker_symbol = str(getattr(managed_position, "symbol", "")) or str(source_symbol)
        volume = float(getattr(managed_position, "initial_volume", 0.0) or 0.0)
        price = float(getattr(managed_position, "entry_price", 0.0) or 0.0)
        if price <= 0:
            price = float(risk_plan["entry"])
        self._append({
            "Event": "ENTRY", "TimeUTC": datetime.now(timezone.utc).isoformat(),
            "PositionID": position_id, "DealTicket": int(getattr(result, "deal", 0) or 0),
            "Symbol": broker_symbol, "Side": side, "Volume": volume, "Price": price,
            "StopLoss": float(getattr(managed_position, "initial_stop_loss", 0.0) or risk_plan["stop_loss"]),
            "TakeProfit": float(getattr(managed_position, "take_profit", 0.0) or risk_plan["take_profit"]),
            "PnL": 0.0, "ExitReason": "", "BrokerReason": "",
            "Magic": self.executor.config.magic, "Comment": f"AAQTS {source_symbol}",
        })

    def _reason_name(self, reason: int | None) -> str:
        if reason is None:
            return "UNKNOWN"
        mt5 = self.executor.mt5
        mapping = {
            getattr(mt5, "DEAL_REASON_SL", 4): "STOP_LOSS",
            getattr(mt5, "DEAL_REASON_TP", 5): "TAKE_PROFIT",
            getattr(mt5, "DEAL_REASON_EXPERT", 3): "BOT_MANAGED",
            getattr(mt5, "DEAL_REASON_CLIENT", 0): "MANUAL_DESKTOP",
            getattr(mt5, "DEAL_REASON_MOBILE", 1): "MANUAL_MOBILE",
            getattr(mt5, "DEAL_REASON_WEB", 2): "MANUAL_WEB",
            getattr(mt5, "DEAL_REASON_SO", 6): "STOP_OUT",
        }
        return mapping.get(int(reason), f"BROKER_REASON_{int(reason)}")

    def _history(self, start: datetime, end: datetime) -> list[Any]:
        deals = self.executor.mt5.history_deals_get(start, end)
        if deals is None:
            last_error = getattr(self.executor.mt5, "last_error", lambda: "unknown")()
            raise ExecutionError(f"MT5 deal history is unavailable: {last_error}")
        return list(deals)

    def managed_closed_deals(self, start_time: datetime, end_time: datetime) -> list[ManagedClosedDeal]:
        start = self._as_utc(start_time, "start_time")
        end = self._as_utc(end_time, "end_time")
        if end < start:
            raise ExecutionError("MT5 history end_time cannot precede start_time")
        bounded = self._apply_risk_baseline(start, end)
        if bounded is None:
            return []
        start, end = bounded
        # Discovery deliberately reaches before the baseline so an AAQTS
        # position opened earlier but closed after the baseline is still owned
        # correctly and its post-baseline realized PnL is counted.
        discovery_start = start - timedelta(days=30)
        deals = self._history(discovery_start, end)
        entry_values = {getattr(self.executor.mt5, "DEAL_ENTRY_IN", 0), getattr(self.executor.mt5, "DEAL_ENTRY_INOUT", 2)}
        exit_values = {getattr(self.executor.mt5, "DEAL_ENTRY_OUT", 1), getattr(self.executor.mt5, "DEAL_ENTRY_OUT_BY", 3)}
        managed_positions = {
            int(getattr(deal, "position_id", 0) or 0)
            for deal in deals
            if getattr(deal, "entry", None) in entry_values
            and getattr(deal, "magic", None) == self.executor.config.magic
            and int(getattr(deal, "position_id", 0) or 0) > 0
        }
        results: list[ManagedClosedDeal] = []
        for deal in deals:
            position_id = int(getattr(deal, "position_id", 0) or 0)
            if position_id not in managed_positions or getattr(deal, "entry", None) not in exit_values:
                continue
            timestamp = float(getattr(deal, "time", 0.0) or 0.0)
            if timestamp <= 0:
                continue
            closed_at = datetime.fromtimestamp(timestamp, timezone.utc)
            if not (start <= closed_at <= end):
                continue
            pnl = sum(float(getattr(deal, field_name, 0.0) or 0.0) for field_name in ("profit", "swap", "commission", "fee"))
            reason = getattr(deal, "reason", None)
            results.append(ManagedClosedDeal(
                closed_at=closed_at, profit_loss=pnl, position_id=position_id,
                deal_ticket=int(getattr(deal, "ticket", 0) or 0),
                symbol=str(getattr(deal, "symbol", "") or ""),
                volume=float(getattr(deal, "volume", 0.0) or 0.0),
                exit_price=float(getattr(deal, "price", 0.0) or 0.0),
                exit_reason=self._reason_name(reason),
                broker_reason=int(reason) if reason is not None else None,
                comment=str(getattr(deal, "comment", "") or ""),
            ))
        return sorted(results, key=lambda item: item.closed_at)

    def closed_position_results(self, start_time: datetime, end_time: datetime) -> list[ClosedPositionResult]:
        return [ClosedPositionResult(closed_at=item.closed_at, profit_loss=item.profit_loss) for item in self.managed_closed_deals(start_time, end_time)]

    def sync_closed(self, *, lookback_days: int = 30) -> list[ManagedClosedDeal]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(1, int(lookback_days)))
        results = self.managed_closed_deals(start, end)
        for item in results:
            self._append({
                "Event": "EXIT", "TimeUTC": item.closed_at.isoformat(),
                "PositionID": item.position_id, "DealTicket": item.deal_ticket,
                "Symbol": item.symbol, "Side": "", "Volume": item.volume,
                "Price": item.exit_price, "StopLoss": "", "TakeProfit": "",
                "PnL": item.profit_loss, "ExitReason": item.exit_reason,
                "BrokerReason": item.broker_reason if item.broker_reason is not None else "",
                "Magic": self.executor.config.magic, "Comment": item.comment,
            })
        return results


__all__ = ["MT5TradeAudit", "ManagedClosedDeal"]
