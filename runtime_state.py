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
