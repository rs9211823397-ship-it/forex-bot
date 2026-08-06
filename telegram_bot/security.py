"""Role-based authorization for the AAQTS Telegram control plane."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import IntEnum


class TelegramRole(IntEnum):
    VIEWER = 10
    OPERATOR = 20
    RISK_MANAGER = 30
    OWNER = 40


def _ids(value: str) -> frozenset[int]:
    resolved: set[int] = set()
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            resolved.add(int(token))
        except ValueError as exc:
            raise ValueError("Telegram user IDs must be integers") from exc
    return frozenset(resolved)


class TelegramAccessPolicy:
    """Numeric user-ID allowlist with monotonic roles."""

    def __init__(
        self,
        *,
        owners: frozenset[int] = frozenset(),
        risk_managers: frozenset[int] = frozenset(),
        operators: frozenset[int] = frozenset(),
        viewers: frozenset[int] = frozenset(),
    ):
        self.owners = owners
        self.risk_managers = risk_managers
        self.operators = operators
        self.viewers = viewers

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TelegramAccessPolicy:
        values = os.environ if environ is None else environ
        owners = _ids(values.get("TELEGRAM_OWNER_IDS", ""))
        # Backward-compatible single-user setup. In a private chat the chat ID
        # and user ID are identical, so the existing configuration stays usable.
        if not owners:
            owners = _ids(values.get("TELEGRAM_CHAT_ID", ""))
        return cls(
            owners=owners,
            risk_managers=_ids(values.get("TELEGRAM_RISK_MANAGER_IDS", "")),
            operators=_ids(values.get("TELEGRAM_OPERATOR_IDS", "")),
            viewers=_ids(values.get("TELEGRAM_VIEWER_IDS", "")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.owners or self.risk_managers or self.operators or self.viewers)

    def role_for(self, user_id: int | None) -> TelegramRole | None:
        if user_id is None:
            return None
        if user_id in self.owners:
            return TelegramRole.OWNER
        if user_id in self.risk_managers:
            return TelegramRole.RISK_MANAGER
        if user_id in self.operators:
            return TelegramRole.OPERATOR
        if user_id in self.viewers:
            return TelegramRole.VIEWER
        return None

    def allows(self, user_id: int | None, minimum_role: TelegramRole) -> bool:
        role = self.role_for(user_id)
        return role is not None and role >= minimum_role


READ_ROLE = TelegramRole.VIEWER
CONTROL_ROLE = TelegramRole.OPERATOR
RISK_ROLE = TelegramRole.RISK_MANAGER
OWNER_ROLE = TelegramRole.OWNER
