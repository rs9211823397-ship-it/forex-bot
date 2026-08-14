"""Confirmed-bar 24-hour native indicator demo mode.

This fixes two parity issues in the first native experiment:
1. Never executes from the currently-forming M15 candle. Only a newly CLOSED
   15-minute candle can create an entry/reversal.
2. LuxAlgo Liquidity Sweeps is calculated/logged as chart context only. The
   supplied LuxAlgo source draws liquidity sweep/retest areas and does not expose
   BUY/SELL plotshape or alertcondition entries. Therefore it must not be silently
   converted into trade entries. The supplied AlgoAlpha Half Trend source DOES
   expose Bullish/Bearish Trend alertconditions; those are the executable signals.

Execution remains MT5 DEMO only through IndicatorOnlyBroker. The next confirmed
opposite Half Trend signal closes the managed indicator position and opens the new
one in the same event.
"""

from __future__ import annotations

import logging
import signal
import time
from typing import Any

from scripts.indicator_native_24h import (
    NativeIndicatorService,
    SignalEvent,
    TV_SYMBOL,
    half_trend_events,
    liquidity_sweep_events,
    _utc_now,
)
from scripts.indicator_only_24h import Alert

LOGGER = logging.getLogger("aaqts.indicator_native_confirmed")
MODE_NAME = "INDICATOR_NATIVE_24H_CONFIRMED"


class ConfirmedM15Service(NativeIndicatorService):
    def _status_confirmed(self, state: str, **extra: Any) -> None:
        self._status(
            state,
            mode=MODE_NAME,
            signal_confirmation="CLOSED_M15_ONLY",
            execution_signal_source="AlgoAlpha Half Trend bullish/bearish trend alerts",
            luxalgo_role="Liquidity sweep/retest chart context only; no invented BUY/SELL entry",
            **extra,
        )

    @staticmethod
    def _event_payload(event: SignalEvent) -> dict[str, Any]:
        return {
            "indicator": event.indicator,
            "side": event.side,
            "bar_time": event.bar_time,
            "subtype": event.subtype,
            "price": event.price,
        }

    def run(self) -> None:
        self._status_confirmed("STARTING")
        self.broker.connect()

        all_rates = self._rates()
        if len(all_rates) < 3:
            raise RuntimeError("Need at least three M15 bars")
        closed_rates = all_rates[:-1]  # MT5 position 0 includes the forming M15 bar.
        last_closed_time = int(closed_rates[-1]["time"])

        # Warm start: all existing closed-bar Half Trend signals are historical.
        for event in half_trend_events(closed_rates):
            self.seen.add(event.event_id)

        self._status_confirmed(
            "RUNNING",
            current_forming_bar_time=int(all_rates[-1]["time"]),
            last_closed_bar_time=last_closed_time,
            seeded_historical_events=len(self.seen),
        )
        self._append(
            {
                "event": "STARTED_CONFIRMED_M15",
                "forming_bar_time": int(all_rates[-1]["time"]),
                "last_closed_bar_time": last_closed_time,
                "seeded_historical_events": len(self.seen),
            }
        )

        while not self.stop_requested and _utc_now() < self.expires:
            cycle_started = time.perf_counter()
            try:
                all_rates = self._rates()
                if len(all_rates) < 3:
                    raise RuntimeError("Insufficient M15 bars")
                closed_rates = all_rates[:-1]
                forming_time = int(all_rates[-1]["time"])
                newest_closed_time = int(closed_rates[-1]["time"])

                # No execution work until a brand-new 15m candle has fully closed.
                if newest_closed_time != last_closed_time:
                    half_events = half_trend_events(closed_rates)
                    lux_events = liquidity_sweep_events(closed_rates)

                    lux_on_bar = [e for e in lux_events if e.bar_time == newest_closed_time]
                    if lux_on_bar:
                        self._append(
                            {
                                "event": "LUXALGO_CONTEXT_ON_CLOSED_BAR",
                                "bar_time": newest_closed_time,
                                "events": [self._event_payload(e) for e in lux_on_bar],
                            }
                        )

                    executable = [
                        e
                        for e in half_events
                        if e.bar_time == newest_closed_time and e.event_id not in self.seen
                    ]
                    executable.sort(key=lambda e: (e.bar_time, e.subtype))

                    for event in executable:
                        self.seen.add(event.event_id)
                        alert = Alert(
                            alert_id=event.event_id,
                            indicator=event.indicator,
                            symbol=TV_SYMBOL,
                            timeframe="15",
                            side=event.side,
                            received_at=_utc_now(),
                            bar_time=str(event.bar_time),
                            raw={
                                "subtype": event.subtype,
                                "calculated_price": event.price,
                                "source": "MT5_NATIVE_CONFIRMED_M15",
                                "closed_bar_only": True,
                                "luxalgo_context": [self._event_payload(e) for e in lux_on_bar],
                            },
                        )
                        started = time.perf_counter()
                        try:
                            result = self.broker.reverse_on_signal(alert)
                            latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                            self._append(
                                {
                                    "event": "EXECUTED_CONFIRMED_SIGNAL",
                                    "signal": self._event_payload(event),
                                    "latency_ms": latency_ms,
                                    "result": result,
                                }
                            )
                            self._status_confirmed(
                                "RUNNING",
                                current_forming_bar_time=forming_time,
                                last_closed_bar_time=newest_closed_time,
                                last_signal=self._event_payload(event),
                                last_execution=result,
                                latency_ms=latency_ms,
                            )
                        except Exception as exc:
                            LOGGER.exception("Confirmed M15 execution blocked")
                            self._append(
                                {
                                    "event": "EXECUTION_BLOCKED",
                                    "signal": self._event_payload(event),
                                    "error": str(exc),
                                }
                            )
                            self._status_confirmed(
                                "RUNNING",
                                current_forming_bar_time=forming_time,
                                last_closed_bar_time=newest_closed_time,
                                last_signal=self._event_payload(event),
                                last_error=str(exc),
                            )

                    last_closed_time = newest_closed_time

                elapsed_ms = round((time.perf_counter() - cycle_started) * 1000.0, 3)
                self._status_confirmed(
                    "RUNNING",
                    current_forming_bar_time=forming_time,
                    last_closed_bar_time=newest_closed_time,
                    last_cycle_ms=elapsed_ms,
                )
            except Exception as exc:
                LOGGER.exception("Confirmed native indicator scan failed")
                self._append({"event": "SCAN_ERROR", "error": str(exc)})
                self._status_confirmed("RUNNING", last_error=str(exc))

            time.sleep(max(0.1, float(__import__("scripts.indicator_native_24h", fromlist=["POLL_SECONDS"]).POLL_SECONDS)))

        self._status_confirmed("STOPPED" if self.stop_requested else "EXPIRED")
        self.broker.shutdown()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    service = ConfirmedM15Service()

    def stop(*_args: object) -> None:
        service.stop_requested = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    service.run()


if __name__ == "__main__":
    main()
