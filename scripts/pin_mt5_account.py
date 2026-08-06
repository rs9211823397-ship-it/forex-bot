#!/usr/bin/env python3
"""Pin the currently authenticated MT5 demo login to a local runtime file.

This script is intentionally local-only: it never prints the account login and
never writes it into source-controlled configuration. The trading engine then
uses the pinned numeric login as AAQTS_MT5_EXPECTED_LOGIN fallback and refuses
to start MT5_DEMO when no identity pin is present.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def main() -> None:
    from config.settings import MT5_EXPECTED_LOGIN_FILE, MT5_TERMINAL_PATH

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise SystemExit("[pin] ERROR: MetaTrader5 package is unavailable") from exc

    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise SystemExit(f"[pin] ERROR: MT5 initialization failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        if account is None:
            raise SystemExit("[pin] ERROR: MT5 account information is unavailable")
        demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        if getattr(account, "trade_mode", None) != demo_mode:
            raise SystemExit("[pin] ERROR: only a DEMO account may be pinned")
        login = int(getattr(account, "login", 0) or 0)
        if login <= 0:
            raise SystemExit("[pin] ERROR: connected account has no valid numeric login")
        path = Path(MT5_EXPECTED_LOGIN_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(str(login), encoding="utf-8")
        temp.replace(path)
        print(f"[pin] MT5 demo account identity pinned locally at {path}")
        print("[pin] Login value intentionally not displayed. Restart diagnostics/bot after pinning.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
