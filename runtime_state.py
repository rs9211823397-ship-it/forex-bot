"""Shared runtime heartbeat for AAQTS processes.

The trading engine writes a small JSON snapshot atomically. Independent
processes, such as the Telegram manager, read the snapshot to report the real
engine state instead of relying on their own in-memory BotController instance.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STATE_FILE = RUNTIME_DIR / "aaqts_status.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_runtime_state(**updates: Any) -> dict[str, Any]:
    """Merge and atomically persist the current AAQTS runtime snapshot."""
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
        os.replace(temp_name, STATE_FILE)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    return state


def read_runtime_state() -> dict[str, Any]:
    """Return the last valid runtime snapshot, or an empty mapping."""
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


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
