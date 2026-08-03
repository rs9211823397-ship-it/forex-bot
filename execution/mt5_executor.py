"""Safe MetaTrader 5 execution engine for AAQTS.

The module keeps MT5-specific behaviour behind a small class so it can be
unit-tested with a fake adapter. Every new market order requires a valid stop
loss and take profit. Existing broker-side positions are rediscovered after a
restart by magic number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional


AAQTS_MAGIC = 20260730


class ExecutionError(RuntimeError):
    """Raised when a trade request cannot be validated or executed."""


@dataclass(frozen=True)
class ExecutionConfig:
    terminal_path: Optional[str] = None
    magic: int = AAQTS_MAGIC
    deviation: int = 20
    max_open_positions: int = 3
    allow_duplicate_direction: bool = False
    require_stop_loss: bool = True
    require_take_profit: bool = True


@dataclass(frozen=True)
class TradeResult:
    success: bool
    retcode: Optional[int]
    comment: str
    order: Optional[int] = None
    deal: Optional[int] = None
    position: Optional[int] = None


class MT5Executor:
    """Validated MT5 market execution and broker-side position management."""

    def __init__(self, config: Optional[ExecutionConfig] = None, adapter: Any = None):
        self.config = config or ExecutionConfig()
        if adapter is None:
            try:
                import MetaTrader5 as adapter  # type: ignore
            except ImportError as exc:
                raise ExecutionError(
                    "MetaTrader5 package is not installed. Install it on the Windows MT5 host."
                ) from exc
        self.mt5 = adapter
        self.connected = False
        self.accept_new_trades = True

    def connect(self) -> bool:
        kwargs = {}
        if self.config.terminal_path:
            kwargs["path"] = self.config.terminal_path
        self.connected = bool(self.mt5.initialize(**kwargs))
        if not self.connected:
            raise ExecutionError(f"MT5 initialization failed: {self.mt5.last_error()}")

        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if terminal is None or account is None:
            self.shutdown()
            raise ExecutionError("MT5 terminal/account information is unavailable")
        if not terminal.trade_allowed:
            self.shutdown()
            raise ExecutionError("Algorithmic trading is disabled in the MT5 terminal")
        if not account.trade_allowed or not account.trade_expert:
            self.shutdown()
            raise ExecutionError("Trading or expert trading is disabled on the account")
        return True

    def shutdown(self) -> None:
        if self.connected:
            self.mt5.shutdown()
        self.connected = False

    def pause(self) -> None:
        """Reject new entries while leaving existing positions protected."""
        self.accept_new_trades = False

    def resume(self) -> None:
        self.accept_new_trades = True

    def positions(self, symbol: Optional[str] = None, managed_only: bool = True) -> list[Any]:
        raw = self.mt5.positions_get(symbol=symbol) if symbol else self.mt5.positions_get()
        positions = list(raw or [])
        if managed_only:
            positions = [p for p in positions if getattr(p, "magic", None) == self.config.magic]
        return positions

    def recover_positions(self) -> list[Any]:
        """Return all AAQTS positions still held by the broker after restart."""
        self._ensure_connected()
        return self.positions(managed_only=True)

    def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: float,
        take_profit: float,
        comment: str = "AAQTS",
    ) -> TradeResult:
        self._ensure_connected()
        if not self.accept_new_trades:
            raise ExecutionError("New entries are paused")

        side = side.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ExecutionError("side must be BUY or SELL")
        if volume <= 0:
            raise ExecutionError("volume must be greater than zero")
        if self.config.require_stop_loss and stop_loss <= 0:
            raise ExecutionError("A valid stop loss is mandatory")
        if self.config.require_take_profit and take_profit <= 0:
            raise ExecutionError("A valid take profit is mandatory")

        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise ExecutionError(f"Unknown MT5 symbol: {symbol}")
        if not getattr(info, "visible", False) and not self.mt5.symbol_select(symbol, True):
            raise ExecutionError(f"Could not select symbol: {symbol}")
        if getattr(info, "trade_mode", 0) == 0:
            raise ExecutionError(f"Trading is disabled for {symbol}")

        volume = self._normalize_volume(volume, info)
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ExecutionError(f"No current tick is available for {symbol}")

        is_buy = side == "BUY"
        price = tick.ask if is_buy else tick.bid
        self._validate_protection(side, price, stop_loss, take_profit, info)
        self._validate_position_limits(symbol, side)

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY if is_buy else self.mt5.ORDER_TYPE_SELL,
            "price": self._round_price(price, info),
            "sl": self._round_price(stop_loss, info),
            "tp": self._round_price(take_profit, info),
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }

        check = self.mt5.order_check(request)
        if check is None or getattr(check, "retcode", None) != 0:
            detail = getattr(check, "comment", self.mt5.last_error())
            raise ExecutionError(f"MT5 order_check rejected the request: {detail}")

        result = self.mt5.order_send(request)
        success_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        success = result is not None and getattr(result, "retcode", None) == success_code
        trade_result = self._to_result(result, success)
        if not success:
            raise ExecutionError(
                f"MT5 order_send failed: {trade_result.retcode} {trade_result.comment}"
            )
        return trade_result

    def modify_protection(self, position_ticket: int, stop_loss: float, take_profit: float) -> TradeResult:
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        side = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
        info = self.mt5.symbol_info(position.symbol)
        tick = self.mt5.symbol_info_tick(position.symbol)
        if info is None or tick is None:
            raise ExecutionError("Symbol information is unavailable")
        price = tick.bid if side == "BUY" else tick.ask
        self._validate_protection(side, price, stop_loss, take_profit, info)

        request = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "position": position.ticket,
            "symbol": position.symbol,
            "sl": self._round_price(stop_loss, info),
            "tp": self._round_price(take_profit, info),
            "magic": self.config.magic,
        }
        result = self.mt5.order_send(request)
        success_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        success = result is not None and getattr(result, "retcode", None) == success_code
        trade_result = self._to_result(result, success, position.ticket)
        if not success:
            raise ExecutionError(f"Protection update failed: {trade_result.comment}")
        return trade_result

    def close_position(self, position_ticket: int, comment: str = "AAQTS close") -> TradeResult:
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        tick = self.mt5.symbol_info_tick(position.symbol)
        info = self.mt5.symbol_info(position.symbol)
        if tick is None or info is None:
            raise ExecutionError("Symbol information is unavailable")

        closing_buy = position.type != self.mt5.POSITION_TYPE_BUY
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": self.mt5.ORDER_TYPE_BUY if closing_buy else self.mt5.ORDER_TYPE_SELL,
            "position": position.ticket,
            "price": tick.ask if closing_buy else tick.bid,
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }
        result = self.mt5.order_send(request)
        success_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        success = result is not None and getattr(result, "retcode", None) == success_code
        trade_result = self._to_result(result, success, position.ticket)
        if not success:
            raise ExecutionError(f"Close failed: {trade_result.comment}")
        return trade_result

    def close_all(self) -> list[TradeResult]:
        results = []
        for position in list(self.positions(managed_only=True)):
            results.append(self.close_position(position.ticket, "AAQTS emergency close"))
        return results

    def emergency_stop(self) -> list[TradeResult]:
        """Pause entries and close every position owned by this AAQTS magic number."""
        self.pause()
        return self.close_all()

    def _position_by_ticket(self, ticket: int) -> Any:
        matches = [p for p in self.positions(managed_only=True) if p.ticket == ticket]
        if not matches:
            raise ExecutionError(f"Managed position {ticket} was not found")
        return matches[0]

    def _validate_position_limits(self, symbol: str, side: str) -> None:
        positions = self.positions(managed_only=True)
        if len(positions) >= self.config.max_open_positions:
            raise ExecutionError("Maximum AAQTS open-position limit reached")
        if self.config.allow_duplicate_direction:
            return
        wanted_type = self.mt5.POSITION_TYPE_BUY if side == "BUY" else self.mt5.POSITION_TYPE_SELL
        if any(p.symbol == symbol and p.type == wanted_type for p in positions):
            raise ExecutionError(f"Duplicate {symbol} {side} position rejected")

    def _validate_protection(self, side: str, entry: float, sl: float, tp: float, info: Any) -> None:
        if side == "BUY" and not (sl < entry < tp):
            raise ExecutionError("BUY protection must satisfy SL < entry < TP")
        if side == "SELL" and not (tp < entry < sl):
            raise ExecutionError("SELL protection must satisfy TP < entry < SL")
        minimum = max(getattr(info, "trade_stops_level", 0), 0) * info.point
        if minimum and (abs(entry - sl) < minimum or abs(tp - entry) < minimum):
            raise ExecutionError("SL/TP violates the broker minimum stop distance")

    @staticmethod
    def _normalize_volume(volume: float, info: Any) -> float:
        minimum = float(info.volume_min)
        maximum = float(info.volume_max)
        step = float(info.volume_step)
        if volume < minimum or volume > maximum:
            raise ExecutionError(f"Volume must be between {minimum} and {maximum}")
        steps = round((volume - minimum) / step)
        normalized = minimum + steps * step
        return round(normalized, 8)

    def _filling_mode(self, info: Any) -> int:
        # The connected MetaQuotes demo symbol reports filling_mode=1 and accepts FOK.
        # Prefer FOK when advertised, then IOC, then RETURN for exchange-style symbols.
        advertised = int(getattr(info, "filling_mode", 0))
        if advertised & 1:
            return self.mt5.ORDER_FILLING_FOK
        if advertised & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    @staticmethod
    def _round_price(price: float, info: Any) -> float:
        return round(float(price), int(info.digits))

    def _ensure_connected(self) -> None:
        if not self.connected:
            raise ExecutionError("MT5Executor is not connected")

    @staticmethod
    def _to_result(result: Any, success: bool, position: Optional[int] = None) -> TradeResult:
        if result is None:
            return TradeResult(False, None, "No response from MT5", position=position)
        return TradeResult(
            success=success,
            retcode=getattr(result, "retcode", None),
            comment=str(getattr(result, "comment", "")),
            order=getattr(result, "order", None),
            deal=getattr(result, "deal", None),
            position=position or getattr(result, "order", None),
        )
