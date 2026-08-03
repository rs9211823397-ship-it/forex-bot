"""Validated, non-secret production configuration."""

from dataclasses import asdict, dataclass
import logging
from math import isfinite
import os
from pathlib import Path
from typing import Mapping


_ENVIRONMENTS = frozenset({"development", "staging", "production"})
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_LIVE_ACKNOWLEDGEMENT = "I_UNDERSTAND_LIVE_TRADING"
_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _parse_int(value: str, name: str) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if resolved <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return resolved


def _parse_float(value: str, name: str) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(resolved) or resolved <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return resolved


@dataclass(frozen=True)
class ProductionConfig:
    """Deployment settings that are safe to persist and report.

    Credentials and tokens are deliberately not represented.  Future live
    adapters must obtain them from a dedicated secret provider.
    """

    environment: str = "development"
    state_dir: Path = Path("state")
    log_dir: Path = Path("logs")
    log_level: str = "INFO"
    log_max_bytes: int = 10_000_000
    log_backup_count: int = 5
    max_accounts: int = 100
    max_gross_exposure: float = 1_000_000.0
    live_trading_enabled: bool = False

    def __post_init__(self):
        environment = str(self.environment).strip().lower()
        if environment not in _ENVIRONMENTS:
            raise ValueError(
                f"environment must be one of {sorted(_ENVIRONMENTS)}"
            )
        object.__setattr__(self, "environment", environment)

        for name in ("state_dir", "log_dir"):
            resolved = Path(getattr(self, name))
            if not str(resolved).strip():
                raise ValueError(f"{name} must be a non-empty path")
            object.__setattr__(self, name, resolved)

        level = str(self.log_level).strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError("log_level is not a valid logging level")
        object.__setattr__(self, "log_level", level)

        for name in (
            "log_max_bytes",
            "log_backup_count",
            "max_accounts",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"{name} must be greater than zero")

        if isinstance(self.max_gross_exposure, bool):
            raise ValueError(
                "max_gross_exposure must be finite and greater than zero"
            )
        maximum = float(self.max_gross_exposure)
        if not isfinite(maximum) or maximum <= 0:
            raise ValueError(
                "max_gross_exposure must be finite and greater than zero"
            )
        object.__setattr__(self, "max_gross_exposure", maximum)
        if not isinstance(self.live_trading_enabled, bool):
            raise TypeError("live_trading_enabled must be a boolean")

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ProductionConfig":
        """Load only the documented non-secret environment keys."""

        values = os.environ if environ is None else environ
        live_enabled = _parse_bool(
            values.get("FOREX_BOT_LIVE_TRADING", "false"),
            "FOREX_BOT_LIVE_TRADING",
        )
        if live_enabled and values.get(
            "FOREX_BOT_LIVE_ACKNOWLEDGEMENT"
        ) != _LIVE_ACKNOWLEDGEMENT:
            raise ValueError(
                "Live trading requires explicit safety acknowledgement"
            )

        return cls(
            environment=values.get(
                "FOREX_BOT_ENVIRONMENT",
                "development",
            ),
            state_dir=Path(values.get("FOREX_BOT_STATE_DIR", "state")),
            log_dir=Path(values.get("FOREX_BOT_LOG_DIR", "logs")),
            log_level=values.get("FOREX_BOT_LOG_LEVEL", "INFO"),
            log_max_bytes=_parse_int(
                values.get("FOREX_BOT_LOG_MAX_BYTES", "10000000"),
                "FOREX_BOT_LOG_MAX_BYTES",
            ),
            log_backup_count=_parse_int(
                values.get("FOREX_BOT_LOG_BACKUP_COUNT", "5"),
                "FOREX_BOT_LOG_BACKUP_COUNT",
            ),
            max_accounts=_parse_int(
                values.get("FOREX_BOT_MAX_ACCOUNTS", "100"),
                "FOREX_BOT_MAX_ACCOUNTS",
            ),
            max_gross_exposure=_parse_float(
                values.get(
                    "FOREX_BOT_MAX_GROSS_EXPOSURE",
                    "1000000",
                ),
                "FOREX_BOT_MAX_GROSS_EXPOSURE",
            ),
            live_trading_enabled=live_enabled,
        )

    def as_public_dict(self) -> dict:
        """Return a serialization containing no credential material."""

        values = asdict(self)
        values["state_dir"] = str(self.state_dir)
        values["log_dir"] = str(self.log_dir)
        return values
