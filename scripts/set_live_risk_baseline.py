#!/usr/bin/env python3
"""Start a fresh local risk-protection epoch for guarded MT5_LIVE deployment."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

BASELINE_FILE = REPO_ROOT / "runtime" / "mt5_live_risk_baseline_utc.txt"


def main() -> None:
    if os.getenv("AAQTS_EXECUTION_MODE", "").upper().strip() != "MT5_LIVE":
        raise SystemExit("[live-baseline] ERROR: AAQTS_EXECUTION_MODE must be MT5_LIVE")
    timestamp = datetime.now(timezone.utc).isoformat()
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = BASELINE_FILE.with_suffix(BASELINE_FILE.suffix + ".tmp")
    temp.write_text(timestamp, encoding="utf-8")
    temp.replace(BASELINE_FILE)
    print(f"[live-baseline] Fresh live risk baseline written locally at {BASELINE_FILE}")
    print("[live-baseline] Timestamp intentionally omitted from console output.")


if __name__ == "__main__":
    main()
