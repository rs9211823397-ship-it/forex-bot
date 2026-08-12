from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import OpenAIResponsesChartClient
from .config import ChartObserverConfig
from .snapshot import MarketSnapshot
from .store import ChartObservationStore


@dataclass(frozen=True)
class ReplayItem:
    input_path: Path
    snapshot: MarketSnapshot
    deterministic: dict[str, Any]
    lower_image: Path
    higher_image: Path


class HistoricalChartReplay:
    """Replay persisted captures through the remote chart analyst later.

    This utility is outside the trading path. It never imports execution or
    risk modules and never changes an AAQTS decision. Existing analysis.json
    files are skipped so repeated runs are idempotent.
    """

    def __init__(
        self,
        config: ChartObserverConfig,
        *,
        client: OpenAIResponsesChartClient | None = None,
        store: ChartObservationStore | None = None,
    ) -> None:
        self.config = config
        self.root = Path(config.output_root)
        self.client = client or OpenAIResponsesChartClient(config)
        self.store = store or ChartObservationStore(config)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object: {path}")
        return payload

    @staticmethod
    def _snapshot(payload: dict[str, Any]) -> MarketSnapshot:
        raw = payload.get("snapshot")
        if not isinstance(raw, dict):
            raise ValueError("Replay input is missing snapshot")
        values = dict(raw)
        values["lower_bars"] = tuple(values.get("lower_bars") or ())
        values["higher_bars"] = tuple(values.get("higher_bars") or ())
        values["lower_indicators"] = dict(values.get("lower_indicators") or {})
        values["higher_indicators"] = dict(values.get("higher_indicators") or {})
        return MarketSnapshot(**values)

    def pending_paths(self) -> list[Path]:
        if not self.root.exists():
            return []
        pending: list[Path] = []
        for input_path in sorted(self.root.glob("????-??-??/*/input.json")):
            if (input_path.parent / "analysis.json").exists():
                continue
            pending.append(input_path)
        return pending

    def _load_item(self, input_path: Path) -> ReplayItem:
        payload = self._read_json(input_path)
        snapshot = self._snapshot(payload)
        deterministic = payload.get("deterministic_comparison") or {}
        if not isinstance(deterministic, dict):
            deterministic = {}
        images = payload.get("images") or {}
        if not isinstance(images, dict):
            images = {}
        lower_image = input_path.parent / str(images.get("lower") or "m15.png")
        higher_image = input_path.parent / str(images.get("higher") or "h1.png")
        if not lower_image.exists():
            raise FileNotFoundError(f"Missing replay image: {lower_image}")
        if not higher_image.exists():
            raise FileNotFoundError(f"Missing replay image: {higher_image}")
        return ReplayItem(
            input_path=input_path,
            snapshot=snapshot,
            deterministic=dict(deterministic),
            lower_image=lower_image,
            higher_image=higher_image,
        )

    def run(self, *, limit: int = 5, fail_fast: bool = True) -> dict[str, Any]:
        if not self.config.remote_enabled:
            raise RuntimeError(
                "Historical replay requires AAQTS_AI_CHART_REMOTE_ENABLED=true"
            )
        if limit <= 0:
            raise ValueError("Replay limit must be positive")

        paths = self.pending_paths()[: int(limit)]
        completed = 0
        errors = 0
        error_messages: list[str] = []
        for input_path in paths:
            item: ReplayItem | None = None
            try:
                item = self._load_item(input_path)
                analysis, metadata = self.client.analyze(
                    item.snapshot,
                    item.lower_image,
                    item.higher_image,
                )
                self.store.write_result(
                    item.snapshot,
                    analysis,
                    deterministic=item.deterministic,
                    metadata=metadata,
                )
                completed += 1
            except Exception as exc:
                errors += 1
                message = f"{type(exc).__name__}: {exc}"
                error_messages.append(message[:1000])
                try:
                    self.store.write_error(
                        error_message=f"HistoricalReplay: {message}",
                        snapshot=(item.snapshot if item is not None else None),
                        symbol=(item.snapshot.symbol if item is not None else input_path.parent.name),
                        deterministic=(item.deterministic if item is not None else {}),
                    )
                except Exception:
                    pass
                if fail_fast:
                    break

        return {
            "requested": len(paths),
            "completed": completed,
            "errors": errors,
            "remaining": len(self.pending_paths()),
            "error_messages": error_messages,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay persisted AAQTS chart captures through the remote analyst."
    )
    parser.add_argument("--execute", action="store_true", help="Actually make remote API calls")
    parser.add_argument("--limit", type=int, default=5, help="Maximum captures to analyze")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue after a failed remote call instead of failing fast",
    )
    args = parser.parse_args()

    config = ChartObserverConfig.from_env()
    replay = HistoricalChartReplay(config)
    pending = replay.pending_paths()
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "DRY_RUN",
                    "pending": len(pending),
                    "remote_enabled": config.remote_enabled,
                    "note": "No remote API calls were made. Use --execute only when API credits are intentionally available.",
                },
                indent=2,
            )
        )
        return 0

    result = replay.run(
        limit=args.limit,
        fail_fast=not args.continue_on_error,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
