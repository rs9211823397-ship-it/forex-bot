"""Persistent emergency stop and pre-execution exposure guard."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from math import isfinite
from pathlib import Path

from execution.models import require_utc_datetime


@dataclass(frozen=True)
class EmergencyStopState:
    """Durable emergency-stop projection."""

    active: bool
    reason: str | None
    changed_at: datetime | None


class EmergencyStopStore:
    """Persist the kill-switch state with atomic replacement."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def status(self) -> EmergencyStopState:
        if not self.path.exists():
            return EmergencyStopState(False, None, None)
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            changed_at = values.get("changed_at")
            timestamp = (
                datetime.fromisoformat(changed_at)
                if changed_at is not None
                else None
            )
            if timestamp is not None:
                require_utc_datetime(timestamp, "changed_at")
            return EmergencyStopState(
                active=bool(values["active"]),
                reason=values.get("reason"),
                changed_at=timestamp,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            # A corrupt or partial safety file must never enable execution.
            return EmergencyStopState(
                True,
                "EMERGENCY_STOP_STATE_INVALID",
                None,
            )

    def activate(
        self,
        reason: str,
        *,
        changed_at: datetime | None = None,
    ) -> EmergencyStopState:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Emergency-stop reason must be non-empty")
        timestamp = changed_at or datetime.now(timezone.utc)
        require_utc_datetime(timestamp, "changed_at")
        state = EmergencyStopState(True, reason.strip(), timestamp)
        self._write(state)
        return state

    def clear(
        self,
        *,
        changed_at: datetime | None = None,
    ) -> EmergencyStopState:
        timestamp = changed_at or datetime.now(timezone.utc)
        require_utc_datetime(timestamp, "changed_at")
        state = EmergencyStopState(False, None, timestamp)
        self._write(state)
        return state

    def _write(self, state: EmergencyStopState):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        values = asdict(state)
        values["changed_at"] = (
            state.changed_at.isoformat()
            if state.changed_at is not None
            else None
        )
        payload = json.dumps(
            values,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.path)


class ExposureAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class ExposureDecision:
    """Result from a non-signal-producing exposure check."""

    action: ExposureAction
    current_exposure: float
    proposed_exposure: float
    projected_exposure: float
    maximum_exposure: float
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action is ExposureAction.ALLOW


class MaxExposureGuard:
    """Block orders whose projected absolute gross exposure is too high."""

    def __init__(self, maximum_exposure: float):
        resolved = float(maximum_exposure)
        if not isfinite(resolved) or resolved <= 0:
            raise ValueError("maximum_exposure must be finite and positive")
        self.maximum_exposure = resolved

    def evaluate(
        self,
        current_exposure: float,
        proposed_exposure: float,
    ) -> ExposureDecision:
        current = float(current_exposure)
        proposed = float(proposed_exposure)
        if (
            not isfinite(current)
            or not isfinite(proposed)
            or current < 0
            or proposed < 0
        ):
            raise ValueError("Exposure inputs must be finite and non-negative")
        projected = current + proposed
        allowed = projected <= self.maximum_exposure
        return ExposureDecision(
            action=(
                ExposureAction.ALLOW
                if allowed
                else ExposureAction.BLOCK
            ),
            current_exposure=current,
            proposed_exposure=proposed,
            projected_exposure=projected,
            maximum_exposure=self.maximum_exposure,
            reason=(
                "WITHIN_MAX_EXPOSURE"
                if allowed
                else "MAX_EXPOSURE_EXCEEDED"
            ),
        )
