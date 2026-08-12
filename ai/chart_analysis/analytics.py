from __future__ import annotations

import json
import math
import os
import statistics
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import ChartObserverConfig


class OutcomeAnalytics:
    """Build restart-safe research summaries from chart captures and outcomes.

    Analytics are observational only. They never approve, reject, size, delay,
    or otherwise influence AAQTS trading decisions.
    """

    SCHEMA_VERSION = "1.1"

    def __init__(self, config: ChartObserverConfig) -> None:
        self.config = config
        self.root = Path(config.output_root)
        self.summary_path = self.root / "analytics_summary.json"
        self._lock = threading.RLock()

    @staticmethod
    def _finite(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _signal(deterministic: dict[str, Any]) -> str:
        return str(
            deterministic.get("signal")
            or deterministic.get("strategy_signal")
            or "HOLD"
        ).upper().strip()

    @classmethod
    def _confidence_bucket(cls, value: object) -> str:
        confidence = cls._finite(value)
        if confidence is None:
            return "UNKNOWN"
        if confidence < 40:
            return "LT_40"
        if confidence < 50:
            return "40_49"
        if confidence < 60:
            return "50_59"
        if confidence < 70:
            return "60_69"
        return "70_PLUS"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _ai_relation(
        deterministic_signal: str,
        analysis_payload: dict[str, Any] | None,
    ) -> tuple[str, str | None, float | None, bool | None]:
        if not isinstance(analysis_payload, dict):
            return "NOT_ANALYZED", None, None, None
        analysis = analysis_payload.get("analysis") or {}
        if not isinstance(analysis, dict):
            return "NOT_ANALYZED", None, None, None
        ai_signal = str(analysis.get("signal") or "HOLD").upper().strip()
        ai_confidence = OutcomeAnalytics._finite(analysis.get("confidence"))
        ai_abstain = bool(analysis.get("abstain") is True)
        if ai_abstain:
            relation = "ABSTAIN"
        elif ai_signal == "HOLD":
            relation = "AI_HOLD"
        elif ai_signal == deterministic_signal:
            relation = "AGREE"
        elif ai_signal in {"BUY", "SELL"}:
            relation = "DISAGREE"
        else:
            relation = "UNKNOWN"
        return relation, ai_signal, ai_confidence, ai_abstain

    def _rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.root.exists():
            return rows

        for input_path in sorted(self.root.glob("????-??-??/*/input.json")):
            payload = self._read_json(input_path)
            if payload is None:
                continue
            snapshot = payload.get("snapshot") or {}
            deterministic = payload.get("deterministic_comparison") or {}
            if not isinstance(snapshot, dict) or not isinstance(deterministic, dict):
                continue
            signal = self._signal(deterministic)
            if signal not in {"BUY", "SELL"}:
                continue

            outcome_path = input_path.parent / "outcome.json"
            outcome = self._read_json(outcome_path) if outcome_path.exists() else None
            final = outcome.get("final", {}) if isinstance(outcome, dict) else {}
            if not isinstance(final, dict):
                final = {}
            horizons = outcome.get("horizons", {}) if isinstance(outcome, dict) else {}
            if not isinstance(horizons, dict):
                horizons = {}

            analysis_path = input_path.parent / "analysis.json"
            analysis_payload = self._read_json(analysis_path) if analysis_path.exists() else None
            ai_relation, ai_signal, ai_confidence, ai_abstain = self._ai_relation(
                signal,
                analysis_payload,
            )

            record_type = str(outcome.get("record_type", "")) if isinstance(outcome, dict) else ""
            error = bool(
                outcome
                and (
                    "ERROR" in record_type.upper()
                    or outcome.get("error")
                )
            )
            finalized = bool(outcome and outcome.get("finalized") is True)

            rows.append(
                {
                    "snapshot_id": str(snapshot.get("snapshot_id") or input_path.parent.name),
                    "symbol": str(snapshot.get("symbol") or "UNKNOWN"),
                    "as_of_utc": str(snapshot.get("as_of_utc") or ""),
                    "signal": signal,
                    "confidence": self._finite(deterministic.get("confidence")),
                    "confidence_bucket": self._confidence_bucket(deterministic.get("confidence")),
                    "strategy": str(deterministic.get("strategy") or "UNKNOWN"),
                    "regime": str(deterministic.get("regime") or "UNKNOWN"),
                    "ai_relation": ai_relation,
                    "ai_signal": ai_signal,
                    "ai_confidence": ai_confidence,
                    "ai_abstain": ai_abstain,
                    "finalized": finalized,
                    "error": error,
                    "status": str(final.get("status") or ("ERROR" if error else "PENDING")),
                    "realized_r": self._finite(final.get("realized_r")),
                    "available_future_bars": int(outcome.get("available_future_bars", 0) or 0)
                    if isinstance(outcome, dict)
                    else 0,
                    "horizons": horizons,
                }
            )
        return rows

    @classmethod
    def _profit_factor(cls, values: Iterable[float]) -> float | None:
        positives = sum(value for value in values if value > 0)
        negatives = abs(sum(value for value in values if value < 0))
        if negatives == 0:
            return None
        return positives / negatives

    @staticmethod
    def _rounded(value: float | None) -> float | None:
        if value is None or not math.isfinite(value):
            return None
        return round(float(value), 6)

    def _final_metrics(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        finalized = [row for row in rows if row["finalized"]]
        statuses = Counter(row["status"] for row in finalized)
        valid = [row for row in finalized if row["realized_r"] is not None]
        realized = [float(row["realized_r"]) for row in valid]
        pf = self._profit_factor(realized)
        return {
            "samples": len(finalized),
            "scored_samples": len(valid),
            "status_counts": dict(sorted(statuses.items())),
            "positive_r_samples": sum(1 for value in realized if value > 0),
            "negative_r_samples": sum(1 for value in realized if value < 0),
            "flat_r_samples": sum(1 for value in realized if value == 0),
            "positive_r_rate": self._rounded(
                sum(1 for value in realized if value > 0) / len(realized)
            ) if realized else None,
            "expectancy_r": self._rounded(statistics.fmean(realized)) if realized else None,
            "median_r": self._rounded(statistics.median(realized)) if realized else None,
            "profit_factor": self._rounded(pf),
            "total_r": self._rounded(sum(realized)) if realized else None,
        }

    def _horizon_metrics(self, rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
        metrics: list[dict[str, Any]] = []
        for row in rows:
            item = row["horizons"].get(str(horizon))
            if isinstance(item, dict):
                metrics.append(item)
        if not metrics:
            return {
                "samples": 0,
                "avg_mark_to_market_r": None,
                "avg_mfe_r": None,
                "avg_mae_r": None,
                "positive_close_rate": None,
                "barrier_counts": {},
            }

        mtm = [value for item in metrics if (value := self._finite(item.get("mark_to_market_r"))) is not None]
        mfe = [value for item in metrics if (value := self._finite(item.get("mfe_r"))) is not None]
        mae = [value for item in metrics if (value := self._finite(item.get("mae_r"))) is not None]
        barriers = Counter(str(item.get("first_barrier_event") or "NONE") for item in metrics)
        return {
            "samples": len(metrics),
            "avg_mark_to_market_r": self._rounded(statistics.fmean(mtm)) if mtm else None,
            "avg_mfe_r": self._rounded(statistics.fmean(mfe)) if mfe else None,
            "avg_mae_r": self._rounded(statistics.fmean(mae)) if mae else None,
            "positive_close_rate": self._rounded(
                sum(1 for value in mtm if value > 0) / len(mtm)
            ) if mtm else None,
            "barrier_counts": dict(sorted(barriers.items())),
        }

    def _bucket(self, rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get(key) or "UNKNOWN")].append(row)
        result: dict[str, Any] = {}
        for name in sorted(grouped):
            group = grouped[name]
            result[name] = {
                "captures": len(group),
                "pending": sum(1 for row in group if not row["finalized"] and not row["error"]),
                "errors": sum(1 for row in group if row["error"]),
                "final": self._final_metrics(group),
            }
        return result

    def build(self) -> dict[str, Any]:
        rows = self._rows()
        finalized_count = sum(1 for row in rows if row["finalized"])
        error_count = sum(1 for row in rows if row["error"])
        pending_count = sum(1 for row in rows if not row["finalized"] and not row["error"])
        min_total = int(self.config.analytics_min_finalized_samples)
        min_bucket = int(self.config.analytics_min_bucket_samples)
        ai_counts = Counter(row["ai_relation"] for row in rows)
        analyzed_rows = [row for row in rows if row["ai_relation"] != "NOT_ANALYZED"]

        summary = {
            "record_type": "AAQTS_CHART_OUTCOME_ANALYTICS",
            "schema_version": self.SCHEMA_VERSION,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "observer_only": True,
            "remote_ai_required": False,
            "counts": {
                "captures": len(rows),
                "pending": pending_count,
                "finalized": finalized_count,
                "errors": error_count,
            },
            "readiness": {
                "minimum_finalized_samples": min_total,
                "minimum_bucket_samples": min_bucket,
                "ready_for_overall_conclusions": finalized_count >= min_total,
                "warning": (
                    "Dataset is below the minimum finalized-sample guardrail; treat all performance statistics as descriptive only."
                    if finalized_count < min_total
                    else "Overall sample guardrail met; bucket-level conclusions still require their own minimum sample count."
                ),
            },
            "overall": self._final_metrics(rows),
            "horizons": {
                str(horizon): self._horizon_metrics(rows, horizon)
                for horizon in self.config.outcome_horizons
            },
            "by_symbol": self._bucket(rows, "symbol"),
            "by_signal": self._bucket(rows, "signal"),
            "by_confidence": self._bucket(rows, "confidence_bucket"),
            "by_regime": self._bucket(rows, "regime"),
            "by_strategy": self._bucket(rows, "strategy"),
            "ai_comparison": {
                "analyzed": len(analyzed_rows),
                "not_analyzed": ai_counts.get("NOT_ANALYZED", 0),
                "relation_counts": {
                    key: value
                    for key, value in sorted(ai_counts.items())
                    if key != "NOT_ANALYZED"
                },
                "by_relation": self._bucket(analyzed_rows, "ai_relation"),
            },
        }

        for section_name in (
            "by_symbol",
            "by_signal",
            "by_confidence",
            "by_regime",
            "by_strategy",
        ):
            for bucket in summary[section_name].values():
                bucket["sample_guardrail_met"] = (
                    bucket["final"]["samples"] >= min_bucket
                )
        for bucket in summary["ai_comparison"]["by_relation"].values():
            bucket["sample_guardrail_met"] = bucket["final"]["samples"] >= min_bucket
        return summary

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def refresh(self) -> dict[str, Any]:
        with self._lock:
            summary = self.build()
            self._write_json(self.summary_path, summary)
            return summary

    def status(self) -> dict[str, Any]:
        summary = self.refresh()
        return {
            "enabled": self.config.analytics_enabled,
            "summary_path": str(self.summary_path),
            "counts": summary["counts"],
            "ai_comparison": summary["ai_comparison"],
            "ready_for_overall_conclusions": summary["readiness"]["ready_for_overall_conclusions"],
        }
