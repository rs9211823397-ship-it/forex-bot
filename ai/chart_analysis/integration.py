from __future__ import annotations

import logging
import threading
from typing import Any

from .config import ChartObserverConfig
from .observer import ChartObserver


logger = logging.getLogger(__name__)
_lock = threading.RLock()
_observer: ChartObserver | None = None


def _get_observer() -> ChartObserver | None:
    """Return the shared observer only when Phase AI-1 is explicitly enabled."""

    global _observer
    try:
        config = ChartObserverConfig.from_env()
    except Exception:
        logger.exception("AI chart observer configuration is invalid; observer disabled")
        return None

    if not config.enabled:
        return None

    with _lock:
        if _observer is None:
            try:
                _observer = ChartObserver(config)
                logger.info(
                    "AI chart observer enabled | mode=%s model=%s actionable_only=%s",
                    config.mode,
                    config.model,
                    config.only_actionable,
                )
            except Exception:
                logger.exception("AI chart observer initialization failed; trading continues")
                return None
        return _observer


def observe_routed_decision(
    *,
    symbol: str,
    lower_frame,
    higher_frame,
    deterministic: dict[str, Any],
    lower_timeframe: str,
    higher_timeframe: str,
) -> bool:
    """Submit one blind observation without affecting the routed decision.

    This bridge deliberately returns only whether work was scheduled. Callers
    must never use that boolean to approve, reject, size, delay, or modify a
    trade. Any configuration, rendering, storage, or scheduling error fails
    open with respect to the deterministic trading engine.
    """

    if higher_frame is None:
        return False

    observer = _get_observer()
    if observer is None:
        return False

    try:
        return observer.observe(
            symbol=str(symbol),
            lower_frame=lower_frame,
            higher_frame=higher_frame,
            deterministic=dict(deterministic),
            lower_timeframe=str(lower_timeframe),
            higher_timeframe=str(higher_timeframe),
        )
    except Exception:
        logger.exception("AI chart observation scheduling failed for %s; trading continues", symbol)
        return False


def chart_observer_status() -> dict[str, Any]:
    with _lock:
        if _observer is None:
            try:
                config = ChartObserverConfig.from_env()
                return {
                    "enabled": config.enabled,
                    "mode": config.mode,
                    "model": config.model,
                    "only_actionable": config.only_actionable,
                    "submitted": 0,
                    "completed": 0,
                    "errors": 0,
                    "pending": 0,
                    "last_completed_utc": None,
                    "last_error": None,
                    "prompt_version": config.prompt_version,
                    "schema_version": config.schema_version,
                }
            except Exception as exc:
                return {
                    "enabled": False,
                    "mode": "OBSERVER",
                    "submitted": 0,
                    "completed": 0,
                    "errors": 1,
                    "pending": 0,
                    "last_error": f"{type(exc).__name__}: {exc}"[:1000],
                }
        return _observer.status()


def shutdown_chart_observer(*, wait: bool = False) -> None:
    global _observer
    with _lock:
        observer = _observer
        _observer = None
    if observer is not None:
        try:
            observer.shutdown(wait=wait)
        except Exception:
            logger.exception("AI chart observer shutdown failed")


__all__ = [
    "observe_routed_decision",
    "chart_observer_status",
    "shutdown_chart_observer",
]
