from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ai.chart_analysis.config import ChartObserverConfig
from ai.chart_analysis.milestone_watcher import (
    ResearchMilestoneWatcher,
    load_subscribers,
    plan_research_events,
)


def _summary(
    *,
    captures: int = 8,
    pending: int = 8,
    finalized: int = 0,
    h6: int = 0,
    h12: int = 0,
    ready: bool = False,
) -> dict:
    return {
        "counts": {
            "captures": captures,
            "pending": pending,
            "finalized": finalized,
            "errors": 0,
        },
        "horizons": {
            "1": {"samples": captures},
            "3": {"samples": max(0, captures - 2)},
            "6": {"samples": h6},
            "12": {"samples": h12},
        },
        "readiness": {"ready_for_overall_conclusions": ready},
        "overall": {
            "expectancy_r": 0.42 if finalized else None,
            "median_r": 0.31 if finalized else None,
            "profit_factor": 1.6 if finalized else None,
            "positive_r_rate": 0.6 if finalized else None,
        },
    }


def test_planner_tracks_first_six_and_twelve_bar_milestones():
    h6 = plan_research_events(_summary(h6=1))
    assert [event.event_id for event in h6] == ["horizon_6_first"]

    h12 = plan_research_events(
        _summary(finalized=1, pending=7, h6=1, h12=1),
        {"horizon_6_first"},
    )
    assert [event.event_id for event in h12] == ["horizon_12_first"]
    assert "completed future candles only" in h12[0].text


def test_planner_uses_only_latest_catchup_milestone():
    events = plan_research_events(
        _summary(captures=25, pending=5, finalized=20, h6=20, h12=20),
    )
    assert [event.event_id for event in events] == ["finalized_20"]


def test_ready_dataset_supersedes_older_milestones():
    events = plan_research_events(
        _summary(captures=35, pending=5, finalized=30, h6=30, h12=30, ready=True),
    )
    assert [event.event_id for event in events] == ["dataset_ready"]
    assert "DATASET READY" in events[0].text
    assert "30-finalized-sample" in events[0].text


def test_subscriber_loader_ignores_bad_ids(tmp_path):
    path = tmp_path / "telegram_subscribers.json"
    path.write_text(
        json.dumps({"chat_ids": [1001, "1002", "bad", None]}),
        encoding="utf-8",
    )
    assert load_subscribers(path) == {1001, 1002}


def test_delivered_event_is_restart_safe_and_not_repeated(tmp_path, monkeypatch):
    output_root = tmp_path / "ai_chart_analysis"
    subscribers = tmp_path / "telegram_subscribers.json"
    subscribers.write_text(json.dumps({"chat_ids": [1001]}), encoding="utf-8")
    state_file = output_root / "milestone_notifications.json"
    config = ChartObserverConfig(output_root=output_root)
    summary = _summary(h6=1)

    class AnalyticsStub:
        def refresh(self):
            return summary

    watcher = ResearchMilestoneWatcher(
        config,
        subscribers_file=subscribers,
        state_file=state_file,
    )
    watcher.analytics = AnalyticsStub()

    async def fake_send(event, subscriber_ids):
        assert subscriber_ids == {1001}
        return True

    monkeypatch.setattr(watcher, "_send_event", fake_send)
    assert asyncio.run(watcher.check_once()) == ["horizon_6_first"]
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["sent_events"] == ["horizon_6_first"]

    restarted = ResearchMilestoneWatcher(
        config,
        subscribers_file=subscribers,
        state_file=state_file,
    )
    restarted.analytics = AnalyticsStub()
    monkeypatch.setattr(restarted, "_send_event", fake_send)
    assert asyncio.run(restarted.check_once()) == []


def test_failed_delivery_keeps_milestone_pending(tmp_path, monkeypatch):
    output_root = tmp_path / "ai_chart_analysis"
    subscribers = tmp_path / "telegram_subscribers.json"
    subscribers.write_text(json.dumps({"chat_ids": [1001]}), encoding="utf-8")
    state_file = output_root / "milestone_notifications.json"
    watcher = ResearchMilestoneWatcher(
        ChartObserverConfig(output_root=output_root),
        subscribers_file=subscribers,
        state_file=state_file,
    )

    class AnalyticsStub:
        def refresh(self):
            return _summary(h6=1)

    watcher.analytics = AnalyticsStub()

    async def failed_send(event, subscriber_ids):
        return False

    monkeypatch.setattr(watcher, "_send_event", failed_send)
    assert asyncio.run(watcher.check_once()) == []
    assert not state_file.exists()


def test_windows_research_watcher_is_isolated_from_openai():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-ai-research-watcher.ps1").read_text(
        encoding="utf-8"
    )
    installer = (root / "scripts" / "windows" / "install-ai-research-watcher.ps1").read_text(
        encoding="utf-8"
    )

    assert 'AAQTS_AI_CHART_REMOTE_ENABLED = "false"' in launcher
    assert "Remove-Item Env:OPENAI_API_KEY" in launcher
    assert "telegram_token.dpapi" in launcher
    assert "ai.chart_analysis.milestone_watcher" in launcher
    assert 'AAQTS_AI_CHART_ANALYTICS_MIN_FINALIZED = "30"' in launcher
    assert 'AAQTS_AI_CHART_ANALYTICS_MIN_BUCKET = "10"' in launcher
    assert 'taskName = "AAQTS-AI-Research"' in installer
    assert "MultipleInstances IgnoreNew" in installer
    assert "Start-ScheduledTask" in installer
