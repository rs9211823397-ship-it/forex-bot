"""Runtime-only credential resolution for registered trading accounts."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from accounts.registry import AccountPlatform, TradingAccount


def account_env_prefix(account_id: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]", "_", account_id).upper()
    return f"AAQTS_ACCOUNT_{suffix}"


@dataclass(frozen=True)
class AccountCredentials:
    """Secrets held only in process memory."""

    password: str = ""
    bridge_token: str = ""
    terminal_path: str = ""


@dataclass(frozen=True)
class CredentialReadiness:
    ready: bool
    missing: tuple[str, ...]


class EnvironmentCredentialProvider:
    """Resolve per-account secrets without persisting or logging their values."""

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = os.environ if environ is None else environ

    def credentials(self, account: TradingAccount) -> AccountCredentials:
        prefix = account_env_prefix(account.account_id)
        return AccountCredentials(
            password=self._environ.get(f"{prefix}_PASSWORD", "").strip(),
            bridge_token=self._environ.get(f"{prefix}_BRIDGE_TOKEN", "").strip(),
            terminal_path=self._environ.get(
                f"{prefix}_TERMINAL_PATH", account.terminal_path
            ).strip(),
        )

    def readiness(self, account: TradingAccount) -> CredentialReadiness:
        if account.platform is AccountPlatform.PAPER:
            return CredentialReadiness(True, ())

        values = self.credentials(account)
        prefix = account_env_prefix(account.account_id)
        missing: list[str] = []
        if account.platform is AccountPlatform.MT5:
            if not values.password:
                missing.append(f"{prefix}_PASSWORD")
            if not values.terminal_path:
                missing.append(f"{prefix}_TERMINAL_PATH")
        elif account.platform is AccountPlatform.MT4:
            if not account.bridge_url:
                missing.append("bridge_url")
            if not values.bridge_token:
                missing.append(f"{prefix}_BRIDGE_TOKEN")
        return CredentialReadiness(not missing, tuple(missing))

    def public_status(self, account: TradingAccount) -> dict[str, object]:
        readiness = self.readiness(account)
        return {
            "ready": readiness.ready,
            "missing": readiness.missing,
        }
