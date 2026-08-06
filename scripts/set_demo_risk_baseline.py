"""Start a fresh MT5 demo risk-accounting epoch without disabling protections."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow direct execution as: python scripts/set_demo_risk_baseline.py
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import (
    EXECUTION_MODE,
    MT5_EXPECTED_LOGIN,
    MT5_RISK_BASELINE_FILE,
    MT5_TERMINAL_PATH,
)


def main() -> None:
    if EXECUTION_MODE != "MT5_DEMO":
        raise SystemExit("[baseline] ERROR: AAQTS_EXECUTION_MODE must be MT5_DEMO")

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise SystemExit("[baseline] ERROR: MetaTrader5 package is not installed") from exc

    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise SystemExit(f"[baseline] ERROR: MT5 initialize failed: {mt5.last_error()}")

    try:
        account = mt5.account_info()
        if account is None:
            raise SystemExit(f"[baseline] ERROR: MT5 account unavailable: {mt5.last_error()}")

        login = int(getattr(account, "login", 0) or 0)
        if login <= 0:
            raise SystemExit("[baseline] ERROR: MT5 account login is invalid")

        if MT5_EXPECTED_LOGIN and login != int(MT5_EXPECTED_LOGIN):
            raise SystemExit("[baseline] ERROR: connected MT5 login does not match pinned account")

        trade_mode = getattr(account, "trade_mode", None)
        demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        if trade_mode != demo_mode:
            raise SystemExit("[baseline] ERROR: connected MT5 account is not a demo account")

        baseline = datetime.now(timezone.utc).replace(microsecond=0)
        path = Path(MT5_RISK_BASELINE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(baseline.isoformat(), encoding="utf-8")

        print(f"[baseline] Fresh demo risk epoch started at {baseline.isoformat()}")
        print(f"[baseline] Saved locally at {path}")
        print("[baseline] Old realized AAQTS losses before this timestamp will not count toward new daily/weekly/consecutive-loss limits.")
        print("[baseline] Risk protections remain enabled. Restart diagnostics/bot now.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
