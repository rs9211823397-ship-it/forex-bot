#!/usr/bin/env python3
"""Register non-secret WinProFX live metadata for the Telegram manager."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from accounts.registry import AccountRegistry, TradingAccount


def register_winprofx_live_account(
    *,
    runtime_dir: Path,
    account_id: str,
    login: str,
    server: str,
    terminal_path: str,
    currency: str = "USD",
) -> TradingAccount:
    registry = AccountRegistry(runtime_dir / "accounts_registry.json", max_accounts=100)
    record = TradingAccount(
        account_id=account_id,
        label="WinProFX Live",
        broker="WinProFX",
        platform="MT5",
        environment="LIVE",
        login=login,
        server=server,
        currency=currency,
        enabled=True,
        terminal_path=terminal_path,
    )

    # The deployed Telegram profile is explicitly single-account. Remove old
    # demo/live metadata so selection cannot silently fall back to Exness.
    for existing in registry.list_accounts():
        if existing.account_id != account_id:
            registry.remove(existing.account_id)

    try:
        registry.replace(record)
    except KeyError:
        registry.add(record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--account-id", default="winprofx_live")
    parser.add_argument("--login", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--terminal-path", required=True)
    parser.add_argument("--currency", default="USD")
    args = parser.parse_args()

    register_winprofx_live_account(
        runtime_dir=args.runtime_dir,
        account_id=args.account_id,
        login=args.login,
        server=args.server,
        terminal_path=args.terminal_path,
        currency=args.currency,
    )
    print("WINPROFX_LIVE_ACCOUNT_REGISTERED")


if __name__ == "__main__":
    main()
