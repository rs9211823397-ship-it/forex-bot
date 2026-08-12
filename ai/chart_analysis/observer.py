from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from indicators.technical import TechnicalIndicators

from .client import OpenAIResponsesChartClient
from .config import ChartObserverConfig
from .renderer import ChartRenderer
from .snapshot import build_market_snapshot, causal_render_frame
from .store import ChartObservationStore


logger = logging.getLogger(__name__)


class ChartObserver:
    """Asynchronous, fail-open Phase AI-1 observer.

    Local evidence capture is independent from remote model usage. When
    ``remote_enabled`` is false, causal snapshots and charts are still written
    but no network request is made. No observer output is returned to strategy,
    risk, or execution code.
    """

    def __init__(
        self,
        config: ChartObserverConfig | None = None,
        *,
        renderer: ChartRenderer | None = None,
        client: OpenAIResponsesChartClient | None = None,
        store: ChartObservationStore | None = None,
    ) -> None:
        self.config = config or ChartObserverConfig.from_env()
        self.renderer = renderer or ChartRenderer()
        self.client = client or OpenAIResponsesChartClient(self.config)
        self.store = store or ChartObservationStore(self.config)
        self.indicators = TechnicalIndicators()
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.max_inflight,
            thread_name_prefix="aaqts-ai-chart",
        )
        self._slots = threading.BoundedSemaphore(self.config.max_inflight)
        self._lock = threading.RLock()
        self._last_candle_by_symbol: dict[str, str] = {}
        self._submitted = 0
        self._captured = 0
        self._completed = 0
        self._errors = 0
        self._pending = 0
        self._last_completed_utc: str | None = None
        self._last_error: str | None = None

    @staticmethod
    def _completed_close(frame: pd.DataFrame) -> str:
        if frame is None or frame.empty or "close_time" not in frame.columns:
            raise ValueError("Observer requires a completed lower-timeframe candle")
        value = pd.Timestamp(frame["close_time"].iloc[-1])
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        else:
            value = value.tz_convert("UTC")
        return value.isoformat()

    def observe(
        self,
        *,
        symbol: str,
        lower_frame: pd.DataFrame,
        higher_frame: pd.DataFrame,
        deterministic: dict[str, Any],
        lower_timeframe: str,
        higher_timeframe: str,
    ) -> bool:
        """Schedule one blind observation; return False when safely skipped."""

        if not self.config.enabled:
            return False

        signal = str(
            deterministic.get("signal")
            or deterministic.get("strategy_signal")
            or "HOLD"
        ).upper().strip()
        close_time = self._completed_close(lower_frame)

        with self._lock:
            if self._last_candle_by_symbol.get(str(symbol)) == close_time:
                return False
            if self.config.only_actionable and signal not in {"BUY", "SELL"}:
                self._last_candle_by_symbol[str(symbol)] = close_time
                return False
            if not self._slots.acquire(blocking=False):
                # Do not stall the trading loop or create an unbounded queue.
                return False
            self._last_candle_by_symbol[str(symbol)] = close_time
            self._submitted += 1
            self._pending += 1

        lower_copy = lower_frame.copy(deep=True)
        lower_copy.attrs.update(dict(getattr(lower_frame, "attrs", {}) or {}))
        higher_copy = higher_frame.copy(deep=True)
        higher_copy.attrs.update(dict(getattr(higher_frame, "attrs", {}) or {}))
        deterministic_copy = dict(deterministic)

        try:
            self._executor.submit(
                self._run,
                str(symbol),
                lower_copy,
                higher_copy,
                deterministic_copy,
                str(lower_timeframe),
                str(higher_timeframe),
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._pending = max(0, self._pending - 1)
                self._errors += 1
                self._last_error = message[:1000]
                if self._last_candle_by_symbol.get(str(symbol)) == close_time:
                    self._last_candle_by_symbol.pop(str(symbol), None)
            self._slots.release()
            logger.exception("Could not schedule AI chart observer for %s", symbol)
            try:
                self.store.write_error(
                    error_message=message,
                    symbol=str(symbol),
                    deterministic=deterministic_copy,
                )
            except Exception:
                logger.exception("Could not persist AI chart scheduling error")
            return False
        return True

    def _run(
        self,
        symbol: str,
        lower_frame: pd.DataFrame,
        higher_frame: pd.DataFrame,
        deterministic: dict[str, Any],
        lower_timeframe: str,
        higher_timeframe: str,
    ) -> None:
        snapshot = None
        try:
            # Truncate raw frames before indicator calculation. This makes the
            # observer robust even if a future indicator implementation becomes
            # centered/non-causal: future H1 candles never enter that function.
            as_of_utc = self._completed_close(lower_frame)
            lower_causal = causal_render_frame(
                lower_frame,
                as_of_utc=as_of_utc,
                bars=len(lower_frame),
            )
            higher_causal = causal_render_frame(
                higher_frame,
                as_of_utc=as_of_utc,
                bars=len(higher_frame),
            )
            lower_analyzed = self.indicators.add_indicators(lower_causal)
            higher_analyzed = self.indicators.add_indicators(higher_causal)
            snapshot = build_market_snapshot(
                symbol=symbol,
                lower_frame=lower_analyzed,
                higher_frame=higher_analyzed,
                lower_timeframe=lower_timeframe,
                higher_timeframe=higher_timeframe,
                numeric_bars=self.config.numeric_bars,
                schema_version=self.config.schema_version,
            )
            directory = self.store.observation_dir(snapshot)
            lower_image = directory / "m15.png"
            higher_image = directory / "h1.png"

            self.renderer.render(
                causal_render_frame(
                    lower_analyzed,
                    as_of_utc=snapshot.as_of_utc,
                    bars=self.config.lower_render_bars,
                ),
                symbol=symbol,
                timeframe=lower_timeframe,
                as_of_utc=snapshot.as_of_utc,
                output_path=lower_image,
            )
            self.renderer.render(
                causal_render_frame(
                    higher_analyzed,
                    as_of_utc=snapshot.as_of_utc,
                    bars=self.config.higher_render_bars,
                ),
                symbol=symbol,
                timeframe=higher_timeframe,
                as_of_utc=snapshot.as_of_utc,
                output_path=higher_image,
            )
            self.store.write_input(
                snapshot,
                deterministic=deterministic,
                lower_image_name=lower_image.name,
                higher_image_name=higher_image.name,
            )

            if not self.config.remote_enabled:
                self.store.write_capture(snapshot, deterministic=deterministic)
                with self._lock:
                    self._captured += 1
                    self._last_completed_utc = datetime.now(timezone.utc).isoformat()
                    self._last_error = None
                return

            analysis, metadata = self.client.analyze(
                snapshot,
                lower_image,
                higher_image,
            )
            self.store.write_result(
                snapshot,
                analysis,
                deterministic=deterministic,
                metadata=metadata,
            )
            with self._lock:
                self._completed += 1
                self._last_completed_utc = datetime.now(timezone.utc).isoformat()
                self._last_error = None
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("AI chart observer failed for %s", symbol)
            try:
                self.store.write_error(
                    error_message=message,
                    snapshot=snapshot,
                    symbol=symbol,
                    deterministic=deterministic,
                )
            except Exception:
                logger.exception("Could not persist AI chart observer error")
            with self._lock:
                self._errors += 1
                self._last_error = message[:1000]
        finally:
            with self._lock:
                self._pending = max(0, self._pending - 1)
            self._slots.release()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "remote_enabled": self.config.remote_enabled,
                "mode": self.config.mode,
                "model": self.config.model,
                "only_actionable": self.config.only_actionable,
                "submitted": self._submitted,
                "captured": self._captured,
                "completed": self._completed,
                "errors": self._errors,
                "pending": self._pending,
                "last_completed_utc": self._last_completed_utc,
                "last_error": self._last_error,
                "prompt_version": self.config.prompt_version,
                "schema_version": self.config.schema_version,
            }

    def shutdown(self, *, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)
