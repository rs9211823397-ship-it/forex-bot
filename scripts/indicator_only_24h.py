"""Temporary 24-hour TradingView indicator-only execution mode.

Direction is supplied by TradingView alerts from the two approved indicators:
- LuxAlgo - Liquidity Sweeps (Swings 5, Only Wicks, Max bars 300)
- AlgoAlpha - Half Trend (Amplitude 2, Channel Deviation 2, Linear Regression 7)

The service hard-locks alerts to a 15-minute timeframe. AAQTS strategy/regime
filters are intentionally bypassed for this temporary mode, while broker/demo
identity checks, spread, margin, duplicate-direction and protective-stop checks
remain active.

The user's dynamic TP rule is implemented as a signal-to-signal reversal:
when the next opposite valid alert arrives, the current position is closed at
market and the new opposite position is opened immediately. The close fill of
that prior position is therefore its logical TP/exit and the next trade's entry
is taken from the same reversal event. No fixed broker TP is submitted because
that future price is unknowable at the time of the original entry.

This module is deliberately standalone so the normal AAQTS engine can be
stopped for the 24-hour experiment without altering production strategy logic.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import isfinite
from pathlib import Path
from typing import Any

from config.settings import (
    MT5_EXPECTED_LOGIN,
    MT5_FIXED_LOT,
    MT5_LOGIN,
    MT5_MAX_SPREAD_STOP_RATIO,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_SYMBOL_SUFFIX,
    MT5_TERMINAL_PATH,
    MT5_USE_PREAUTHENTICATED_SESSION,
)
from config.symbols import symbol_by_broker
from mt5_ipc import serialized_mt5_call


LOGGER = logging.getLogger("aaqts.indicator_only")
MAGIC = 20260814
MODE_NAME = "INDICATOR_ONLY_24H"
APPROVED_INDICATORS = {
    "LUXALGO_LIQUIDITY_SWEEPS": "LuxAlgo - Liquidity Sweeps",
    "ALGOALPHA_HALF_TREND": "AlgoAlpha - Half Trend",
}
VALID_SIDES = {"BUY", "SELL"}
EXPECTED_TIMEFRAME = "15"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _normalize_timeframe(value: object) -> str:
    text = str(value or "").strip().lower()
    aliases = {"15m": "15", "15min": "15", "15minute": "15", "15minutes": "15"}
    return aliases.get(text, text)


def _normalize_symbol(value: object) -> str:
    text = str(value or "").strip().upper().replace("/", "")
    for prefix in ("BITSTAMP:", "BINANCE:", "COINBASE:", "OANDA:", "FOREXCOM:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _normalize_indicator(value: object) -> str:
    text = " ".join(str(value or "").strip().upper().replace("_", " ").split())
    if "LUXALGO" in text and "LIQUIDITY" in text and "SWEEP" in text:
        return "LUXALGO_LIQUIDITY_SWEEPS"
    if "ALGOALPHA" in text and "HALF" in text and "TREND" in text:
        return "ALGOALPHA_HALF_TREND"
    return str(value or "").strip().upper()


@dataclass(frozen=True)
class Alert:
    alert_id: str
    indicator: str
    symbol: str
    timeframe: str
    side: str
    received_at: datetime
    bar_time: str
    raw: dict[str, Any]


class IndicatorOnlyBroker:
    """Minimal demo-only execution adapter for the temporary indicator test."""

    def __init__(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - Windows deployment only
            raise RuntimeError("MetaTrader5 package is required on the VPS") from exc
        self.mt5 = mt5
        self.fixed_lot = _env_float(
            "AAQTS_INDICATOR_FIXED_LOT",
            float(MT5_FIXED_LOT),
            minimum=0.01,
            maximum=100.0,
        )
        # Protective catastrophe stop only; it does not create direction.
        self.stop_percent = _env_float(
            "AAQTS_INDICATOR_STOP_PERCENT", 1.0, minimum=0.05, maximum=20.0
        )
        self.max_spread_stop_ratio = _env_float(
            "AAQTS_INDICATOR_MAX_SPREAD_STOP_RATIO",
            float(MT5_MAX_SPREAD_STOP_RATIO),
            minimum=0.01,
            maximum=1.0,
        )
        self.deviation = _env_int(
            "AAQTS_INDICATOR_DEVIATION_POINTS", 20, minimum=0, maximum=500
        )
        self.connected = False

    @serialized_mt5_call
    def connect(self) -> None:
        kwargs: dict[str, Any] = {"path": MT5_TERMINAL_PATH}
        if not MT5_USE_PREAUTHENTICATED_SESSION and MT5_LOGIN:
            if not MT5_PASSWORD or not MT5_SERVER:
                raise RuntimeError("MT5 explicit login requires password and server")
            kwargs.update(
                login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER
            )
        if not self.mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {self.mt5.last_error()}")
        self.connected = True
        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if terminal is None or account is None:
            self.shutdown()
            raise RuntimeError("MT5 terminal/account information unavailable")
        expected = int(MT5_EXPECTED_LOGIN) if MT5_EXPECTED_LOGIN else None
        if expected is not None and int(getattr(account, "login", -1)) != expected:
            self.shutdown()
            raise RuntimeError("Connected MT5 login does not match pinned demo account")
        demo_mode = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        if getattr(account, "trade_mode", None) != demo_mode:
            self.shutdown()
            raise RuntimeError("Indicator-only mode is locked to MT5 DEMO")
        if not getattr(terminal, "trade_allowed", False):
            self.shutdown()
            raise RuntimeError("Algorithmic trading is disabled in MT5 terminal")
        if not getattr(account, "trade_allowed", False) or not getattr(account, "trade_expert", False):
            self.shutdown()
            raise RuntimeError("Trading/expert trading is disabled on demo account")

    @serialized_mt5_call
    def shutdown(self) -> None:
        if self.connected:
            self.mt5.shutdown()
        self.connected = False

    def _ensure(self) -> None:
        if self.connected and self.mt5.account_info() is not None:
            return
        try:
            self.mt5.shutdown()
        except Exception:
            pass
        self.connected = False
        self.connect()

    def _broker_symbol(self, tv_symbol: str) -> str:
        canonical = _normalize_symbol(tv_symbol)
        # Validate against the AAQTS catalog, then append configured Exness suffix.
        definition = symbol_by_broker(canonical)
        if definition.entry_policy != "OPEN":
            raise RuntimeError(f"{canonical} is not open-entry eligible")
        return f"{definition.broker_symbol}{MT5_SYMBOL_SUFFIX}"

    def _info_tick(self, symbol: str) -> tuple[Any, Any]:
        self._ensure()
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Unknown MT5 symbol {symbol}")
        if not getattr(info, "visible", False) and not self.mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Could not select MT5 symbol {symbol}")
        info = self.mt5.symbol_info(symbol)
        tick = self.mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            raise RuntimeError(f"Quote unavailable for {symbol}")
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if not (isfinite(bid) and isfinite(ask) and bid > 0 and ask >= bid):
            raise RuntimeError(f"Invalid bid/ask for {symbol}")
        tick_s = float(getattr(tick, "time_msc", 0.0) or 0.0) / 1000.0
        if tick_s <= 0:
            tick_s = float(getattr(tick, "time", 0.0) or 0.0)
        age = _utc_now().timestamp() - tick_s
        if tick_s <= 0 or age < -5 or age > 15:
            raise RuntimeError(f"Stale MT5 quote for {symbol}: {age:.1f}s")
        return info, tick

    def _normalize_volume(self, volume: float, info: Any) -> float:
        minimum = float(info.volume_min)
        maximum = float(info.volume_max)
        step = float(info.volume_step)
        if volume < minimum or volume > maximum:
            raise RuntimeError(f"Volume {volume} outside broker limits {minimum}..{maximum}")
        steps = int(((volume - minimum) / step) + 1e-12)
        return round(minimum + steps * step, 8)

    def _filling(self, info: Any) -> int:
        mode = int(getattr(info, "filling_mode", 0))
        if mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        if mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _managed_positions(self, broker_symbol: str) -> list[Any]:
        self._ensure()
        raw = self.mt5.positions_get(symbol=broker_symbol)
        if raw is None:
            raise RuntimeError(f"positions_get failed: {self.mt5.last_error()}")
        return [p for p in raw if int(getattr(p, "magic", 0) or 0) == MAGIC]

    def _side(self, position: Any) -> str:
        return "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"

    def _check_margin(self, symbol: str, order_type: int, volume: float, price: float) -> None:
        required = self.mt5.order_calc_margin(order_type, symbol, volume, price)
        account = self.mt5.account_info()
        if required is None or account is None:
            raise RuntimeError("Margin validation unavailable")
        free = float(getattr(account, "margin_free", 0.0) or 0.0)
        if float(required) > free + 1e-12:
            raise RuntimeError(f"Insufficient free margin: need {required:.2f}, free {free:.2f}")

    def _send(self, request: dict[str, Any]) -> Any:
        check = self.mt5.order_check(request)
        if check is None or int(getattr(check, "retcode", -1)) != 0:
            detail = getattr(check, "comment", self.mt5.last_error())
            raise RuntimeError(f"MT5 order_check rejected request: {detail}")
        result = self.mt5.order_send(request)
        done = int(getattr(self.mt5, "TRADE_RETCODE_DONE", 10009))
        if result is None or int(getattr(result, "retcode", -1)) != done:
            detail = getattr(result, "comment", self.mt5.last_error())
            raise RuntimeError(f"MT5 order_send failed: {detail}")
        return result

    def close_position(self, position: Any, *, reason: str) -> dict[str, Any]:
        info, tick = self._info_tick(position.symbol)
        closing_buy = position.type != self.mt5.POSITION_TYPE_BUY
        volume = self._normalize_volume(float(position.volume), info)
        price = float(tick.ask if closing_buy else tick.bid)
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY if closing_buy else self.mt5.ORDER_TYPE_SELL,
            "position": int(position.ticket),
            "price": round(price, int(info.digits)),
            "deviation": self.deviation,
            "magic": MAGIC,
            "comment": f"IND24H EXIT {reason}"[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(info),
        }
        result = self._send(request)
        return {
            "ticket": int(position.ticket),
            "side": self._side(position),
            "exit_price": float(getattr(result, "price", 0.0) or price),
            "deal": int(getattr(result, "deal", 0) or 0),
        }

    def open_position(self, tv_symbol: str, side: str, *, indicator: str) -> dict[str, Any]:
        broker_symbol = self._broker_symbol(tv_symbol)
        info, tick = self._info_tick(broker_symbol)
        existing = self._managed_positions(broker_symbol)
        if existing:
            raise RuntimeError("Indicator position still open; refusing duplicate entry")
        is_buy = side == "BUY"
        entry = float(tick.ask if is_buy else tick.bid)
        stop_distance = entry * (self.stop_percent / 100.0)
        stop = entry - stop_distance if is_buy else entry + stop_distance
        spread = float(tick.ask) - float(tick.bid)
        ratio = spread / max(stop_distance, float(info.point), 1e-12)
        if ratio > self.max_spread_stop_ratio:
            raise RuntimeError(
                f"Spread too wide: spread/stop={ratio:.3f} > {self.max_spread_stop_ratio:.3f}"
            )
        minimum = max(int(getattr(info, "trade_stops_level", 0) or 0), 0) * float(info.point)
        if minimum and stop_distance < minimum:
            raise RuntimeError("Protective stop violates broker minimum stop distance")
        volume = self._normalize_volume(self.fixed_lot, info)
        order_type = self.mt5.ORDER_TYPE_BUY if is_buy else self.mt5.ORDER_TYPE_SELL
        self._check_margin(broker_symbol, order_type, volume, entry)
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": volume,
            "type": order_type,
            "price": round(entry, int(info.digits)),
            "sl": round(stop, int(info.digits)),
            # Intentionally no fixed broker TP: next opposite signal is logical TP.
            "tp": 0.0,
            "deviation": self.deviation,
            "magic": MAGIC,
            "comment": f"IND24H {indicator[:12]}"[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(info),
        }
        result = self._send(request)
        return {
            "side": side,
            "symbol": tv_symbol,
            "broker_symbol": broker_symbol,
            "entry_price": float(getattr(result, "price", 0.0) or entry),
            "stop_loss": float(request["sl"]),
            "volume": volume,
            "deal": int(getattr(result, "deal", 0) or 0),
            "order": int(getattr(result, "order", 0) or 0),
        }

    def reverse_on_signal(self, alert: Alert) -> dict[str, Any]:
        broker_symbol = self._broker_symbol(alert.symbol)
        positions = self._managed_positions(broker_symbol)
        same_side = [p for p in positions if self._side(p) == alert.side]
        opposite = [p for p in positions if self._side(p) != alert.side]
        if same_side and not opposite:
            return {"action": "IGNORED_DUPLICATE_DIRECTION", "side": alert.side}
        if len(positions) > 1:
            raise RuntimeError("More than one indicator-only position exists; fail-closed")

        closed: dict[str, Any] | None = None
        if opposite:
            closed = self.close_position(opposite[0], reason="NEXT_SIGNAL_TP")

        opened = self.open_position(alert.symbol, alert.side, indicator=alert.indicator)
        return {
            "action": "REVERSED" if closed else "OPENED",
            "closed": closed,
            "opened": opened,
            "logical_tp_rule": "previous exit = next opposite signal entry event",
        }


class IndicatorOnlyService:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.log_path = self.runtime / "indicator_only_24h.jsonl"
        self.status_path = self.runtime / "indicator_only_24h_status.json"
        self.secret = os.getenv("AAQTS_INDICATOR_WEBHOOK_SECRET", "").strip()
        if len(self.secret) < 16:
            raise RuntimeError("AAQTS_INDICATOR_WEBHOOK_SECRET must be at least 16 characters")
        allowed_raw = os.getenv("AAQTS_INDICATOR_ALLOWED_SYMBOLS", "BTCUSD")
        self.allowed_symbols = {
            _normalize_symbol(item) for item in allowed_raw.split(",") if item.strip()
        }
        if not self.allowed_symbols:
            raise RuntimeError("At least one indicator-only symbol must be configured")
        self.started_at = _utc_now()
        duration_hours = _env_float(
            "AAQTS_INDICATOR_DURATION_HOURS", 24.0, minimum=0.1, maximum=24.0
        )
        self.expires_at = self.started_at + timedelta(hours=duration_hours)
        self.queue: queue.Queue[Alert | None] = queue.Queue(maxsize=1000)
        self.seen: dict[str, float] = {}
        self.seen_lock = threading.RLock()
        self.broker = IndicatorOnlyBroker()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, name="indicator-executor", daemon=True)
        self._write_status(state="STARTING")

    def _append(self, event: dict[str, Any]) -> None:
        record = {"ts": _utc_now().isoformat(), **event}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def _write_status(self, **updates: Any) -> None:
        current: dict[str, Any] = {}
        try:
            current = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        current.update(
            {
                "mode": MODE_NAME,
                "timeframe": "15m",
                "started_utc": self.started_at.isoformat(),
                "expires_utc": self.expires_at.isoformat(),
                "allowed_symbols": sorted(self.allowed_symbols),
                "indicator_settings": {
                    "LuxAlgo - Liquidity Sweeps": {
                        "swings": 5,
                        "options": "Only Wicks",
                        "extend": True,
                        "max_bars": 300,
                    },
                    "AlgoAlpha - Half Trend": {
                        "amplitude": 2,
                        "channel_deviation": 2,
                        "linear_regression_length": 7,
                    },
                },
                "tp_rule": "close current trade on next opposite valid signal; same event opens next trade",
                "heartbeat_utc": _utc_now().isoformat(),
            }
        )
        current.update(updates)
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)

    def _validate_payload(self, payload: dict[str, Any]) -> Alert:
        if not secrets.compare_digest(str(payload.get("secret", "")), self.secret):
            raise ValueError("invalid webhook secret")
        indicator = _normalize_indicator(payload.get("indicator"))
        if indicator not in APPROVED_INDICATORS:
            raise ValueError("indicator is not approved for this 24h mode")
        symbol = _normalize_symbol(payload.get("symbol") or payload.get("ticker"))
        if symbol not in self.allowed_symbols:
            raise ValueError(f"symbol {symbol!r} is not enabled for indicator-only mode")
        timeframe = _normalize_timeframe(payload.get("timeframe") or payload.get("interval"))
        if timeframe != EXPECTED_TIMEFRAME:
            raise ValueError("only 15-minute alerts are accepted")
        side = str(payload.get("side") or payload.get("signal") or "").strip().upper()
        if side not in VALID_SIDES:
            raise ValueError("side/signal must be BUY or SELL")
        bar_time = str(payload.get("bar_time") or payload.get("time") or "").strip()
        explicit_id = str(payload.get("alert_id") or "").strip()
        alert_id = explicit_id or f"{indicator}|{symbol}|{timeframe}|{side}|{bar_time}"
        if not bar_time and not explicit_id:
            # Last-resort small time bucket prevents accidental double POSTs while
            # still allowing a later signal from the other indicator.
            alert_id += f"|{int(time.time() // 5)}"
        return Alert(
            alert_id=alert_id,
            indicator=indicator,
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            received_at=_utc_now(),
            bar_time=bar_time,
            raw=dict(payload),
        )

    def accept(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if _utc_now() >= self.expires_at:
            return HTTPStatus.GONE, {"ok": False, "error": "24-hour mode expired"}
        try:
            alert = self._validate_payload(payload)
        except ValueError as exc:
            self._append({"event": "REJECTED_ALERT", "error": str(exc), "payload": payload})
            return HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}

        with self.seen_lock:
            cutoff = time.time() - 86400
            self.seen = {key: ts for key, ts in self.seen.items() if ts >= cutoff}
            if alert.alert_id in self.seen:
                return HTTPStatus.OK, {"ok": True, "status": "duplicate_ignored", "alert_id": alert.alert_id}
            self.seen[alert.alert_id] = time.time()
        try:
            self.queue.put_nowait(alert)
        except queue.Full:
            self._append({"event": "QUEUE_FULL", "alert_id": alert.alert_id})
            return HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "execution queue full"}
        self._append(
            {
                "event": "ALERT_ACCEPTED",
                "alert_id": alert.alert_id,
                "indicator": alert.indicator,
                "symbol": alert.symbol,
                "side": alert.side,
                "bar_time": alert.bar_time,
            }
        )
        self._write_status(state="RUNNING", last_alert_id=alert.alert_id)
        return HTTPStatus.ACCEPTED, {"ok": True, "status": "queued", "alert_id": alert.alert_id}

    def _worker_loop(self) -> None:
        try:
            self.broker.connect()
        except Exception as exc:
            LOGGER.exception("Indicator-only MT5 connection failed")
            self._append({"event": "BROKER_CONNECT_FAILED", "error": str(exc)})
            self._write_status(state="BROKER_ERROR", error=str(exc))
            return
        self._write_status(state="RUNNING")
        while not self._stop.is_set():
            try:
                alert = self.queue.get(timeout=0.5)
            except queue.Empty:
                self._write_status(state="RUNNING")
                continue
            if alert is None:
                break
            if _utc_now() >= self.expires_at:
                self._append({"event": "EXPIRED_ALERT_DROPPED", "alert_id": alert.alert_id})
                continue
            started = time.perf_counter()
            try:
                result = self.broker.reverse_on_signal(alert)
                latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
                self._append(
                    {
                        "event": "EXECUTED_SIGNAL",
                        "alert_id": alert.alert_id,
                        "indicator": alert.indicator,
                        "symbol": alert.symbol,
                        "side": alert.side,
                        "latency_ms": latency_ms,
                        "result": result,
                    }
                )
                self._write_status(
                    state="RUNNING",
                    last_execution={
                        "alert_id": alert.alert_id,
                        "side": alert.side,
                        "symbol": alert.symbol,
                        "latency_ms": latency_ms,
                        "result": result,
                    },
                )
            except Exception as exc:
                LOGGER.exception("Indicator-only execution failed")
                self._append(
                    {
                        "event": "EXECUTION_BLOCKED",
                        "alert_id": alert.alert_id,
                        "indicator": alert.indicator,
                        "symbol": alert.symbol,
                        "side": alert.side,
                        "error": str(exc),
                    }
                )
                self._write_status(state="RUNNING", last_error=str(exc))
            finally:
                self.queue.task_done()
        try:
            self.broker.shutdown()
        finally:
            self._write_status(state="STOPPED")

    def start_worker(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=5)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "AAQTSIndicatorOnly/1.0"

    @property
    def service(self) -> IndicatorOnlyService:
        return self.server.service  # type: ignore[attr-defined]

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "mode": MODE_NAME,
                    "timeframe": "15m",
                    "expires_utc": self.service.expires_at.isoformat(),
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/webhook/tradingview":
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 32_768:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid payload size"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON object required"})
            return
        status, body = self.service.accept(payload)
        self._json(status, body)

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("webhook %s", format % args)


class ServiceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: IndicatorOnlyService):
        super().__init__(address, WebhookHandler)
        self.service = service


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    service = IndicatorOnlyService()
    service.start_worker()
    host = os.getenv("AAQTS_INDICATOR_WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = _env_int("AAQTS_INDICATOR_WEBHOOK_PORT", 80, minimum=1, maximum=65535)
    server = ServiceHTTPServer((host, port), service)

    def request_stop(*_args: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    expiry_seconds = max(0.0, (service.expires_at - _utc_now()).total_seconds())
    threading.Timer(expiry_seconds, request_stop).start()
    LOGGER.info(
        "%s listening on %s:%s; expires %s; symbols=%s",
        MODE_NAME,
        host,
        port,
        service.expires_at.isoformat(),
        sorted(service.allowed_symbols),
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        service.stop()
        LOGGER.info("%s stopped", MODE_NAME)


if __name__ == "__main__":
    main()
