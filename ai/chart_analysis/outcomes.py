from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ChartObserverConfig
from .snapshot import MarketSnapshot


@dataclass(frozen=True)
class PendingOutcome:
    snapshot_id: str
    symbol: str
    as_of_utc: str
    signal: str
    confidence: float | None
    snapshot_atr: float | None
    captured_entry: float | None
    captured_stop: float | None
    captured_target: float | None


class OutcomeEvaluator:
    """Attach forward-only M15 labels to captured chart observations.

    The evaluator never changes a trading decision. It only consumes candles
    whose ``close_time`` is strictly after a capture's ``as_of_utc``. Entry is
    the first future bar open unless a deterministic entry was captured. Risk
    is the captured stop distance when available, otherwise snapshot ATR.
    """

    SCHEMA_VERSION = "1.0"

    def __init__(self, config: ChartObserverConfig) -> None:
        self.config = config
        self.root = Path(config.output_root)
        self.horizons = tuple(int(item) for item in config.outcome_horizons)
        self.max_horizon = max(self.horizons)
        self.stop_r = float(config.outcome_stop_r)
        self.target_r = float(config.outcome_target_r)
        self._lock = threading.RLock()
        self._index_lock = threading.Lock()
        self._pending: dict[str, PendingOutcome] = {}
        self._finalized: set[str] = set()
        self._load_existing()

    @staticmethod
    def _finite(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _utc(value: object) -> pd.Timestamp:
        parsed = pd.Timestamp(value)
        if parsed.tzinfo is None:
            return parsed.tz_localize("UTC")
        return parsed.tz_convert("UTC")

    @classmethod
    def _level(cls, deterministic: dict[str, Any], *names: str) -> float | None:
        sources: list[dict[str, Any]] = [deterministic]
        for key in ("risk_plan", "trade_plan", "execution_plan"):
            nested = deterministic.get(key)
            if isinstance(nested, dict):
                sources.append(nested)
        for source in sources:
            for name in names:
                if name in source:
                    value = cls._finite(source.get(name))
                    if value is not None:
                        return value
        return None

    @classmethod
    def _pending_from_payload(cls, payload: dict[str, Any]) -> PendingOutcome | None:
        snapshot = payload.get("snapshot") or {}
        deterministic = payload.get("deterministic_comparison") or {}
        if not isinstance(snapshot, dict) or not isinstance(deterministic, dict):
            return None
        signal = str(
            deterministic.get("signal")
            or deterministic.get("strategy_signal")
            or "HOLD"
        ).upper().strip()
        if signal not in {"BUY", "SELL"}:
            return None
        lower_indicators = snapshot.get("lower_indicators") or {}
        if not isinstance(lower_indicators, dict):
            lower_indicators = {}
        snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
        symbol = str(snapshot.get("symbol") or "").strip()
        as_of_utc = str(snapshot.get("as_of_utc") or "").strip()
        if not snapshot_id or not symbol or not as_of_utc:
            return None
        return PendingOutcome(
            snapshot_id=snapshot_id,
            symbol=symbol,
            as_of_utc=as_of_utc,
            signal=signal,
            confidence=cls._finite(deterministic.get("confidence")),
            snapshot_atr=cls._finite(lower_indicators.get("ATR")),
            captured_entry=cls._level(deterministic, "entry", "entry_price"),
            captured_stop=cls._level(deterministic, "stop_loss", "sl", "stop"),
            captured_target=cls._level(
                deterministic,
                "take_profit",
                "tp",
                "target",
                "target_1",
            ),
        )

    def _load_existing(self) -> None:
        if not self.config.outcomes_enabled or not self.root.exists():
            return
        for input_path in self.root.glob("????-??-??/*/input.json"):
            try:
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                pending = self._pending_from_payload(payload)
                if pending is None:
                    continue
                outcome_path = input_path.parent / "outcome.json"
                if outcome_path.exists():
                    try:
                        existing = json.loads(outcome_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        existing = {}
                    if existing.get("finalized") is True:
                        self._finalized.add(pending.snapshot_id)
                        continue
                self._pending[pending.snapshot_id] = pending
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue

    def register(
        self,
        snapshot: MarketSnapshot,
        deterministic: dict[str, Any],
    ) -> bool:
        if not self.config.outcomes_enabled:
            return False
        payload = {
            "snapshot": snapshot.to_dict(),
            "deterministic_comparison": dict(deterministic),
        }
        pending = self._pending_from_payload(payload)
        if pending is None:
            return False
        with self._lock:
            if pending.snapshot_id in self._finalized:
                return False
            self._pending[pending.snapshot_id] = pending
        return True

    @staticmethod
    def _future_frame(frame: pd.DataFrame, as_of_utc: str) -> pd.DataFrame:
        if frame is None or frame.empty or "close_time" not in frame.columns:
            return pd.DataFrame()
        required = ("open", "high", "low", "close")
        if any(name not in frame.columns for name in required):
            return pd.DataFrame()
        close_times = pd.to_datetime(frame["close_time"], utc=True, errors="coerce")
        cutoff = OutcomeEvaluator._utc(as_of_utc)
        future = frame.loc[close_times > cutoff].copy()
        if future.empty:
            return future
        future["__close_time_utc"] = close_times.loc[future.index]
        future = future.sort_values("__close_time_utc")
        for name in required:
            future[name] = pd.to_numeric(future[name], errors="coerce")
        return future.dropna(subset=list(required))

    def update_market(self, symbol: str, frame: pd.DataFrame) -> int:
        """Update pending observations for one symbol from completed candles."""
        if not self.config.outcomes_enabled:
            return 0
        normalized_symbol = str(symbol)
        with self._lock:
            candidates = [
                item
                for item in self._pending.values()
                if item.symbol == normalized_symbol
            ]
        written = 0
        for pending in candidates:
            future = self._future_frame(frame, pending.as_of_utc)
            if future.empty:
                continue
            payload = self._evaluate(pending, future)
            self._write_outcome(pending, payload)
            written += 1
            if payload["finalized"]:
                with self._lock:
                    self._pending.pop(pending.snapshot_id, None)
                    self._finalized.add(pending.snapshot_id)
        return written

    def _resolve_levels(
        self,
        pending: PendingOutcome,
        future: pd.DataFrame,
    ) -> dict[str, Any]:
        first_open = self._finite(future.iloc[0]["open"])
        if first_open is None or first_open <= 0:
            raise ValueError("Future entry bar has no valid open price")
        entry = pending.captured_entry or first_open
        direction = 1.0 if pending.signal == "BUY" else -1.0

        captured_risk = None
        if pending.captured_stop is not None:
            distance = abs(entry - pending.captured_stop)
            if distance > 0:
                captured_risk = distance
        risk_unit = captured_risk or pending.snapshot_atr
        if risk_unit is None or risk_unit <= 0:
            raise ValueError("Outcome evaluator requires captured stop distance or snapshot ATR")

        stop = pending.captured_stop
        if stop is None:
            stop = entry - direction * self.stop_r * risk_unit
        target = pending.captured_target
        if target is None:
            target = entry + direction * self.target_r * risk_unit

        if pending.signal == "BUY" and not (stop < entry < target):
            raise ValueError("BUY outcome levels must satisfy stop < entry < target")
        if pending.signal == "SELL" and not (target < entry < stop):
            raise ValueError("SELL outcome levels must satisfy target < entry < stop")

        target_r = abs(target - entry) / risk_unit
        stop_distance_r = abs(entry - stop) / risk_unit
        source = (
            "CAPTURED_LEVELS"
            if pending.captured_stop is not None
            else "NEXT_BAR_OPEN_SNAPSHOT_ATR"
        )
        return {
            "entry": entry,
            "stop": stop,
            "target": target,
            "risk_unit": risk_unit,
            "target_r": target_r,
            "stop_r": stop_distance_r,
            "source": source,
        }

    @staticmethod
    def _barrier_event(
        signal: str,
        window: pd.DataFrame,
        stop: float,
        target: float,
    ) -> tuple[str | None, int | None, str | None]:
        for offset, (_, row) in enumerate(window.iterrows(), start=1):
            high = float(row["high"])
            low = float(row["low"])
            if signal == "BUY":
                stop_hit = low <= stop
                target_hit = high >= target
            else:
                stop_hit = high >= stop
                target_hit = low <= target
            if stop_hit and target_hit:
                return "AMBIGUOUS_SAME_BAR", offset, str(row["__close_time_utc"])
            if stop_hit:
                return "SL", offset, str(row["__close_time_utc"])
            if target_hit:
                return "TP", offset, str(row["__close_time_utc"])
        return None, None, None

    def _horizon_metrics(
        self,
        pending: PendingOutcome,
        future: pd.DataFrame,
        horizon: int,
        levels: dict[str, Any],
    ) -> dict[str, Any]:
        window = future.iloc[:horizon]
        entry = float(levels["entry"])
        risk = float(levels["risk_unit"])
        direction = 1.0 if pending.signal == "BUY" else -1.0
        close_price = float(window.iloc[-1]["close"])
        directional_move = direction * (close_price - entry)
        mark_to_market_r = directional_move / risk
        return_pct = directional_move / entry * 100.0

        if pending.signal == "BUY":
            favorable = float(window["high"].max()) - entry
            adverse = entry - float(window["low"].min())
        else:
            favorable = entry - float(window["low"].min())
            adverse = float(window["high"].max()) - entry
        mfe_r = max(0.0, favorable / risk)
        mae_r = max(0.0, adverse / risk)
        event, event_bar, event_close_time = self._barrier_event(
            pending.signal,
            window,
            float(levels["stop"]),
            float(levels["target"]),
        )
        terminal_r = None
        if event == "TP":
            terminal_r = float(levels["target_r"])
        elif event == "SL":
            terminal_r = -float(levels["stop_r"])

        return {
            "bars": int(horizon),
            "close_time_utc": str(window.iloc[-1]["__close_time_utc"]),
            "close": close_price,
            "return_percent": round(return_pct, 6),
            "mark_to_market_r": round(mark_to_market_r, 6),
            "mfe_r": round(mfe_r, 6),
            "mae_r": round(mae_r, 6),
            "first_barrier_event": event,
            "first_barrier_bar": event_bar,
            "first_barrier_close_time_utc": event_close_time,
            "terminal_r": (round(terminal_r, 6) if terminal_r is not None else None),
        }

    def _evaluate(
        self,
        pending: PendingOutcome,
        future: pd.DataFrame,
    ) -> dict[str, Any]:
        levels = self._resolve_levels(pending, future)
        available = len(future)
        horizon_metrics: dict[str, Any] = {}
        for horizon in self.horizons:
            if available >= horizon:
                horizon_metrics[str(horizon)] = self._horizon_metrics(
                    pending,
                    future,
                    horizon,
                    levels,
                )

        finalized = available >= self.max_horizon
        final_metric = horizon_metrics.get(str(self.max_horizon)) if finalized else None
        realized_r = None
        final_status = "PENDING"
        if final_metric is not None:
            event = final_metric["first_barrier_event"]
            if event == "TP":
                final_status = "TP"
                realized_r = float(levels["target_r"])
            elif event == "SL":
                final_status = "SL"
                realized_r = -float(levels["stop_r"])
            elif event == "AMBIGUOUS_SAME_BAR":
                final_status = "AMBIGUOUS_SAME_BAR"
            else:
                final_status = "TIME_HORIZON"
                realized_r = float(final_metric["mark_to_market_r"])

        return {
            "record_type": "AAQTS_CHART_OUTCOME",
            "schema_version": self.SCHEMA_VERSION,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot_id": pending.snapshot_id,
            "symbol": pending.symbol,
            "as_of_utc": pending.as_of_utc,
            "deterministic_signal": pending.signal,
            "deterministic_confidence": pending.confidence,
            "policy": {
                "entry": "CAPTURED_ENTRY_ELSE_NEXT_BAR_OPEN",
                "risk": "CAPTURED_STOP_DISTANCE_ELSE_SNAPSHOT_ATR",
                "fallback_stop_r": self.stop_r,
                "fallback_target_r": self.target_r,
                "horizons": list(self.horizons),
                "same_bar_tp_sl": "AMBIGUOUS_SAME_BAR",
                "future_candles_only": True,
            },
            "levels": {
                key: (round(value, 10) if isinstance(value, float) else value)
                for key, value in levels.items()
            },
            "available_future_bars": int(available),
            "horizons": horizon_metrics,
            "finalized": bool(finalized),
            "final": {
                "status": final_status,
                "realized_r": (round(realized_r, 6) if realized_r is not None else None),
            },
        }

    def _outcome_path(self, pending: PendingOutcome) -> Path:
        return self.root / pending.as_of_utc[:10] / pending.snapshot_id / "outcome.json"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _write_outcome(self, pending: PendingOutcome, payload: dict[str, Any]) -> None:
        path = self._outcome_path(pending)
        previously_finalized = False
        if path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                previously_finalized = previous.get("finalized") is True
            except (OSError, json.JSONDecodeError):
                pass
        self._write_json(path, payload)
        if payload["finalized"] and not previously_finalized:
            final_horizon = payload["horizons"].get(str(self.max_horizon), {})
            self._append_index(
                {
                    "status": "OUTCOME_FINAL",
                    "recorded_utc": payload["updated_utc"],
                    "snapshot_id": pending.snapshot_id,
                    "symbol": pending.symbol,
                    "as_of_utc": pending.as_of_utc,
                    "deterministic_signal": pending.signal,
                    "deterministic_confidence": pending.confidence,
                    "final_status": payload["final"]["status"],
                    "realized_r": payload["final"]["realized_r"],
                    "mfe_r": final_horizon.get("mfe_r"),
                    "mae_r": final_horizon.get("mae_r"),
                    "horizon_bars": self.max_horizon,
                    "schema_version": self.SCHEMA_VERSION,
                }
            )

    def _append_index(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n"
        with self._index_lock:
            with (self.root / "outcomes.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.outcomes_enabled,
                "pending": len(self._pending),
                "finalized_in_memory": len(self._finalized),
                "horizons": list(self.horizons),
                "stop_r": self.stop_r,
                "target_r": self.target_r,
            }


__all__ = ["OutcomeEvaluator", "PendingOutcome"]
