"""Persistent, non-secret registry for Telegram-managed trading accounts.

The registry deliberately stores connection metadata only. Trading passwords,
bridge tokens, and Telegram credentials are resolved at runtime by a separate
credential provider and must never be written to this file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

_ACCOUNT_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_LOGIN = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
_GROUP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,31}$")
_SENSITIVE_KEYS = frozenset({"password", "token", "secret", "api_key", "private_key"})


class AccountPlatform(str, Enum):
    PAPER = "PAPER"
    MT4 = "MT4"
    MT5 = "MT5"


class AccountEnvironment(str, Enum):
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"


@dataclass(frozen=True)
class TradingAccount:
    """Public account metadata suitable for menus, logs, and persistence."""

    account_id: str
    label: str
    broker: str
    platform: AccountPlatform | str
    environment: AccountEnvironment | str
    login: str
    server: str = ""
    currency: str = "USD"
    group: str = "DEFAULT"
    enabled: bool = True
    terminal_path: str = ""
    bridge_url: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not _ACCOUNT_ID.fullmatch(
            self.account_id
        ):
            raise ValueError(
                "account_id must contain 1-64 lowercase letters, numbers, or underscores"
            )
        label = str(self.label).strip()
        if not label or len(label) > 48:
            raise ValueError("label must contain 1-48 characters")
        object.__setattr__(self, "label", label)

        broker = str(self.broker).strip()
        if not broker or len(broker) > 48:
            raise ValueError("broker must contain 1-48 characters")
        object.__setattr__(self, "broker", broker)

        platform = (
            self.platform
            if isinstance(self.platform, AccountPlatform)
            else AccountPlatform(str(self.platform).upper().strip())
        )
        environment = (
            self.environment
            if isinstance(self.environment, AccountEnvironment)
            else AccountEnvironment(str(self.environment).upper().strip())
        )
        if platform is AccountPlatform.PAPER:
            if environment is not AccountEnvironment.PAPER:
                raise ValueError("PAPER platform requires PAPER environment")
        elif environment is AccountEnvironment.PAPER:
            raise ValueError("MT4/MT5 accounts must be DEMO or LIVE")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "environment", environment)

        login = str(self.login).strip()
        if not _LOGIN.fullmatch(login):
            raise ValueError("login contains unsupported characters")
        object.__setattr__(self, "login", login)

        server = str(self.server).strip()
        if platform in {AccountPlatform.MT4, AccountPlatform.MT5} and not server:
            raise ValueError("server is required for MT4/MT5 accounts")
        if len(server) > 128:
            raise ValueError("server must be at most 128 characters")
        object.__setattr__(self, "server", server)

        currency = str(self.currency).upper().strip()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        object.__setattr__(self, "currency", currency)

        group = str(self.group).upper().strip()
        if not _GROUP.fullmatch(group):
            raise ValueError("group contains unsupported characters")
        object.__setattr__(self, "group", group)

        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")

        terminal_path = str(self.terminal_path).strip()
        bridge_url = str(self.bridge_url).strip()
        if platform is AccountPlatform.MT4 and terminal_path and bridge_url:
            raise ValueError(
                "MT4 must use either terminal metadata or a bridge URL, not both"
            )
        if bridge_url:
            parsed_bridge = urlsplit(bridge_url)
            if parsed_bridge.username or parsed_bridge.password:
                raise ValueError("bridge_url cannot contain credentials")
            if parsed_bridge.scheme not in {"http", "https"}:
                raise ValueError("bridge_url must use HTTP or HTTPS")
            if parsed_bridge.scheme == "http" and parsed_bridge.hostname not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                raise ValueError("plain HTTP bridge_url must use a loopback host")
            if not parsed_bridge.hostname:
                raise ValueError("bridge_url must include a host")
        object.__setattr__(self, "terminal_path", terminal_path)
        object.__setattr__(self, "bridge_url", bridge_url.rstrip("/"))

    @property
    def callback_token(self) -> str:
        """Return a compact stable account reference for Telegram callbacks."""

        return hashlib.sha256(self.account_id.encode("utf-8")).hexdigest()[:12]

    @property
    def masked_login(self) -> str:
        if len(self.login) <= 4:
            return self.login
        return f"••••{self.login[-4:]}"

    @property
    def is_live(self) -> bool:
        return self.environment is AccountEnvironment.LIVE

    def as_public_dict(self) -> dict:
        values = asdict(self)
        values["platform"] = self.platform.value
        values["environment"] = self.environment.value
        return values

    @classmethod
    def from_dict(cls, values: dict) -> TradingAccount:
        if not isinstance(values, dict):
            raise TypeError("account record must be an object")
        lowered = {str(key).lower() for key in values}
        sensitive = sorted(lowered.intersection(_SENSITIVE_KEYS))
        if sensitive:
            raise ValueError(
                "account record contains sensitive fields: " + ", ".join(sensitive)
            )
        allowed = {
            "account_id",
            "label",
            "broker",
            "platform",
            "environment",
            "login",
            "server",
            "currency",
            "group",
            "enabled",
            "terminal_path",
            "bridge_url",
        }
        unexpected = sorted(set(values) - allowed)
        if unexpected:
            raise ValueError(
                "account record contains unsupported fields: " + ", ".join(unexpected)
            )
        return cls(**values)


class AccountRegistry:
    """Atomic JSON registry used by Telegram and account supervisors."""

    def __init__(self, path: str | Path, *, max_accounts: int = 100):
        if isinstance(max_accounts, bool) or int(max_accounts) <= 0:
            raise ValueError("max_accounts must be greater than zero")
        self.path = Path(path)
        self.max_accounts = int(max_accounts)
        self._lock = threading.RLock()

    def list_accounts(
        self,
        *,
        enabled_only: bool = False,
        group: str | None = None,
    ) -> tuple[TradingAccount, ...]:
        with self._lock:
            records = self._load()
        if enabled_only:
            records = [record for record in records if record.enabled]
        if group is not None:
            expected = str(group).upper().strip()
            records = [record for record in records if record.group == expected]
        return tuple(sorted(records, key=lambda item: item.account_id))

    def get(self, account_id: str) -> TradingAccount:
        for record in self.list_accounts():
            if record.account_id == account_id:
                return record
        raise KeyError(f"Unknown account_id: {account_id}")

    def resolve_token(self, token: str) -> TradingAccount:
        matches = [
            record for record in self.list_accounts() if record.callback_token == token
        ]
        if len(matches) != 1:
            raise KeyError("Unknown or ambiguous account callback token")
        return matches[0]

    def add(self, record: TradingAccount) -> TradingAccount:
        with self._lock:
            records = self._load()
            for existing in records:
                if existing.account_id == record.account_id:
                    if existing == record:
                        return existing
                    raise ValueError(f"Account {record.account_id} already exists")
                if (
                    existing.platform is record.platform
                    and existing.login == record.login
                    and existing.server.casefold() == record.server.casefold()
                ):
                    raise ValueError(
                        "The same platform/login/server account is already registered"
                    )
            if len(records) >= self.max_accounts:
                raise RuntimeError("Maximum configured account count reached")
            records.append(record)
            self._write(records)
        return record

    def replace(self, record: TradingAccount) -> TradingAccount:
        with self._lock:
            records = self._load()
            replaced = False
            updated: list[TradingAccount] = []
            for existing in records:
                if existing.account_id == record.account_id:
                    updated.append(record)
                    replaced = True
                else:
                    updated.append(existing)
            if not replaced:
                raise KeyError(f"Unknown account_id: {record.account_id}")
            self._write(updated)
        return record

    def set_enabled(self, account_id: str, enabled: bool) -> TradingAccount:
        current = self.get(account_id)
        values = current.as_public_dict()
        values["enabled"] = bool(enabled)
        return self.replace(TradingAccount.from_dict(values))

    def remove(self, account_id: str) -> TradingAccount:
        with self._lock:
            records = self._load()
            kept = [record for record in records if record.account_id != account_id]
            if len(kept) == len(records):
                raise KeyError(f"Unknown account_id: {account_id}")
            removed = next(
                record for record in records if record.account_id == account_id
            )
            self._write(kept)
        return removed

    def groups(self) -> tuple[str, ...]:
        return tuple(sorted({item.group for item in self.list_accounts()}))

    def _load(self) -> list[TradingAccount]:
        if not self.path.exists():
            return []
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Account registry is unavailable or invalid") from exc
        if not isinstance(values, dict) or values.get("version") != 1:
            raise RuntimeError("Unsupported account registry format")
        raw_accounts = values.get("accounts")
        if not isinstance(raw_accounts, list):
            raise TypeError("Account registry accounts must be a list")
        records = [TradingAccount.from_dict(item) for item in raw_accounts]
        identifiers = [item.account_id for item in records]
        if len(identifiers) != len(set(identifiers)):
            raise RuntimeError("Account registry contains duplicate account IDs")
        return records

    def _write(self, records: Iterable[TradingAccount]) -> None:
        ordered = sorted(records, key=lambda item: item.account_id)
        payload = {
            "version": 1,
            "accounts": [item.as_public_dict() for item in ordered],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f"{self.path.stem}_",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def select_accounts_for_mode(
    accounts: Iterable[TradingAccount],
    *,
    single_account_mode: bool,
    primary_account_id: str = "",
    enabled_only: bool = False,
) -> tuple[TradingAccount, ...]:
    """Select the fail-closed account scope for the configured UI/runtime mode.

    Single-account mode selects the explicit primary account when configured,
    otherwise it accepts exactly one registry record.  It never guesses between
    multiple existing accounts.
    """

    records = tuple(sorted(accounts, key=lambda item: item.account_id))
    if single_account_mode:
        selected_id = str(primary_account_id).strip().lower()
        if selected_id:
            matches = tuple(
                account for account in records if account.account_id == selected_id
            )
            if not matches:
                raise RuntimeError(
                    "AAQTS_PRIMARY_ACCOUNT_ID does not match a registered account"
                )
            records = matches
        elif len(records) > 1:
            raise RuntimeError(
                "Single-account mode found multiple registered accounts; set "
                "AAQTS_PRIMARY_ACCOUNT_ID"
            )
    if enabled_only:
        records = tuple(account for account in records if account.enabled)
    return records
