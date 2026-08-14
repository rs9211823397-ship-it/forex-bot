"""Telegram overlay for the temporary INDICATOR_NATIVE_24H experiment.

This module leaves the normal AAQTS Telegram manager intact, but when the native
indicator status heartbeat is fresh it surfaces that mode in /menu and /status
and pushes subscribed chats signal/execution events from the native JSONL log.
Telegram never opens an MT5 session here; it only reads runtime files produced
by the native worker.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram.error import TelegramError

from telegram_bot import bot as base
from telegram_bot.alert_monitor import load_subscribers

STATUS_PATH = base.RUNTIME_DIR / "indicator_native_24h_status.json"
EVENTS_PATH = base.RUNTIME_DIR / "indicator_native_24h.jsonl"
FRESH_SECONDS = 20.0

_BASE_HOME_TEXT = base._home_text
_BASE_STATUS_COMMAND = base.status_command
_BASE_POST_INIT = base.post_init
_BASE_POST_SHUTDOWN = base.post_shutdown


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def native_state() -> dict[str, Any]:
    state = _read_json(STATUS_PATH)
    heartbeat = _parse_utc(state.get("heartbeat_utc"))
    if heartbeat is None:
        return {}
    age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
    if age < -5 or age > FRESH_SECONDS:
        return {}
    if str(state.get("mode", "")).upper() != "INDICATOR_NATIVE_24H":
        return {}
    return state


def _latest_native_event() -> dict[str, Any]:
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return {}
    for line in reversed(lines[-250:]):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("event") in {
            "EXECUTED_SIGNAL", "EXECUTION_BLOCKED", "SIGNAL_OBSERVED"
        }:
            return item
    return {}


def _native_summary(role_name: str) -> str:
    state = native_state()
    if not state:
        return ""
    latest = _latest_native_event()
    signal = latest.get("signal") if isinstance(latest.get("signal"), dict) else {}
    indicator = str(signal.get("indicator", "None"))
    indicator = indicator.replace("ALGOALPHA_HALF_TREND", "Half Trend").replace(
        "LUXALGO_LIQUIDITY_SWEEPS", "Liquidity Sweeps"
    )
    side = str(signal.get("side", "WAITING"))
    subtype = str(signal.get("subtype", "None"))
    last_event = str(latest.get("event", "None"))
    return (
        "🧪 AAQTS INDICATOR 24H\n\n"
        "Account: Exness Demo · MT5 DEMO\n"
        f"Mode: {state.get('mode', 'INDICATOR_NATIVE_24H')}\n"
        f"State: {state.get('state', 'UNKNOWN')}\n"
        f"Symbol: {state.get('broker_symbol', 'BTCUSDm')}\n"
        f"Timeframe: {state.get('timeframe', '15m')}\n"
        "Execution: confirmed 15m Half Trend signals\n"
        "LuxAlgo: liquidity context only\n"
        f"Last event: {last_event}\n"
        f"Last signal: {side} · {indicator} · {subtype}\n"
        f"Heartbeat: {state.get('heartbeat_utc', 'Unknown')}\n"
        f"Expires: {state.get('expires_utc', 'Unknown')}\n"
        "TP rule: next opposite confirmed signal closes + reverses\n"
        "Normal AAQTS engine: DISABLED\n"
        f"Role: {role_name}"
    )


def patched_home_text(role: base.TelegramRole) -> str:
    summary = _native_summary(role.name.replace("_", " "))
    return summary or _BASE_HOME_TEXT(role)


async def patched_status_command(update, context) -> None:
    if await base.ensure_access(update) is None:
        return
    if not update.message:
        return
    summary = _native_summary((base._role(update) or base.READ_ROLE).name.replace("_", " "))
    if summary:
        await update.message.reply_text(summary)
        return
    await _BASE_STATUS_COMMAND(update, context)


def _format_event(event: dict[str, Any]) -> str | None:
    kind = str(event.get("event", ""))
    if kind not in {"EXECUTED_SIGNAL", "EXECUTION_BLOCKED"}:
        return None
    sig = event.get("signal") if isinstance(event.get("signal"), dict) else {}
    side = str(sig.get("side", "UNKNOWN"))
    indicator = str(sig.get("indicator", "UNKNOWN")).replace(
        "ALGOALPHA_HALF_TREND", "Half Trend"
    ).replace("LUXALGO_LIQUIDITY_SWEEPS", "Liquidity Sweeps")
    subtype = str(sig.get("subtype", ""))
    price = sig.get("price")
    if kind == "EXECUTION_BLOCKED":
        return (
            "⚠️ INDICATOR 24H EXECUTION BLOCKED\n\n"
            f"Signal: {side} · {indicator}\n"
            f"Type: {subtype}\n"
            f"Calculated price: {price}\n"
            f"Reason: {event.get('error', 'Unknown')}"
        )
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    action = str(result.get("action", "EXECUTED"))
    opened = result.get("opened") if isinstance(result.get("opened"), dict) else {}
    closed = result.get("closed") if isinstance(result.get("closed"), dict) else {}
    lines = [
        "🚨 INDICATOR 24H TRADE",
        "",
        f"Action: {action}",
        f"Signal: {side} · {indicator}",
        f"Type: {subtype}",
    ]
    if opened:
        lines.extend([
            f"Entry: {opened.get('entry_price', 'N/A')}",
            f"SL: {opened.get('stop_loss', 'N/A')}",
            f"Lot: {opened.get('volume', 'N/A')}",
        ])
    if closed:
        lines.extend([
            f"Closed ticket: {closed.get('ticket', 'N/A')}",
            f"Exit: {closed.get('exit_price', 'N/A')}",
        ])
    lines.append("Rule: next opposite confirmed signal = exit + reverse")
    return "\n".join(lines)


async def _native_event_monitor(application) -> None:
    offset = 0
    try:
        if EVENTS_PATH.exists():
            offset = EVENTS_PATH.stat().st_size
    except OSError:
        offset = 0
    while True:
        await asyncio.sleep(2.0)
        if not native_state():
            continue
        try:
            size = EVENTS_PATH.stat().st_size
            if size < offset:
                offset = 0
            if size == offset:
                continue
            with EVENTS_PATH.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
        except (FileNotFoundError, OSError):
            continue
        for line in chunk.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            text = _format_event(event)
            if not text:
                continue
            for chat_id in load_subscribers():
                try:
                    await application.bot.send_message(chat_id=chat_id, text=text)
                except TelegramError:
                    base.logger.warning("Could not send native 24h alert to chat %s", chat_id)


async def patched_post_init(application) -> None:
    await _BASE_POST_INIT(application)
    application.bot_data["native_24h_alert_task"] = asyncio.create_task(
        _native_event_monitor(application), name="aaqts-native-24h-telegram-monitor"
    )


async def patched_post_shutdown(application) -> None:
    task = application.bot_data.get("native_24h_alert_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await _BASE_POST_SHUTDOWN(application)


def main() -> None:
    base._home_text = patched_home_text
    base.status_command = patched_status_command
    base.post_init = patched_post_init
    base.post_shutdown = patched_post_shutdown
    base.main()


if __name__ == "__main__":
    main()
