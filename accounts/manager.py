"""Isolated configuration and lifecycle control for multiple accounts."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Callable

from bot_controller import BotController

from accounts.safety import EmergencyStopStore


_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ACCOUNT_MODES = frozenset({"paper", "research", "live"})


@dataclass(frozen=True)
class AccountConfig:
    """Non-secret account configuration.

    Broker credentials are intentionally outside this object and must be
    supplied by a future deployment-specific secret provider.
    """

    account_id: str
    broker: str
    mode: str = "paper"
    currency: str = "USD"
    enabled: bool = True

    def __post_init__(self):
        if not isinstance(self.account_id, str) or not _ACCOUNT_ID.fullmatch(
            self.account_id
        ):
            raise ValueError(
                "account_id must be 1-64 safe alphanumeric/path characters"
            )
        if not isinstance(self.broker, str) or not self.broker.strip():
            raise ValueError("broker must be a non-empty string")
        normalized_mode = str(self.mode).strip().lower()
        if normalized_mode not in _ACCOUNT_MODES:
            raise ValueError(
                f"mode must be one of {sorted(_ACCOUNT_MODES)}"
            )
        object.__setattr__(self, "mode", normalized_mode)
        currency = str(self.currency).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        object.__setattr__(self, "currency", currency)
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")

    @classmethod
    def from_dict(cls, values: dict) -> "AccountConfig":
        allowed = {"account_id", "broker", "mode", "currency", "enabled"}
        unexpected = sorted(set(values) - allowed)
        if unexpected:
            raise ValueError(
                "Account config contains unsupported fields: "
                + ", ".join(unexpected)
            )
        return cls(**values)


@dataclass(frozen=True)
class AccountRuntime:
    """Read-only account lifecycle projection."""

    config: AccountConfig
    storage_dir: Path
    status: str


class AccountManager:
    """Own isolated controllers and data folders for configured accounts."""

    def __init__(
        self,
        state_root: str | Path,
        *,
        max_accounts: int = 100,
        controller_factory: Callable[[], BotController] = BotController,
        emergency_stop: EmergencyStopStore | None = None,
    ):
        if (
            isinstance(max_accounts, bool)
            or not isinstance(max_accounts, int)
            or max_accounts <= 0
        ):
            raise ValueError("max_accounts must be greater than zero")
        self.state_root = Path(state_root)
        self.max_accounts = int(max_accounts)
        self._controller_factory = controller_factory
        self._emergency_stop = emergency_stop
        self._accounts: dict[
            str,
            tuple[AccountConfig, BotController, Path],
        ] = {}

    @property
    def account_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._accounts))

    def register(self, config: AccountConfig) -> AccountRuntime:
        """Register an account idempotently and persist only public config."""

        existing = self._accounts.get(config.account_id)
        if existing is not None:
            if existing[0] != config:
                raise ValueError(
                    f"Account {config.account_id} is already registered "
                    "with different configuration"
                )
            return self.snapshot(config.account_id)
        if len(self._accounts) >= self.max_accounts:
            raise RuntimeError("Maximum configured account count reached")

        account_dir = self.state_root / "accounts" / config.account_id
        account_dir.mkdir(parents=True, exist_ok=True)
        self._write_config(account_dir / "config.json", config)
        self._accounts[config.account_id] = (
            config,
            self._controller_factory(),
            account_dir,
        )
        return self.snapshot(config.account_id)

    def load(self) -> tuple[AccountRuntime, ...]:
        """Load persisted public configurations in deterministic order."""

        accounts_root = self.state_root / "accounts"
        if not accounts_root.exists():
            return ()
        for config_path in sorted(accounts_root.glob("*/config.json")):
            values = json.loads(config_path.read_text(encoding="utf-8"))
            config = AccountConfig.from_dict(values)
            if config.account_id != config_path.parent.name:
                raise ValueError(
                    "Persisted account_id does not match its storage folder"
                )
            self.register(config)
        return tuple(self.snapshot(key) for key in self.account_ids)

    def start(self, account_id: str) -> str:
        config, controller, _ = self._get(account_id)
        if not config.enabled:
            return "ACCOUNT DISABLED"
        if self._emergency_stop is not None:
            state = self._emergency_stop.status()
            if state.active:
                return "BLOCKED BY EMERGENCY STOP"
        return controller.start_bot()

    def pause(self, account_id: str) -> str:
        return self._get(account_id)[1].pause_bot()

    def resume(self, account_id: str) -> str:
        if self._emergency_stop is not None:
            state = self._emergency_stop.status()
            if state.active:
                return "BLOCKED BY EMERGENCY STOP"
        return self._get(account_id)[1].resume_bot()

    def stop(self, account_id: str) -> str:
        return self._get(account_id)[1].stop_bot()

    def stop_all(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (account_id, self.stop(account_id))
            for account_id in self.account_ids
        )

    def snapshot(self, account_id: str) -> AccountRuntime:
        config, controller, account_dir = self._get(account_id)
        return AccountRuntime(
            config=config,
            storage_dir=account_dir,
            status=controller.status(),
        )

    def _get(
        self,
        account_id: str,
    ) -> tuple[AccountConfig, BotController, Path]:
        try:
            return self._accounts[account_id]
        except KeyError as exc:
            raise KeyError(f"Unknown account_id: {account_id}") from exc

    @staticmethod
    def _write_config(path: Path, config: AccountConfig):
        payload = json.dumps(
            asdict(config),
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
