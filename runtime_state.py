"""Shared runtime heartbeat for AAQTS processes.

The trading engine writes a small JSON snapshot atomically. Independent
processes, such as the Telegram manager, read the snapshot to report the real
engine state instead of relying on their own in-memory BotController instance.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
_CONFIGURED_RUNTIME_DIR = os.getenv("AAQTS_RUNTIME_DIR", "").strip()
RUNTIME_DIR = (
    Path(_CONFIGURED_RUNTIME_DIR)
    if _CONFIGURED_RUNTIME_DIR
    else PROJECT_ROOT / "runtime"
)
if not RUNTIME_DIR.is_absolute():
    RUNTIME_DIR = PROJECT_ROOT / RUNTIME_DIR
RUNTIME_ACCOUNT_ID = os.getenv("AAQTS_ACCOUNT_ID", "primary").strip() or "primary"
_STATE_WRITE_LOCK = threading.RLock()


def runtime_state_file(
    account_id: str,
    runtime_dir: str | Path | None = None,
) -> Path:
    """Return the safe heartbeat path for one account worker."""

    normalized = str(account_id).strip() or "primary"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", normalized)
    root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
    return (
        root / "aaqts_status.json"
        if safe_id == "primary"
        else root / f"aaqts_status_{safe_id}.json"
    )


STATE_FILE = runtime_state_file(RUNTIME_ACCOUNT_ID)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_runtime_state(**updates: Any) -> dict[str, Any]:
    """Merge and atomically persist the current AAQTS runtime snapshot."""
    with _STATE_WRITE_LOCK:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        state = read_runtime_state()
        state.update(updates)
        state["heartbeat_utc"] = utc_now_iso()

        fd, temp_name = tempfile.mkstemp(
            prefix="aaqts_status_",
            suffix=".json",
            dir=RUNTIME_DIR,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
            for attempt in range(5):
                try:
                    os.replace(temp_name, STATE_FILE)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        return state


class EngineInstanceLock:
    """Cross-platform non-blocking lock for one account execution worker."""

    def __init__(
        self,
        account_id: str,
        runtime_dir: str | Path | None = None,
    ) -> None:
        safe_id = re.sub(
            r"[^A-Za-z0-9_.-]",
            "_",
            str(account_id).strip() or "primary",
        )
        root = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
        self.path = root / f"aaqts_engine_{safe_id}.lock"
        self._handle = None

    def acquire(self) -> "EngineInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise RuntimeError(
                f"AAQTS worker is already running for account {self.path.stem}"
            ) from exc
        self._handle = handle
        return self

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "EngineInstanceLock":
        return self.acquire()

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


@contextmanager
def engine_instance_lock(
    account_id: str,
    runtime_dir: str | Path | None = None,
):
    lock = EngineInstanceLock(account_id, runtime_dir)
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


def read_runtime_state() -> dict[str, Any]:
    """Return the last valid runtime snapshot, or an empty mapping."""
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def read_all_runtime_states() -> tuple[dict[str, Any], ...]:
    """Return every valid account-worker heartbeat in stable file order."""

    states = []
    for path in sorted(RUNTIME_DIR.glob("aaqts_status*.json")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            states.append(value)
    return tuple(states)


def heartbeat_is_fresh(state: dict[str, Any], max_age_seconds: int = 90) -> bool:
    """Return True when the trading-engine heartbeat is recent enough."""
    value = state.get("heartbeat_utc")
    if not value:
        return False
    try:
        heartbeat = datetime.fromisoformat(str(value))
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
        return 0 <= age <= max_age_seconds
    except (TypeError, ValueError):
        return False
