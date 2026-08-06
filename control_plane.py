"""Durable command spool between Telegram and trading-engine processes.

Each account receives its own queue. This avoids pretending that an in-memory
controller inside the Telegram process can control a separately running engine,
and it lets independently hosted account workers claim only their commands.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4


class ControlAction(str, Enum):
    PAUSE_ENTRIES = "PAUSE_ENTRIES"
    RESUME_ENTRIES = "RESUME_ENTRIES"
    STOP_ENGINE = "STOP_ENGINE"
    EMERGENCY_CLOSE = "EMERGENCY_CLOSE"


@dataclass(frozen=True)
class ControlRequest:
    request_id: str
    account_id: str
    action: ControlAction | str
    requested_by: int
    requested_at_utc: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", ControlAction(self.action))
        if not self.request_id or not self.account_id:
            raise ValueError("request_id and account_id are required")
        if not isinstance(self.requested_by, int):
            raise TypeError("requested_by must be an integer Telegram user ID")
        try:
            parsed = datetime.fromisoformat(self.requested_at_utc)
        except ValueError as exc:
            raise ValueError("requested_at_utc must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("requested_at_utc must be timezone-aware")
        reason = str(self.reason).strip()
        if not reason or len(reason) > 200:
            raise ValueError("reason must contain 1-200 characters")
        object.__setattr__(self, "reason", reason)

    def as_dict(self) -> dict:
        values = asdict(self)
        values["action"] = self.action.value
        return values

    @classmethod
    def from_dict(cls, values: dict) -> ControlRequest:
        return cls(**values)


class ControlCommandStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def submit(
        self,
        account_id: str,
        action: ControlAction | str,
        *,
        requested_by: int,
        reason: str,
    ) -> ControlRequest:
        request = ControlRequest(
            request_id=uuid4().hex,
            account_id=account_id,
            action=ControlAction(action),
            requested_by=requested_by,
            requested_at_utc=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )
        pending = self._directory(account_id, "pending")
        pending.mkdir(parents=True, exist_ok=True)
        self._write(pending / f"{request.request_id}.json", request.as_dict())
        return request

    def claim_next(self, account_id: str) -> ControlRequest | None:
        pending = self._directory(account_id, "pending")
        processing = self._directory(account_id, "processing")
        if not pending.exists():
            return None
        processing.mkdir(parents=True, exist_ok=True)
        for source in sorted(pending.glob("*.json")):
            target = processing / source.name
            try:
                os.replace(source, target)
            except (FileNotFoundError, OSError):
                continue
            try:
                values = json.loads(target.read_text(encoding="utf-8"))
                request = ControlRequest.from_dict(values)
                if request.account_id != account_id:
                    raise ValueError("Command account does not match queue")
                return request
            except Exception as exc:  # noqa: BLE001 - corrupt spool is quarantined
                self._finish_file(
                    target,
                    account_id,
                    "failed",
                    {"status": "FAILED", "error": str(exc)},
                )
        return None

    def complete(
        self,
        request: ControlRequest,
        *,
        result: str,
        success: bool = True,
    ) -> None:
        source = (
            self._directory(request.account_id, "processing")
            / f"{request.request_id}.json"
        )
        payload = request.as_dict()
        payload.update(
            {
                "status": "COMPLETED" if success else "FAILED",
                "result": str(result)[:500],
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._finish_file(
            source,
            request.account_id,
            "completed" if success else "failed",
            payload,
        )
        if success and request.action in {
            ControlAction.STOP_ENGINE,
            ControlAction.EMERGENCY_CLOSE,
        }:
            self._write(
                self._restart_block_path(request.account_id),
                {
                    "request_id": request.request_id,
                    "action": request.action.value,
                    "blocked_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )

    def restart_blocked(self, account_id: str) -> bool:
        return self._restart_block_path(account_id).exists()

    def clear_restart_block(self, account_id: str) -> bool:
        path = self._restart_block_path(account_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def recent(self, account_id: str, *, limit: int = 10) -> tuple[dict, ...]:
        files = []
        for state in ("completed", "failed", "pending", "processing"):
            folder = self._directory(account_id, state)
            files.extend(folder.glob("*.json") if folder.exists() else [])
        records: list[dict] = []
        dated_files = []
        for path in files:
            try:
                dated_files.append((path.stat().st_mtime, path))
            except FileNotFoundError:
                continue
        for _, path in sorted(dated_files)[-max(1, int(limit)) :]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                value = dict(value)
                value["queue_state"] = path.parent.name.upper()
                records.append(value)
        return tuple(records)

    def process_available(
        self,
        account_id: str,
        handler: Callable[[ControlRequest], str],
        *,
        maximum: int = 20,
    ) -> tuple[tuple[ControlRequest, str, bool], ...]:
        results = []
        for _ in range(maximum):
            request = self.claim_next(account_id)
            if request is None:
                break
            try:
                result = str(handler(request))
                success = True
            except Exception as exc:  # noqa: BLE001 - worker boundary records failure
                result = f"{type(exc).__name__}: {exc}"
                success = False
            self.complete(request, result=result, success=success)
            results.append((request, result, success))
        return tuple(results)

    def _finish_file(
        self,
        source: Path,
        account_id: str,
        state: str,
        payload: dict,
    ) -> None:
        destination_dir = self._directory(account_id, state)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        self._write(destination, payload)
        try:
            source.unlink()
        except FileNotFoundError:
            pass

    def _directory(self, account_id: str, state: str) -> Path:
        if not account_id or any(part in account_id for part in ("/", "\\", "..")):
            raise ValueError("Unsafe account_id for command queue")
        return self.root / account_id / state

    def _restart_block_path(self, account_id: str) -> Path:
        return self._directory(account_id, "state") / "restart_block.json"

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f"{path.stem}_",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
