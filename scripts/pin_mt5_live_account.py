#!/usr/bin/env python3
"""Pin the currently authenticated REAL MT5 account locally without printing IDs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

LOGIN_FILE = REPO_ROOT / "runtime" / "mt5_live_expected_login.txt"
SERVER_FILE = REPO_ROOT / "runtime" / "mt5_live_expected_server.txt"


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(value, encoding="utf-8")
    temp.replace(path)


def main() -> None:
    from config.settings import MT5_TERMINAL_PATH

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise SystemExit("[live-pin] ERROR: MetaTrader5 package is unavailable") from exc

    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise SystemExit(f"[live-pin] ERROR: MT5 initialization failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        if account is None:
            raise SystemExit("[live-pin] ERROR: MT5 account information is unavailable")
        real_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2)
        if getattr(account, "trade_mode", None) != real_mode:
            raise SystemExit("[live-pin] ERROR: only a REAL account may be pinned")
        login = int(getattr(account, "login", 0) or 0)
        server = str(getattr(account, "server", "") or "").strip()
        if login <= 0 or not server:
            raise SystemExit("[live-pin] ERROR: connected REAL account identity is incomplete")
        _atomic_write(LOGIN_FILE, str(login))
        _atomic_write(SERVER_FILE, server)
        print(f"[live-pin] REAL MT5 identity pinned locally under {LOGIN_FILE.parent}")
        print("[live-pin] Login/server values intentionally not displayed or committed.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
