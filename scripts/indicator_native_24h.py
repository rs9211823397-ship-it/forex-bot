"""24-hour native indicator-only demo execution mode.

Ports the user-supplied Pine logic for:
- LuxAlgo Liquidity Sweeps: Swings=5, Wicks + Outbreaks & Retest, Extend=true, Max bars=300
- AlgoAlpha Half Trend Regression: Amplitude=2, Channel Deviation=2, Linear Regression Length=7

Signals are evaluated from live Exness MT5 BTCUSDm 15-minute candles, including the
currently-forming candle. Any newly observed BUY/SELL signal from either indicator
opens/reverses the demo position. The next opposite signal closes the current trade
and opens the opposite trade in the same event. Existing broker safety checks from
IndicatorOnlyBroker remain active.

LuxAlgo source: CC BY-NC-SA 4.0, © LuxAlgo.
AlgoAlpha source: MPL 2.0, © AlgoAlpha.
This port is for the temporary non-commercial demo test requested by the user.
"""

from __future__ import annotations

import json
import logging
import math
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.indicator_only_24h import Alert, IndicatorOnlyBroker

LOGGER = logging.getLogger("aaqts.indicator_native")
MODE_NAME = "INDICATOR_NATIVE_24H"
TIMEFRAME = "15m"
TV_SYMBOL = "BTCUSD"
BROKER_SYMBOL = "BTCUSDm"
POLL_SECONDS = float(os.getenv("AAQTS_INDICATOR_NATIVE_POLL_SECONDS", "1.0"))
DURATION_HOURS = min(24.0, max(0.1, float(os.getenv("AAQTS_INDICATOR_DURATION_HOURS", "24"))))
HISTORY_BARS = max(250, int(os.getenv("AAQTS_INDICATOR_NATIVE_HISTORY_BARS", "500")))


@dataclass
class Pivot:
    price: float
    index: int
    broken: bool = False
    mitigated: bool = False
    taken: bool = False
    wick: bool = False


@dataclass(frozen=True)
class SignalEvent:
    indicator: str
    side: str
    bar_time: int
    subtype: str
    price: float

    @property
    def event_id(self) -> str:
        return f"{self.indicator}|{self.side}|{self.bar_time}|{self.subtype}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _linreg(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0:
        return out
    sx = length * (length - 1) / 2.0
    sxx = (length - 1) * length * (2 * length - 1) / 6.0
    denom = length * sxx - sx * sx
    for i in range(length - 1, len(values)):
        y = values[i - length + 1 : i + 1]
        sy = sum(y)
        sxy = sum(j * yj for j, yj in enumerate(y))
        slope = 0.0 if denom == 0 else (length * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / length
        out[i] = intercept + slope * (length - 1)
    return out


def _sma(values: list[float | None], length: int, i: int) -> float | None:
    if i - length + 1 < 0:
        return None
    window = values[i - length + 1 : i + 1]
    if any(v is None for v in window):
        return None
    return sum(float(v) for v in window) / length


def _highest(values: list[float | None], length: int, i: int) -> float | None:
    if i - length + 1 < 0:
        return None
    window = values[i - length + 1 : i + 1]
    if any(v is None for v in window):
        return None
    return max(float(v) for v in window)


def _lowest(values: list[float | None], length: int, i: int) -> float | None:
    if i - length + 1 < 0:
        return None
    window = values[i - length + 1 : i + 1]
    if any(v is None for v in window):
        return None
    return min(float(v) for v in window)


def half_trend_events(rates: list[dict[str, float]]) -> list[SignalEvent]:
    """Port of user-supplied Half Trend Regression [AlgoAlpha] Pine logic."""
    amplitude = 2
    linreglen = 7
    highs_raw = [float(r["high"]) for r in rates]
    lows_raw = [float(r["low"]) for r in rates]
    closes_raw = [float(r["close"]) for r in rates]
    highs = _linreg(highs_raw, linreglen)
    lows = _linreg(lows_raw, linreglen)
    closes = _linreg(closes_raw, linreglen)

    trend_line: float | None = None
    trend_direction: int | None = None
    max_low = lows_raw[0]
    min_high = highs_raw[0]
    events: list[SignalEvent] = []

    for i in range(len(rates)):
        high_ma = _sma(highs, amplitude, i)
        low_ma = _sma(lows, amplitude, i)
        highest_high = _highest(highs, amplitude, i)
        lowest_low = _lowest(lows, amplitude, i)
        if any(v is None for v in (high_ma, low_ma, highest_high, lowest_low, highs[i], lows[i], closes[i])):
            continue

        old_direction = trend_direction
        if trend_direction is None and i > linreglen:
            trend_direction = 1
            trend_line = float(lowest_low)
        else:
            if trend_direction == 1:
                max_low = max(max_low, float(lowest_low))
                prev_low = lows[i - 1] if i > 0 else None
                if prev_low is not None and float(high_ma) < max_low and float(closes[i]) < float(prev_low):
                    trend_direction = -1
                    trend_line = float(highest_high)
                    min_high = float(highs[i])
            elif trend_direction == -1:
                min_high = min(min_high, float(highest_high))
                prev_high = highs[i - 1] if i > 0 else None
                if prev_high is not None and float(low_ma) > min_high and float(closes[i]) > float(prev_high):
                    trend_direction = 1
                    trend_line = float(lowest_low)
                    max_low = float(lows[i])

        if trend_direction == 1 and trend_line is not None:
            trend_line = max(trend_line, float(lowest_low))
        elif trend_direction == -1 and trend_line is not None:
            trend_line = min(trend_line, float(highest_high))

        if old_direction == 1 and trend_direction == -1:
            events.append(SignalEvent("ALGOALPHA_HALF_TREND", "SELL", int(rates[i]["time"]), "BEARISH_TREND", closes_raw[i]))
        elif old_direction == -1 and trend_direction == 1:
            events.append(SignalEvent("ALGOALPHA_HALF_TREND", "BUY", int(rates[i]["time"]), "BULLISH_TREND", closes_raw[i]))
    return events


def _pivot_high(highs: list[float], n: int, length: int) -> tuple[float, int] | None:
    center = n - length
    left = center - length
    right = center + length
    if left < 0 or right >= len(highs):
        return None
    window = highs[left : right + 1]
    value = highs[center]
    if value == max(window):
        return value, center
    return None


def _pivot_low(lows: list[float], n: int, length: int) -> tuple[float, int] | None:
    center = n - length
    left = center - length
    right = center + length
    if left < 0 or right >= len(lows):
        return None
    window = lows[left : right + 1]
    value = lows[center]
    if value == min(window):
        return value, center
    return None


def liquidity_sweep_events(rates: list[dict[str, float]]) -> list[SignalEvent]:
    """Port of supplied LuxAlgo Pine with Wicks + Outbreaks & Retest selected."""
    length = 5
    highs = [float(r["high"]) for r in rates]
    lows = [float(r["low"]) for r in rates]
    closes = [float(r["close"]) for r in rates]
    piv_h: list[Pivot] = []
    piv_l: list[Pivot] = []
    events: list[SignalEvent] = []

    for n in range(len(rates)):
        ph = _pivot_high(highs, n, length)
        pl = _pivot_low(lows, n, length)
        if ph is not None:
            piv_h.insert(0, Pivot(ph[0], ph[1]))
        if pl is not None:
            piv_l.insert(0, Pivot(pl[0], pl[1]))

        # Pine loops from oldest to newest (size-1 down to 0).
        for idx in range(len(piv_h) - 1, -1, -1):
            get = piv_h[idx]
            if not get.mitigated:
                if not get.broken:
                    if closes[n] > get.price:
                        get.broken = True
                    if not get.wick and highs[n] > get.price and closes[n] < get.price:
                        get.wick = True
                        events.append(SignalEvent("LUXALGO_LIQUIDITY_SWEEPS", "SELL", int(rates[n]["time"]), "BEARISH_WICK_SWEEP", closes[n]))
                else:
                    if closes[n] < get.price:
                        get.mitigated = True
                    if lows[n] < get.price and closes[n] > get.price:
                        get.taken = True
                        events.append(SignalEvent("LUXALGO_LIQUIDITY_SWEEPS", "BUY", int(rates[n]["time"]), "BULLISH_BREAKOUT_RETEST", closes[n]))
            if n - get.index > 2000 or get.mitigated or get.taken:
                piv_h.pop(idx)

        for idx in range(len(piv_l) - 1, -1, -1):
            get = piv_l[idx]
            if not get.mitigated:
                if not get.broken:
                    if closes[n] < get.price:
                        get.broken = True
                    if not get.wick and lows[n] < get.price and closes[n] > get.price:
                        get.wick = True
                        events.append(SignalEvent("LUXALGO_LIQUIDITY_SWEEPS", "BUY", int(rates[n]["time"]), "BULLISH_WICK_SWEEP", closes[n]))
                else:
                    if closes[n] > get.price:
                        get.mitigated = True
                    if highs[n] > get.price and closes[n] < get.price:
                        get.taken = True
                        events.append(SignalEvent("LUXALGO_LIQUIDITY_SWEEPS", "SELL", int(rates[n]["time"]), "BEARISH_BREAKOUT_RETEST", closes[n]))
            if n - get.index > 2000 or get.mitigated or get.taken:
                piv_l.pop(idx)

    return events


class NativeIndicatorService:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.status_path = self.runtime / "indicator_native_24h_status.json"
        self.log_path = self.runtime / "indicator_native_24h.jsonl"
        self.started = _utc_now()
        self.expires = self.started + timedelta(hours=DURATION_HOURS)
        self.broker = IndicatorOnlyBroker()
        self.stop_requested = False
        self.seen: set[str] = set()

    def _append(self, event: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _utc_now().isoformat(), **event}, sort_keys=True, default=str) + "\n")

    def _status(self, state: str, **extra: Any) -> None:
        body = {
            "mode": MODE_NAME,
            "state": state,
            "timeframe": TIMEFRAME,
            "symbol": TV_SYMBOL,
            "broker_symbol": BROKER_SYMBOL,
            "started_utc": self.started.isoformat(),
            "expires_utc": self.expires.isoformat(),
            "heartbeat_utc": _utc_now().isoformat(),
            "poll_seconds": POLL_SECONDS,
            "data_source": "Exness MT5 BTCUSDm",
            "indicator_settings": {
                "LuxAlgo - Liquidity Sweeps": {"swings": 5, "options": "Wicks + Outbreaks & Retest", "extend": True, "max_bars": 300},
                "AlgoAlpha - Half Trend": {"amplitude": 2, "channel_deviation": 2, "linear_regression_length": 7},
            },
            "tp_rule": "next opposite indicator signal closes current position and opens next trade",
            **extra,
        }
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)

    def _rates(self) -> list[dict[str, float]]:
        mt5 = self.broker.mt5
        raw = mt5.copy_rates_from_pos(BROKER_SYMBOL, mt5.TIMEFRAME_M15, 0, HISTORY_BARS)
        if raw is None or len(raw) < 120:
            raise RuntimeError(f"Insufficient M15 rates for {BROKER_SYMBOL}: {mt5.last_error()}")
        rows: list[dict[str, float]] = []
        for r in raw:
            rows.append({"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])})
        return rows

    def _seed_seen(self, events: list[SignalEvent], current_bar_time: int) -> None:
        # Historical signals are evidence only; never execute them at startup.
        for e in events:
            if e.bar_time < current_bar_time:
                self.seen.add(e.event_id)

    def run(self) -> None:
        self._status("STARTING")
        self.broker.connect()
        rates = self._rates()
        all_events = liquidity_sweep_events(rates) + half_trend_events(rates)
        current_bar_time = int(rates[-1]["time"])
        self._seed_seen(all_events, current_bar_time)
        self._status("RUNNING", current_bar_time=current_bar_time)
        self._append({"event": "STARTED", "current_bar_time": current_bar_time, "seeded_historical_events": len(self.seen)})

        while not self.stop_requested and _utc_now() < self.expires:
            cycle_started = time.perf_counter()
            try:
                rates = self._rates()
                events = liquidity_sweep_events(rates) + half_trend_events(rates)
                events.sort(key=lambda e: (e.bar_time, e.indicator, e.subtype))
                latest_bar = int(rates[-1]["time"])
                new_events = [e for e in events if e.event_id not in self.seen and e.bar_time >= latest_bar]
                for event in new_events:
                    self.seen.add(event.event_id)
                    alert = Alert(
                        alert_id=event.event_id,
                        indicator=event.indicator,
                        symbol=TV_SYMBOL,
                        timeframe="15",
                        side=event.side,
                        received_at=_utc_now(),
                        bar_time=str(event.bar_time),
                        raw={"subtype": event.subtype, "calculated_price": event.price, "source": "MT5_NATIVE"},
                    )
                    started = time.perf_counter()
                    try:
                        result = self.broker.reverse_on_signal(alert)
                        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                        self._append({"event": "EXECUTED_SIGNAL", "signal": event.__dict__, "latency_ms": latency_ms, "result": result})
                        self._status("RUNNING", current_bar_time=latest_bar, last_signal=event.__dict__, last_execution=result, latency_ms=latency_ms)
                    except Exception as exc:  # fail closed, continue observing
                        LOGGER.exception("Native indicator execution blocked")
                        self._append({"event": "EXECUTION_BLOCKED", "signal": event.__dict__, "error": str(exc)})
                        self._status("RUNNING", current_bar_time=latest_bar, last_signal=event.__dict__, last_error=str(exc))
                elapsed_ms = round((time.perf_counter() - cycle_started) * 1000.0, 3)
                self._status("RUNNING", current_bar_time=latest_bar, last_cycle_ms=elapsed_ms)
            except Exception as exc:
                LOGGER.exception("Native indicator scan failed")
                self._append({"event": "SCAN_ERROR", "error": str(exc)})
                self._status("RUNNING", last_error=str(exc))
            time.sleep(max(0.1, POLL_SECONDS))

        self._status("STOPPED" if self.stop_requested else "EXPIRED")
        self.broker.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    service = NativeIndicatorService()

    def stop(*_args: object) -> None:
        service.stop_requested = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    service.run()


if __name__ == "__main__":
    main()
