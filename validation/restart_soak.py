"""Fail-closed comparison of AAQTS state before and after a worker restart."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _load(value):
    return dict(value) if isinstance(value, dict) else json.loads(Path(value).read_text(encoding="utf-8"))


def restart_soak_report(before, after) -> dict:
    left, right = _load(before), _load(after)
    left_status, right_status = left.get("runtime", {}), right.get("runtime", {})
    left_positions = left.get("positions", [])
    right_positions = right.get("positions", [])
    left_tickets = {int(item["ticket"]) for item in left_positions}
    right_tickets = {int(item["ticket"]) for item in right_positions}
    left_heartbeat = pd.to_datetime(left_status.get("heartbeat_utc"), utc=True, errors="coerce")
    right_heartbeat = pd.to_datetime(right_status.get("heartbeat_utc"), utc=True, errors="coerce")
    identity = str(left_status.get("risk_state_identity", "")).strip()
    checks = {
        "account_id_stable": left_status.get("account_id") == right_status.get("account_id"),
        "broker_login_stable": left_status.get("mt5_login") == right_status.get("mt5_login"),
        "broker_server_stable": str(left_status.get("mt5_server", "")).lower() == str(right_status.get("mt5_server", "")).lower(),
        "risk_baseline_stable": left_status.get("risk_baseline_utc") == right_status.get("risk_baseline_utc"),
        "risk_identity_stable": bool(identity) and identity == str(right_status.get("risk_state_identity", "")).strip(),
        "equity_peak_preserved": float(right_status.get("equity_peak", 0) or 0) + 1e-12 >= float(left_status.get("equity_peak", 0) or 0),
        "heartbeat_advanced": not pd.isna(left_heartbeat) and not pd.isna(right_heartbeat) and right_heartbeat > left_heartbeat,
        "engine_running": right_status.get("status") == "RUNNING",
        "managed_positions_preserved": left_tickets == right_tickets,
        "no_duplicate_tickets": len(right_tickets) == len(right_positions),
        "position_count_matches_runtime": len(right_positions) == int(right_status.get("open_positions", -1)),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "before_heartbeat_utc": None if pd.isna(left_heartbeat) else left_heartbeat.isoformat(),
        "after_heartbeat_utc": None if pd.isna(right_heartbeat) else right_heartbeat.isoformat(),
        "before_position_tickets": sorted(left_tickets),
        "after_position_tickets": sorted(right_tickets),
    }
