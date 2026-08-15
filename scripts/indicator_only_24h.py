"""Temporary 24-hour UT Bot + EMA200 execution mode.

Strategy (hard-locked to 15-minute closed candles):
- UT Bot sensitivity/key value: 3
- ATR period: 10
- EMA trend filter: 200
- BUY entry only when a fresh UT Bot BUY signal occurs and close > EMA200.
- SELL entry only when a fresh UT Bot SELL signal occurs and close < EMA200.
- A fresh opposite UT Bot signal ALWAYS closes the current managed position.
- After that close, the opposite position is opened only if its EMA200 filter passes.
- No fixed broker TP is used. The next opposite UT Bot signal is the normal exit.

The mode reads MT5 candles directly; no TradingView webhook is required. A broker-side
catastrophe stop remains as an emergency execution protection and is not part of the
normal strategy exit logic.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

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


LOGGER = logging.getLogger("aaqts.utbot_ema_24h")
MAGIC = 20260815
MODE_NAME = "UTBOT_EMA200_24H"
TIMEFRAME = "15m"
UT_KEY_VALUE = 3.0
UT_ATR_PERIOD = 10
EMA_PERIOD = 200
MIN_BARS = 260


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


def _normalize_symbol(value: object) -> str:
    text = str(value or "").strip().upper().replace("/", "")
    for prefix in ("BITSTAMP:", "BINANCE:", "COINBASE:", "OANDA:", "FOREXCOM:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0 or not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def _true_ranges(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("OHLC arrays must have equal length")
    if not closes:
        return []
    out: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            out.append(float(highs[i]) - float(lows[i]))
            continue
        prev_close = float(closes[i - 1])
        out.append(
            max(
                float(highs[i]) - float(lows[i]),
                abs(float(highs[i]) - prev_close),
                abs(float(lows[i]) - prev_close),
            )
        )
    return out


def _rma(values: Sequence[float], period: int) -> list[float]:
    """TradingView-style Wilder RMA seeded with an SMA once enough values exist."""
    if period <= 0 or not values:
        return []
    result = [float("nan")] * len(values)
    if len(values) < period:
        return result
    seed = sum(float(v) for v in values[:period]) / period
    result[period - 1] = seed
    alpha = 1.0 / period
    for i in range(period, len(values)):
        result[i] = alpha * float(values[i]) + (1.0 - alpha) * result[i - 1]
    return result


@dataclass(frozen=True)
class StrategySnapshot:
    bar_time: int
    close: float
    ema200: float
    atr: float
    trailing_stop: float
    signal: str | None
    entry_allowed: bool


def calculate_utbot_ema_snapshot(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    times: Sequence[int],
    *,
    key_value: float = UT_KEY_VALUE,
    atr_period: int = UT_ATR_PERIOD,
    ema_period: int = EMA_PERIOD,
) -> StrategySnapshot:
    """Calculate the latest closed-bar UT Bot signal and EMA200 filter state."""
    if not (len(highs) == len(lows) == len(closes) == len(times)):
        raise ValueError("OHLC/time arrays must have equal length")
    if len(closes) < max(atr_period + 3, ema_period + 3):
        raise ValueError("not enough closed candles")

    closes_f = [float(v) for v in closes]
    atrs = _rma(_true_ranges(highs, lows, closes_f), atr_period)
    ema_values = _ema(closes_f, ema_period)
    stops = [float("nan")] * len(closes_f)

    first = atr_period - 1
    if not isfinite(atrs[first]):
        raise ValueError("ATR seed unavailable")
    stops[first] = closes_f[first] - key_value * atrs[first]

    for i in range(first + 1, len(closes_f)):
        atr = atrs[i]
        if not isfinite(atr):
            continue
        nloss = key_value * atr
        prev_stop = stops[i - 1]
        if not isfinite(prev_stop):
            prev_stop = closes_f[i - 1] - nloss
        src = closes_f[i]
        prev_src = closes_f[i - 1]
        if src > prev_stop and prev_src > prev_stop:
            stops[i] = max(prev_stop, src - nloss)
        elif src < prev_stop and prev_src < prev_stop:
            stops[i] = min(prev_stop, src + nloss)
        elif src > prev_stop:
            stops[i] = src - nloss
        else:
            stops[i] = src + nloss

    i = len(closes_f) - 1
    prev = i - 1
    signal: str | None = None
    if closes_f[i] > stops[i] and closes_f[prev] <= stops[prev]:
        signal = "BUY"
    elif closes_f[i] < stops[i] and closes_f[prev] >= stops[prev]:
        signal = "SELL"

    ema200 = float(ema_values[i])
    close = closes_f[i]
    entry_allowed = bool(
        (signal == "BUY" and close > ema200)
        or (signal == "SELL" and close < ema200)
    )
    return StrategySnapshot(
        bar_time=int(times[i]),
        close=close,
        ema200=ema200,
        atr=float(atrs[i]),
        trailing_stop=float(stops[i]),
        signal=signal,
        entry_allowed=entry_allowed,
    )


class IndicatorOnlyBroker:
    """Minimal demo-only execution adapter for the temporary strategy test."""

    def __init__(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - Windows deployment only
            raise RuntimeError("MetaTrader5 package is required on the VPS") from exc
        self.mt5 = mt5
        self.fixed_lot = _env_float(
            "AAQTS_INDICATOR_FIXED_LOT", float(MT5_FIXED_LOT), minimum=0.01, maximum=100.0
        )
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
            kwargs.update(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
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
            raise RuntimeError("24h strategy mode is locked to MT5 DEMO")
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

    def _broker_symbol(self, symbol: str) -> str:
        canonical = _normalize_symbol(symbol)
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

    def closed_m15_rates(self, symbol: str, count: int = 350) -> list[Any]:
        broker_symbol = self._broker_symbol(symbol)
        self._info_tick(broker_symbol)
        rates = self.mt5.copy_rates_from_pos(broker_symbol, self.mt5.TIMEFRAME_M15, 1, count)
        if rates is None or len(rates) < MIN_BARS:
            raise RuntimeError(f"Need at least {MIN_BARS} closed M15 bars for {broker_symbol}")
        return list(rates)

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
            "comment": f"UTEMA EXIT {reason}"[:31],
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

    def open_position(self, symbol: str, side: str) -> dict[str, Any]:
        broker_symbol = self._broker_symbol(symbol)
        info, tick = self._info_tick(broker_symbol)
        existing = self._managed_positions(broker_symbol)
        if existing:
            raise RuntimeError("24h strategy position still open; refusing duplicate entry")
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
            "tp": 0.0,
            "deviation": self.deviation,
            "magic": MAGIC,
            "comment": "UTBOT3-10 EMA200"[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(info),
        }
        result = self._send(request)
        return {
            "side": side,
            "symbol": symbol,
            "broker_symbol": broker_symbol,
            "entry_price": float(getattr(result, "price", 0.0) or entry),
            "emergency_stop": float(request["sl"]),
            "volume": volume,
            "deal": int(getattr(result, "deal", 0) or 0),
            "order": int(getattr(result, "order", 0) or 0),
        }

    def act_on_signal(self, symbol: str, snapshot: StrategySnapshot) -> dict[str, Any]:
        if snapshot.signal not in {"BUY", "SELL"}:
            return {"action": "NO_SIGNAL"}
        broker_symbol = self._broker_symbol(symbol)
        positions = self._managed_positions(broker_symbol)
        if len(positions) > 1:
            raise RuntimeError("More than one 24h strategy position exists; fail-closed")

        current = positions[0] if positions else None
        if current is not None and self._side(current) == snapshot.signal:
            return {"action": "IGNORED_SAME_DIRECTION", "side": snapshot.signal}

        closed: dict[str, Any] | None = None
        if current is not None:
            closed = self.close_position(current, reason="NEXT_UT_SIGNAL")

        if not snapshot.entry_allowed:
            return {
                "action": "CLOSED_THEN_EMA_BLOCKED" if closed else "EMA_BLOCKED_ENTRY",
                "closed": closed,
                "signal": snapshot.signal,
                "close": snapshot.close,
                "ema200": snapshot.ema200,
            }

        opened = self.open_position(symbol, snapshot.signal)
        return {
            "action": "REVERSED" if closed else "OPENED",
            "closed": closed,
            "opened": opened,
            "normal_exit_rule": "next opposite UT Bot signal",
        }


class StrategyService:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.log_path = self.runtime / "indicator_only_24h.jsonl"
        self.status_path = self.runtime / "indicator_only_24h_status.json"
        allowed_raw = os.getenv("AAQTS_INDICATOR_ALLOWED_SYMBOLS", "BTCUSD")
        self.allowed_symbols = [_normalize_symbol(x) for x in allowed_raw.split(",") if x.strip()]
        if not self.allowed_symbols:
            raise RuntimeError("At least one 24h strategy symbol must be configured")
        self.poll_seconds = _env_float(
            "AAQTS_INDICATOR_POLL_SECONDS", 5.0, minimum=1.0, maximum=60.0
        )
        self.started_at = _utc_now()
        duration_hours = _env_float(
            "AAQTS_INDICATOR_DURATION_HOURS", 24.0, minimum=0.1, maximum=24.0
        )
        self.expires_at = self.started_at + timedelta(hours=duration_hours)
        self.broker = IndicatorOnlyBroker()
        self._stop = threading.Event()
        self.last_bar: dict[str, int] = {}
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
                "timeframe": TIMEFRAME,
                "started_utc": self.started_at.isoformat(),
                "expires_utc": self.expires_at.isoformat(),
                "allowed_symbols": self.allowed_symbols,
                "strategy": {
                    "ut_bot_key_value": UT_KEY_VALUE,
                    "ut_bot_atr_period": UT_ATR_PERIOD,
                    "ema_period": EMA_PERIOD,
                    "buy_entry": "fresh UT BUY and closed candle > EMA200",
                    "sell_entry": "fresh UT SELL and closed candle < EMA200",
                    "normal_exit": "next opposite UT Bot signal regardless of EMA",
                    "reverse_entry": "only if opposite signal also passes EMA200 filter",
                    "fixed_tp": False,
                    "emergency_broker_stop": True,
                },
                "heartbeat_utc": _utc_now().isoformat(),
            }
        )
        current.update(updates)
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.status_path)

    @staticmethod
    def _snapshot(rates: Sequence[Any]) -> StrategySnapshot:
        highs = [float(row["high"]) for row in rates]
        lows = [float(row["low"]) for row in rates]
        closes = [float(row["close"]) for row in rates]
        times = [int(row["time"]) for row in rates]
        return calculate_utbot_ema_snapshot(highs, lows, closes, times)

    def _process_symbol(self, symbol: str) -> None:
        rates = self.broker.closed_m15_rates(symbol)
        snapshot = self._snapshot(rates)
        if self.last_bar.get(symbol) == snapshot.bar_time:
            return
        self.last_bar[symbol] = snapshot.bar_time
        bar_iso = datetime.fromtimestamp(snapshot.bar_time, timezone.utc).isoformat()
        event = {
            "event": "CLOSED_BAR",
            "symbol": symbol,
            "bar_time": bar_iso,
            "close": snapshot.close,
            "ema200": snapshot.ema200,
            "atr10": snapshot.atr,
            "ut_trailing_stop": snapshot.trailing_stop,
            "signal": snapshot.signal,
            "entry_allowed": snapshot.entry_allowed,
        }
        self._append(event)
        self._write_status(state="RUNNING", last_bar=event)
        if snapshot.signal is None:
            return
        started = time.perf_counter()
        result = self.broker.act_on_signal(symbol, snapshot)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        execution = {
            "event": "EXECUTED_SIGNAL",
            "symbol": symbol,
            "bar_time": bar_iso,
            "signal": snapshot.signal,
            "close": snapshot.close,
            "ema200": snapshot.ema200,
            "entry_allowed": snapshot.entry_allowed,
            "latency_ms": latency_ms,
            "result": result,
        }
        self._append(execution)
        self._write_status(state="RUNNING", last_execution=execution)

    def stop(self, *_args: object) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            self.broker.connect()
        except Exception as exc:
            LOGGER.exception("UT Bot + EMA200 MT5 connection failed")
            self._append({"event": "BROKER_CONNECT_FAILED", "error": str(exc)})
            self._write_status(state="BROKER_ERROR", error=str(exc))
            raise

        self._write_status(state="RUNNING")
        LOGGER.info(
            "%s started; symbols=%s; expires=%s",
            MODE_NAME,
            self.allowed_symbols,
            self.expires_at.isoformat(),
        )
        try:
            while not self._stop.is_set() and _utc_now() < self.expires_at:
                for symbol in self.allowed_symbols:
                    if self._stop.is_set():
                        break
                    try:
                        self._process_symbol(symbol)
                    except Exception as exc:
                        LOGGER.exception("24h strategy processing failed for %s", symbol)
                        self._append({"event": "PROCESSING_ERROR", "symbol": symbol, "error": str(exc)})
                        self._write_status(state="RUNNING", last_error=str(exc))
                self._write_status(state="RUNNING")
                self._stop.wait(self.poll_seconds)
        finally:
            self.broker.shutdown()
            final_state = "EXPIRED" if _utc_now() >= self.expires_at else "STOPPED"
            self._write_status(state=final_state)
            LOGGER.info("%s %s", MODE_NAME, final_state.lower())


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    service = StrategyService()
    signal.signal(signal.SIGINT, service.stop)
    signal.signal(signal.SIGTERM, service.stop)
    service.run()


if __name__ == "__main__":
    main()
