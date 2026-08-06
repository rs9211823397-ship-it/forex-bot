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


def _env_flag(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = values.get(name)
    if raw is None:
        return bool(default)
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class AccountCredentials:
    """Secrets held only in process memory."""

    password: str = ""
    bridge_token: str = ""
    terminal_path: str = ""
    use_preauthenticated_session: bool = False


@dataclass(frozen=True)
class CredentialReadiness:
    ready: bool
    missing: tuple[str, ...]


class EnvironmentCredentialProvider:
    """Resolve per-account secrets without persisting or logging their values.

    In single-account deployments the trading engine and Telegram manager must
    not require two independent copies of the same MT5 configuration.  For the
    currently managed ``AAQTS_ACCOUNT_ID`` this provider therefore falls back
    to the global engine MT5 settings.  If no password is present, it may use
    the already-authenticated terminal session; the snapshot reader still
    verifies that the returned MT5 login matches the registered account before
    exposing any account data.
    """

    def __init__(self, environ: Mapping[str, str] | None = None):
        self._environ = os.environ if environ is None else environ

    def _is_primary_runtime_account(self, account: TradingAccount) -> bool:
        runtime_account_id = self._environ.get("AAQTS_ACCOUNT_ID", "").strip().lower()
        return bool(runtime_account_id) and runtime_account_id == account.account_id.lower()

    def credentials(self, account: TradingAccount) -> AccountCredentials:
        prefix = account_env_prefix(account.account_id)
        primary_runtime_account = self._is_primary_runtime_account(account)

        account_password = self._environ.get(f"{prefix}_PASSWORD", "").strip()
        global_password = self._environ.get("AAQTS_MT5_PASSWORD", "").strip()
        password = account_password or (global_password if primary_runtime_account else "")

        account_terminal = self._environ.get(f"{prefix}_TERMINAL_PATH", "").strip()
        global_terminal = self._environ.get("AAQTS_MT5_TERMINAL_PATH", "").strip()
        terminal_path = (
            account_terminal
            or (global_terminal if primary_runtime_account else "")
            or str(account.terminal_path or "").strip()
        )

        explicit_preauth = _env_flag(
            self._environ,
            f"{prefix}_USE_PREAUTHENTICATED_SESSION",
        )
        # Safe only for the one runtime account. Multi-account readers continue
        # to require explicit per-account authentication unless opted in.
        use_preauthenticated_session = explicit_preauth or (
            primary_runtime_account and not password
        )

        return AccountCredentials(
            password=password,
            bridge_token=self._environ.get(f"{prefix}_BRIDGE_TOKEN", "").strip(),
            terminal_path=terminal_path,
            use_preauthenticated_session=use_preauthenticated_session,
        )

    def readiness(self, account: TradingAccount) -> CredentialReadiness:
        if account.platform is AccountPlatform.PAPER:
            return CredentialReadiness(True, ())

        values = self.credentials(account)
        prefix = account_env_prefix(account.account_id)
        missing: list[str] = []
        if account.platform is AccountPlatform.MT5:
            if not values.terminal_path:
                missing.append(f"{prefix}_TERMINAL_PATH")
            if not values.use_preauthenticated_session and not values.password:
                missing.append(f"{prefix}_PASSWORD")
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
