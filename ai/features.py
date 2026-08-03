"""Point-in-time feature contracts for research-only trade quality models.

This module deliberately does not calculate trading signals.  It serializes
facts which have already been calculated by causal production components and
rejects any input whose availability cannot be proven at ``decision_time``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from numbers import Integral, Real
import re
from types import MappingProxyType
from typing import Mapping, Sequence


FeatureValue = bool | float | int | str | None
FEATURE_SCHEMA_VERSION = "1.0.0"


class FeatureValidationError(ValueError):
    """Raised when a feature snapshot violates a point-in-time contract."""


_VERSION_PATTERN = re.compile(r"^[1-9]\d*\.\d+\.\d+$")
_RESERVED_OUTCOME_FIELDS = frozenset(
    {
        "actual_return",
        "exit",
        "exit_price",
        "exit_reason",
        "future",
        "label",
        "outcome",
        "pnl",
        "profit_loss",
        "realized_pnl",
        "result",
        "result_r",
        "trade_outcome",
        "win",
        "winner",
    }
)
_RESERVED_OUTCOME_PREFIXES = (
    "actual_",
    "exit_",
    "future_",
    "label_",
    "next_",
    "outcome_",
    "realized_",
    "result_",
)


def normalize_timestamp(value, *, field_name: str) -> datetime:
    """Return a comparable UTC timestamp or fail closed.

    Naive timestamps are interpreted as UTC for compatibility with the
    repository's historical data.  Aware timestamps are converted to UTC.
    """

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise FeatureValidationError(
                f"{field_name} must be an ISO-8601 timestamp"
            ) from exc

    if not isinstance(value, datetime):
        raise FeatureValidationError(
            f"{field_name} must be a datetime or ISO-8601 string"
        )

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)

    return value


def timestamp_text(value: datetime) -> str:
    """Serialize a normalized timestamp without locale-dependent formatting."""

    normalized = normalize_timestamp(value, field_name="timestamp")
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _is_outcome_field(name: str) -> bool:
    normalized = name.strip().lower()
    return normalized in _RESERVED_OUTCOME_FIELDS or normalized.startswith(
        _RESERVED_OUTCOME_PREFIXES
    )


def _canonical_value(value, *, name: str) -> FeatureValue:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, Integral):
        return int(value)

    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            raise FeatureValidationError(
                f"Feature {name!r} must be finite or None"
            )
        return number

    if isinstance(value, str):
        return value

    raise FeatureValidationError(
        f"Feature {name!r} has unsupported value type "
        f"{type(value).__name__}"
    )


@dataclass(frozen=True)
class FeatureSchema:
    """A versioned, ordered feature contract."""

    version: str
    fields: tuple[str, ...]
    missing_value: None = None

    def __post_init__(self):
        if not _VERSION_PATTERN.fullmatch(self.version):
            raise FeatureValidationError(
                "Schema version must use semantic version form, for example "
                "'1.0.0'"
            )

        if not self.fields:
            raise FeatureValidationError("A feature schema cannot be empty")

        if len(set(self.fields)) != len(self.fields):
            raise FeatureValidationError(
                "Feature schema fields must be unique"
            )

        for field in self.fields:
            if not isinstance(field, str) or not field.strip():
                raise FeatureValidationError(
                    "Feature schema fields must be non-empty strings"
                )
            if _is_outcome_field(field):
                raise FeatureValidationError(
                    f"Outcome field {field!r} is not allowed in a feature "
                    "schema"
                )


# The order is part of the persisted v1 contract.  New features require a new
# schema version; reordering these fields would silently corrupt model inputs.
FEATURE_SCHEMA_V1 = FeatureSchema(
    version=FEATURE_SCHEMA_VERSION,
    fields=(
        "market_regime",
        "htf_regime",
        "structure_trend",
        "protected_swing_high",
        "protected_swing_low",
        "setup",
        "trigger",
        "ema20",
        "ema50",
        "ema200",
        "atr",
        "adx",
        "rsi",
        "macd",
        "macd_histogram",
        "stochastic_rsi",
        "volatility_state",
        "volume",
        "timeframe_agreement",
        "quality_score",
        "risk_reward",
        "previous_trade_r",
    ),
)

SUPPORTED_FEATURE_SCHEMAS = MappingProxyType(
    {FEATURE_SCHEMA_V1.version: FEATURE_SCHEMA_V1}
)


@dataclass(frozen=True)
class FeatureSnapshot:
    """Immutable decision-time input for a future quality model.

    ``existing_direction`` is inherited from an already-qualified setup.  It
    is an input fact, not a prediction target.  ``available_at`` provides the
    audit trail proving that every upstream input was available by the
    decision timestamp.
    """

    schema_version: str
    decision_time: datetime
    symbol: str
    timeframe: str
    existing_direction: str
    ordered_values: tuple[tuple[str, FeatureValue], ...]
    available_at: tuple[tuple[str, datetime], ...]

    def __post_init__(self):
        schema = SUPPORTED_FEATURE_SCHEMAS.get(self.schema_version)
        if schema is None:
            raise FeatureValidationError(
                f"Unsupported feature schema {self.schema_version!r}"
            )

        decision_time = normalize_timestamp(
            self.decision_time,
            field_name="decision_time",
        )
        object.__setattr__(self, "decision_time", decision_time)

        symbol = str(self.symbol).strip().upper()
        timeframe = str(self.timeframe).strip()
        if not symbol:
            raise FeatureValidationError("symbol cannot be empty")
        if not timeframe:
            raise FeatureValidationError("timeframe cannot be empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timeframe", timeframe)

        direction = str(self.existing_direction).strip().upper()
        if direction not in {"BUY", "SELL"}:
            raise FeatureValidationError(
                "existing_direction must be BUY or SELL and must come from "
                "an existing setup"
            )
        object.__setattr__(self, "existing_direction", direction)

        names = tuple(name for name, _ in self.ordered_values)
        if names != schema.fields:
            raise FeatureValidationError(
                "Feature values do not match the registered schema order"
            )

        canonical_values = tuple(
            (name, _canonical_value(value, name=name))
            for name, value in self.ordered_values
        )
        object.__setattr__(self, "ordered_values", canonical_values)

        normalized_availability = []
        seen_sources = set()
        for source_name, source_time in self.available_at:
            name = str(source_name).strip()
            if not name:
                raise FeatureValidationError(
                    "Availability source names cannot be empty"
                )
            if name in seen_sources:
                raise FeatureValidationError(
                    f"Duplicate availability source {name!r}"
                )
            seen_sources.add(name)

            available_time = normalize_timestamp(
                source_time,
                field_name=f"available_at[{name}]",
            )
            if available_time > decision_time:
                raise FeatureValidationError(
                    f"Source {name!r} was not available at decision_time"
                )
            normalized_availability.append((name, available_time))

        if not normalized_availability:
            raise FeatureValidationError(
                "At least one point-in-time availability source is required"
            )

        normalized_availability.sort(key=lambda item: item[0])
        object.__setattr__(
            self,
            "available_at",
            tuple(normalized_availability),
        )

    @property
    def features(self):
        """Read-only feature mapping in the registered schema order."""

        return MappingProxyType(dict(self.ordered_values))

    def value(self, name: str) -> FeatureValue:
        try:
            return self.features[name]
        except KeyError as exc:
            raise FeatureValidationError(
                f"Unknown feature {name!r}"
            ) from exc

    def to_record(self) -> dict:
        """Return a deterministic, JSON-compatible decision record."""

        return {
            "schema_version": self.schema_version,
            "decision_time": timestamp_text(self.decision_time),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "existing_direction": self.existing_direction,
            "features": dict(self.ordered_values),
            "available_at": {
                name: timestamp_text(available_time)
                for name, available_time in self.available_at
            },
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_record(),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )


class PointInTimeFeatureExtractor:
    """Create snapshots only from explicitly time-bounded inputs."""

    def __init__(self, schema: FeatureSchema = FEATURE_SCHEMA_V1):
        registered = SUPPORTED_FEATURE_SCHEMAS.get(schema.version)
        if registered != schema:
            raise FeatureValidationError(
                "Feature schema is not registered by this application version"
            )
        self.schema = schema

    def extract(
        self,
        *,
        decision_time,
        symbol: str,
        timeframe: str,
        existing_direction: str,
        feature_values: Mapping[str, object],
        candle_close_times: Sequence[object] = (),
        confirmation_times: Mapping[str, object] | None = None,
        availability_times: Mapping[str, object] | None = None,
    ) -> FeatureSnapshot:
        """Build one immutable snapshot and enforce all availability bounds.

        Missing schema fields are represented by the schema's explicit
        ``None`` policy.  Unknown fields are rejected, and outcome/future
        fields receive a dedicated leakage error.
        """

        if not isinstance(feature_values, Mapping):
            raise FeatureValidationError(
                "feature_values must be a mapping"
            )

        supplied_names = set()
        for raw_name in feature_values:
            name = str(raw_name)
            if _is_outcome_field(name):
                raise FeatureValidationError(
                    f"Outcome or future field {name!r} cannot be used as a "
                    "decision-time feature"
                )
            supplied_names.add(name)

        unknown = supplied_names.difference(self.schema.fields)
        if unknown:
            raise FeatureValidationError(
                "Unknown feature fields: " + ", ".join(sorted(unknown))
            )

        ordered_values = tuple(
            (
                name,
                feature_values.get(name, self.schema.missing_value),
            )
            for name in self.schema.fields
        )

        available_at = {}
        for index, close_time in enumerate(candle_close_times):
            available_at[f"candle_close[{index}]"] = close_time

        for name, confirmed_time in (confirmation_times or {}).items():
            available_at[f"confirmed:{name}"] = confirmed_time

        for name, source_time in (availability_times or {}).items():
            source_name = f"source:{name}"
            if source_name in available_at:
                raise FeatureValidationError(
                    f"Duplicate availability source {source_name!r}"
                )
            available_at[source_name] = source_time

        return FeatureSnapshot(
            schema_version=self.schema.version,
            decision_time=decision_time,
            symbol=symbol,
            timeframe=timeframe,
            existing_direction=existing_direction,
            ordered_values=ordered_values,
            available_at=tuple(available_at.items()),
        )
