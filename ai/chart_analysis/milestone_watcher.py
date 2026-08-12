from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analytics import OutcomeAnalytics
from .config import ChartObserverConfig


logger = logging.getLogger("aaqts.ai_chart.milestones")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUBSCRIBERS_FILE = PROJECT_ROOT / "runtime" / "telegram_subscribers.json"


@dataclass(frozen=True)
class ResearchEvent:
    event_id: str
    text: str


def _finite_text(value: object, *, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number != number or number in {float("inf"), float("-inf")}:
        return "n/a"
    return f"{number:.3f}{suffix}"


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_subscribers(path: Path = DEFAULT_SUBSCRIBERS_FILE) -> set[int]:
    payload = _load_json(path, {"chat_ids": []})
    result: set[int] = set()
    for value in payload.get("chat_ids", []) or []:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def plan_research_events(
    summary: dict[str, Any],
    sent_events: set[str] | None = None,
) -> list[ResearchEvent]:
    """Return only newly crossed research milestones.

    This function is deliberately pure so milestone semantics can be tested
    without Telegram, market data, OpenAI, or the trading engine.
    """

    sent = set(sent_events or ())
    counts = summary.get("counts") or {}
    horizons = summary.get("horizons") or {}
    readiness = summary.get("readiness") or {}
    overall = summary.get("overall") or {}

    captures = int(counts.get("captures", 0) or 0)
    pending = int(counts.get("pending", 0) or 0)
    finalized = int(counts.get("finalized", 0) or 0)
    errors = int(counts.get("errors", 0) or 0)
    h6_samples = int((horizons.get("6") or {}).get("samples", 0) or 0)
    h12_samples = int((horizons.get("12") or {}).get("samples", 0) or 0)
    ready = bool(readiness.get("ready_for_overall_conclusions"))

    events: list[ResearchEvent] = []

    if h6_samples >= 1 and "horizon_6_first" not in sent:
        events.append(
            ResearchEvent(
                "horizon_6_first",
                "🧪 AAQTS AI RESEARCH UPDATE\n\n"
                "First +6 M15 horizon label is now available.\n"
                f"Captures: {captures}\nPending: {pending}\n"
                f"+6 samples: {h6_samples}\n"
                "No OpenAI call was used; capture-only research remains active.",
            )
        )

    if h12_samples >= 1 and "horizon_12_first" not in sent:
        events.append(
            ResearchEvent(
                "horizon_12_first",
                "✅ AAQTS FIRST FULL OUTCOME\n\n"
                "The first capture has completed the full +12 M15 forward window.\n"
                f"Finalized: {finalized}\nPending: {pending}\n"
                f"+12 samples: {h12_samples}\n"
                "The result was produced from completed future candles only.",
            )
        )

    for milestone in (10, 20):
        event_id = f"finalized_{milestone}"
        if finalized >= milestone and event_id not in sent:
            events.append(
                ResearchEvent(
                    event_id,
                    "📊 AAQTS AI RESEARCH MILESTONE\n\n"
                    f"{milestone} forward outcomes are now finalized.\n"
                    f"Captures: {captures}\nPending: {pending}\nErrors: {errors}\n"
                    f"Expectancy: {_finite_text(overall.get('expectancy_r'), suffix='R')}\n"
                    f"Profit factor: {_finite_text(overall.get('profit_factor'))}\n"
                    "Statistics remain descriptive until the 30-sample guardrail is met.",
                )
            )

    if ready and "dataset_ready" not in sent:
        events.append(
            ResearchEvent(
                "dataset_ready",
                "🚀 AAQTS AI RESEARCH DATASET READY\n\n"
                f"Finalized outcomes: {finalized}\n"
                f"Captures: {captures}\nPending: {pending}\nErrors: {errors}\n"
                f"Expectancy: {_finite_text(overall.get('expectancy_r'), suffix='R')}\n"
                f"Median: {_finite_text(overall.get('median_r'), suffix='R')}\n"
                f"Profit factor: {_finite_text(overall.get('profit_factor'))}\n"
                f"Positive-R rate: {_finite_text((overall.get('positive_r_rate') or 0) * 100, suffix='%')}\n\n"
                "The 30-finalized-sample overall guardrail is met. Bucket conclusions still require their own sample guardrails."
            )
        )

    return events


class ResearchMilestoneWatcher:
    def __init__(
        self,
        config: ChartObserverConfig | None = None,
        *,
        subscribers_file: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.config = config or ChartObserverConfig.from_env()
        self.analytics = OutcomeAnalytics(self.config)
        self.subscribers_file = subscribers_file or DEFAULT_SUBSCRIBERS_FILE
        self.state_file = state_file or Path(self.config.output_root) / "milestone_notifications.json"
        self.poll_seconds = max(
            20,
            int(os.getenv("AAQTS_AI_RESEARCH_WATCH_SECONDS", "60")),
        )

    def _state(self) -> dict[str, Any]:
        return _load_json(
            self.state_file,
            {"sent_events": [], "updated_utc": None},
        )

    def _save_sent(self, event_id: str) -> None:
        state = self._state()
        sent = {str(item) for item in state.get("sent_events", []) or []}
        sent.add(str(event_id))
        _write_json(
            self.state_file,
            {
                "sent_events": sorted(sent),
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _send_event(self, event: ResearchEvent, subscribers: set[int]) -> bool:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            logger.warning("Telegram token is unavailable; research milestone remains pending")
            return False
        if not subscribers:
            logger.info("No Telegram alert subscribers; research milestone remains pending")
            return False

        try:
            from telegram import Bot
        except ImportError:
            logger.exception("python-telegram-bot is unavailable")
            return False

        bot = Bot(token=token)
        delivered = 0
        for chat_id in sorted(subscribers):
            try:
                await bot.send_message(chat_id=chat_id, text=event.text)
                delivered += 1
            except Exception:
                logger.exception("Could not send research milestone to Telegram chat %s", chat_id)
        return delivered > 0

    async def check_once(self) -> list[str]:
        summary = self.analytics.refresh()
        state = self._state()
        sent = {str(item) for item in state.get("sent_events", []) or []}
        events = plan_research_events(summary, sent)
        if not events:
            return []

        subscribers = load_subscribers(self.subscribers_file)
        delivered: list[str] = []
        for event in events:
            if await self._send_event(event, subscribers):
                self._save_sent(event.event_id)
                delivered.append(event.event_id)
        return delivered

    async def run(self) -> None:
        logger.info(
            "AAQTS AI research milestone watcher started; polling every %ss",
            self.poll_seconds,
        )
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AI research milestone watcher iteration failed")
            await asyncio.sleep(self.poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AAQTS AI chart research milestone watcher")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Refresh analytics and process milestones once, then exit.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.getenv("AAQTS_AI_RESEARCH_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    watcher = ResearchMilestoneWatcher()
    if args.once:
        asyncio.run(watcher.check_once())
        return 0
    asyncio.run(watcher.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
