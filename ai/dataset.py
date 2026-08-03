"""Append-only research dataset contracts.

Decision-time snapshots and post-trade outcomes are persisted as different
event types.  Keeping them separate makes accidental label leakage visible and
allows future training pipelines to choose their join policy explicitly.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Iterator

from ai.features import (
    FEATURE_SCHEMA_V1,
    FeatureSchema,
    FeatureSnapshot,
    FeatureValidationError,
    SUPPORTED_FEATURE_SCHEMAS,
    normalize_timestamp,
    timestamp_text,
)


class DatasetValidationError(ValueError):
    """Raised when an append-only dataset contract is violated."""


@dataclass(frozen=True)
class TradeOutcome:
    """Post-trade label stored separately from decision-time features."""

    exit_time: datetime
    exit_reason: str
    profit_loss: float
    r_multiple: float

    def __post_init__(self):
        exit_time = normalize_timestamp(
            self.exit_time,
            field_name="exit_time",
        )
        object.__setattr__(self, "exit_time", exit_time)

        exit_reason = str(self.exit_reason).strip()
        if not exit_reason:
            raise DatasetValidationError("exit_reason cannot be empty")
        object.__setattr__(self, "exit_reason", exit_reason)

        for name in ("profit_loss", "r_multiple"):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise DatasetValidationError(
                    f"{name} must be numeric"
                ) from exc
            if not math.isfinite(value):
                raise DatasetValidationError(
                    f"{name} must be finite"
                )
            object.__setattr__(self, name, value)

    def to_record(self) -> dict:
        return {
            "exit_time": timestamp_text(self.exit_time),
            "exit_reason": self.exit_reason,
            "profit_loss": self.profit_loss,
            "r_multiple": self.r_multiple,
        }


@dataclass(frozen=True)
class DatasetEvent:
    """One immutable event in insertion order."""

    record_type: str
    trade_id: str
    snapshot: FeatureSnapshot | None = None
    outcome: TradeOutcome | None = None

    def __post_init__(self):
        trade_id = str(self.trade_id).strip()
        if not trade_id:
            raise DatasetValidationError("trade_id cannot be empty")
        object.__setattr__(self, "trade_id", trade_id)

        if self.record_type == "decision":
            if self.snapshot is None or self.outcome is not None:
                raise DatasetValidationError(
                    "A decision event must contain only a feature snapshot"
                )
        elif self.record_type == "outcome":
            if self.outcome is None or self.snapshot is not None:
                raise DatasetValidationError(
                    "An outcome event must contain only a trade outcome"
                )
        else:
            raise DatasetValidationError(
                "record_type must be decision or outcome"
            )

    def to_record(self) -> dict:
        if self.record_type == "decision":
            return {
                "record_type": "decision",
                "trade_id": self.trade_id,
                "snapshot": self.snapshot.to_record(),
            }
        return {
            "record_type": "outcome",
            "trade_id": self.trade_id,
            "outcome": self.outcome.to_record(),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_record(),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )


class AppendOnlyTradeDataset:
    """Collect immutable decision and outcome events deterministically."""

    def __init__(self, schema: FeatureSchema = FEATURE_SCHEMA_V1):
        if SUPPORTED_FEATURE_SCHEMAS.get(schema.version) != schema:
            raise DatasetValidationError(
                "Dataset schema is not registered by this application "
                "version"
            )
        self.schema = schema
        self._events: list[DatasetEvent] = []
        self._snapshots: dict[str, FeatureSnapshot] = {}
        self._outcomes: dict[str, TradeOutcome] = {}

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[DatasetEvent]:
        return iter(tuple(self._events))

    @property
    def completed_trade_count(self) -> int:
        return len(self._outcomes)

    def append_snapshot(
        self,
        trade_id: str,
        snapshot: FeatureSnapshot,
    ) -> DatasetEvent:
        trade_key = str(trade_id).strip()
        if trade_key in self._snapshots:
            raise DatasetValidationError(
                f"Decision for trade {trade_key!r} already exists"
            )
        if not isinstance(snapshot, FeatureSnapshot):
            raise DatasetValidationError(
                "snapshot must be a FeatureSnapshot"
            )
        if snapshot.schema_version != self.schema.version:
            raise DatasetValidationError(
                "Snapshot schema does not match the dataset schema"
            )

        event = DatasetEvent(
            record_type="decision",
            trade_id=trade_key,
            snapshot=snapshot,
        )
        self._snapshots[trade_key] = snapshot
        self._events.append(event)
        return event

    def append_outcome(
        self,
        trade_id: str,
        outcome: TradeOutcome,
    ) -> DatasetEvent:
        trade_key = str(trade_id).strip()
        snapshot = self._snapshots.get(trade_key)
        if snapshot is None:
            raise DatasetValidationError(
                "An outcome requires a previously appended decision"
            )
        if trade_key in self._outcomes:
            raise DatasetValidationError(
                f"Outcome for trade {trade_key!r} already exists"
            )
        if not isinstance(outcome, TradeOutcome):
            raise DatasetValidationError(
                "outcome must be a TradeOutcome"
            )
        if outcome.exit_time < snapshot.decision_time:
            raise DatasetValidationError(
                "exit_time cannot precede decision_time"
            )

        event = DatasetEvent(
            record_type="outcome",
            trade_id=trade_key,
            outcome=outcome,
        )
        self._outcomes[trade_key] = outcome
        self._events.append(event)
        return event

    def completed_records(self) -> tuple[dict, ...]:
        """Return nested research rows without merging labels into features."""

        records = []
        for event in self._events:
            if event.record_type != "decision":
                continue
            outcome = self._outcomes.get(event.trade_id)
            if outcome is None:
                continue
            records.append(
                {
                    "trade_id": event.trade_id,
                    "snapshot": event.snapshot.to_record(),
                    "outcome": outcome.to_record(),
                }
            )
        return tuple(records)

    @staticmethod
    def _exclusive_path(path) -> Path:
        output_path = Path(path)
        if output_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite append-only dataset {output_path}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def export_jsonl(self, path) -> Path:
        """Export immutable events in insertion order.

        Existing files are never overwritten.  Callers should use a new,
        versioned path for each export.
        """

        output_path = self._exclusive_path(path)
        with output_path.open("x", encoding="utf-8", newline="\n") as handle:
            for event in self._events:
                handle.write(event.to_json())
                handle.write("\n")
        return output_path

    def export_csv(self, path) -> Path:
        """Export events using one stable, schema-ordered column layout."""

        output_path = self._exclusive_path(path)
        feature_columns = tuple(
            f"feature.{name}" for name in self.schema.fields
        )
        columns = (
            "record_type",
            "trade_id",
            "schema_version",
            "decision_time",
            "symbol",
            "timeframe",
            "existing_direction",
            *feature_columns,
            "exit_time",
            "exit_reason",
            "profit_loss",
            "r_multiple",
        )

        with output_path.open(
            "x",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns,
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            for event in self._events:
                row = {name: "" for name in columns}
                row["record_type"] = event.record_type
                row["trade_id"] = event.trade_id

                if event.record_type == "decision":
                    snapshot = event.snapshot
                    row.update(
                        {
                            "schema_version": snapshot.schema_version,
                            "decision_time": timestamp_text(
                                snapshot.decision_time
                            ),
                            "symbol": snapshot.symbol,
                            "timeframe": snapshot.timeframe,
                            "existing_direction": (
                                snapshot.existing_direction
                            ),
                        }
                    )
                    for name, value in snapshot.ordered_values:
                        row[f"feature.{name}"] = (
                            "" if value is None else value
                        )
                else:
                    outcome = event.outcome
                    row.update(outcome.to_record())

                writer.writerow(row)
        return output_path


__all__ = [
    "AppendOnlyTradeDataset",
    "DatasetEvent",
    "DatasetValidationError",
    "FeatureValidationError",
    "TradeOutcome",
]
