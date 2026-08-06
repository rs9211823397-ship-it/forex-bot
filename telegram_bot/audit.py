"""Append-only audit records for Telegram reads and control requests."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_SENSITIVE = ("password", "secret", "token", "credential", "api_key")


class TelegramAuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def write(
        self,
        event: str,
        *,
        user_id: int | None,
        role: str,
        account_ids: tuple[str, ...] = (),
        outcome: str = "OK",
        detail: dict[str, Any] | None = None,
    ) -> None:
        safe_detail = detail or {}
        for key in safe_detail:
            if any(term in str(key).lower() for term in _SENSITIVE):
                raise ValueError("Sensitive values cannot be written to audit log")
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": str(event),
            "user_id": user_id,
            "role": str(role),
            "account_ids": list(account_ids),
            "outcome": str(outcome),
            "detail": safe_detail,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with _LOCK, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def recent(self, limit: int = 10) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        with _LOCK:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return tuple(records)
