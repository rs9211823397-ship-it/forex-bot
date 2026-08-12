from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ChartObserverConfig
from .schema import ChartAnalysis
from .snapshot import MarketSnapshot


class ChartObservationStore:
    """Persist reproducible Phase AI-1 evidence outside the execution path."""

    def __init__(self, config: ChartObserverConfig) -> None:
        self.config = config
        self.root = Path(config.output_root)
        self._index_lock = threading.Lock()

    def observation_dir(self, snapshot: MarketSnapshot) -> Path:
        day = snapshot.as_of_utc[:10]
        return self.root / day / snapshot.snapshot_id

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def write_input(
        self,
        snapshot: MarketSnapshot,
        *,
        deterministic: dict[str, Any],
        lower_image_name: str,
        higher_image_name: str,
    ) -> Path:
        directory = self.observation_dir(snapshot)
        payload = {
            "record_type": "AAQTS_AI_CHART_INPUT",
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "observer_mode": self.config.mode,
            "model": self.config.model,
            "prompt_version": self.config.prompt_version,
            "schema_version": self.config.schema_version,
            "snapshot": snapshot.to_dict(),
            # Comparison evidence only. The observer client never receives this
            # object, which keeps the model blind to the deterministic decision.
            "deterministic_comparison": dict(deterministic),
            "images": {
                "lower": str(lower_image_name),
                "higher": str(higher_image_name),
            },
        }
        self._write_json(directory / "input.json", payload)
        return directory

    def write_result(
        self,
        snapshot: MarketSnapshot,
        analysis: ChartAnalysis,
        *,
        deterministic: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Path:
        directory = self.observation_dir(snapshot)
        payload = {
            "record_type": "AAQTS_AI_CHART_RESULT",
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "prompt_version": self.config.prompt_version,
            "schema_version": self.config.schema_version,
            "snapshot_id": snapshot.snapshot_id,
            "analysis": analysis.to_dict(),
            "api": dict(metadata),
            "deterministic_comparison": dict(deterministic),
        }
        path = directory / "analysis.json"
        self._write_json(path, payload)
        self._append_index(
            {
                "status": "COMPLETED",
                "recorded_utc": payload["recorded_utc"],
                "snapshot_id": snapshot.snapshot_id,
                "symbol": snapshot.symbol,
                "as_of_utc": snapshot.as_of_utc,
                "ai_signal": analysis.signal,
                "ai_confidence": analysis.confidence,
                "ai_abstain": analysis.abstain,
                "deterministic_signal": str(
                    deterministic.get("signal")
                    or deterministic.get("strategy_signal")
                    or "UNKNOWN"
                ),
                "deterministic_confidence": deterministic.get("confidence"),
                "prompt_version": self.config.prompt_version,
                "schema_version": self.config.schema_version,
                "model": metadata.get("model", self.config.model),
            }
        )
        return path

    def write_error(
        self,
        *,
        error_message: str,
        snapshot: MarketSnapshot | None = None,
        symbol: str | None = None,
        deterministic: dict[str, Any] | None = None,
    ) -> Path:
        recorded = datetime.now(timezone.utc)
        if snapshot is not None:
            directory = self.observation_dir(snapshot)
            snapshot_id = snapshot.snapshot_id
            resolved_symbol = snapshot.symbol
            as_of_utc = snapshot.as_of_utc
        else:
            directory = self.root / recorded.date().isoformat() / "_errors"
            snapshot_id = None
            resolved_symbol = str(symbol or "UNKNOWN")
            as_of_utc = None

        payload = {
            "record_type": "AAQTS_AI_CHART_ERROR",
            "recorded_utc": recorded.isoformat(),
            "snapshot_id": snapshot_id,
            "symbol": resolved_symbol,
            "as_of_utc": as_of_utc,
            "error": str(error_message)[:2000],
            "prompt_version": self.config.prompt_version,
            "schema_version": self.config.schema_version,
            "model": self.config.model,
            "deterministic_comparison": dict(deterministic or {}),
        }
        filename = "error.json" if snapshot is not None else f"{recorded.strftime('%H%M%S_%f')}.json"
        path = directory / filename
        self._write_json(path, payload)
        self._append_index(
            {
                "status": "ERROR",
                "recorded_utc": payload["recorded_utc"],
                "snapshot_id": snapshot_id,
                "symbol": resolved_symbol,
                "as_of_utc": as_of_utc,
                "error": payload["error"],
                "prompt_version": self.config.prompt_version,
                "schema_version": self.config.schema_version,
                "model": self.config.model,
            }
        )
        return path

    def _append_index(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
        with self._index_lock:
            with (self.root / "observations.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
