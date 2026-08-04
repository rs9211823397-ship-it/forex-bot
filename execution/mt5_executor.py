"""Safe MetaTrader 5 execution engine for AAQTS.

The module keeps MT5-specific behaviour behind a small class so it can be
unit-tested with a fake adapter. Every new market order requires a valid stop
loss and take profit. Existing broker-side positions are rediscovered after a
restart by magic number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import floor, isfinite
from typing import Any, Optional


AAQTS_MAGIC = 20260730


class ExecutionError(RuntimeError):
    """Raised when a trade request cannot be validated or executed."""


@dataclass(frozen=True)
class ExecutionConfig:
    terminal_path: Optional[str] = None
    login: Optional[int] = None
    expected_login: Optional[int] = None
    password: str = field(default="", repr=False)
    server: str = ""
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


@dataclass(frozen=True)
class AccountSnapshot:
    """Small, stable subset of broker account state used by risk controls."""

    balance: float
    equity: float

    def __post_init__(self) -> None:
        for field_name in ("balance", "equity"):
            value = float(getattr(self, field_name))
            if not isfinite(value) or value <= 0:
                raise ExecutionError(
                    f"MT5 account {field_name} must be finite and positive"
                )
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True)
class ClosedPositionResult:
    """One realized MT5 exit deal owned by this bot's magic number."""

    closed_at: datetime
    profit_loss: float

    def __post_init__(self) -> None:
        instant = self.closed_at
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ExecutionError("MT5 closed_at must be timezone-aware")
        value = float(self.profit_loss)
        if not isfinite(value):
            raise ExecutionError("MT5 realized profit/loss must be finite")
        object.__setattr__(self, "closed_at", instant.astimezone(timezone.utc))
        object.__setattr__(self, "profit_loss", value)


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
        if self.config.login is not None:
            if not self.config.password or not self.config.server:
                raise ExecutionError("MT5 login requires both password and server")
            kwargs.update(
                {
                    "login": int(self.config.login),
                    "password": self.config.password,
                    "server": self.config.server,
                }
            )
        self.connected = bool(self.mt5.initialize(**kwargs))
        if not self.connected:
            raise ExecutionError(f"MT5 initialization failed: {self.mt5.last_error()}")

        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if terminal is None or account is None:
            self.shutdown()
            raise ExecutionError("MT5 terminal/account information is unavailable")
        expected_login = (
            self.config.expected_login
            if self.config.expected_login is not None
            else self.config.login
        )
        if expected_login is not None and int(
            getattr(account, "login", -1)
        ) != int(expected_login):
            self.shutdown()
            raise ExecutionError("MT5 connected to an unexpected account login")
        demo_mode = getattr(self.mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        if getattr(account, "trade_mode", None) != demo_mode:
            self.shutdown()
            raise ExecutionError(
                "MT5_DEMO requires a broker demo account; live/contest accounts are blocked"
            )
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

    def positions(
        self, symbol: Optional[str] = None, managed_only: bool = True
    ) -> list[Any]:
        raw = (
            self.mt5.positions_get(symbol=symbol)
            if symbol
            else self.mt5.positions_get()
        )
        positions = list(raw or [])
        if managed_only:
            positions = [
                p for p in positions if getattr(p, "magic", None) == self.config.magic
            ]
        return positions

    def recover_positions(self) -> list[Any]:
        """Return all AAQTS positions still held by the broker after restart."""
        self._ensure_connected()
        return self.positions(managed_only=True)

    def account_snapshot(self) -> AccountSnapshot:
        """Return current broker balance/equity for live risk decisions."""
        self._ensure_connected()
        account = self.mt5.account_info()
        if account is None:
            raise ExecutionError("MT5 account information is unavailable")
        return AccountSnapshot(
            balance=getattr(account, "balance", 0.0),
            equity=getattr(account, "equity", 0.0),
        )

    def closed_position_results(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[ClosedPositionResult]:
        """Return realized exit deals in a UTC interval for loss controls."""
        self._ensure_connected()
        start = self._as_utc(start_time, "start_time")
        end = self._as_utc(end_time, "end_time")
        if end < start:
            raise ExecutionError("MT5 history end_time cannot precede start_time")

        deals = self.mt5.history_deals_get(start, end)
        if deals is None:
            raise ExecutionError(
                f"MT5 deal history is unavailable: {self.mt5.last_error()}"
            )
        exit_entries = {
            getattr(self.mt5, "DEAL_ENTRY_OUT", 1),
            getattr(self.mt5, "DEAL_ENTRY_OUT_BY", 3),
        }
        results: list[ClosedPositionResult] = []
        for deal in deals:
            if getattr(deal, "magic", None) != self.config.magic:
                continue
            if getattr(deal, "entry", None) not in exit_entries:
                continue
            timestamp = float(getattr(deal, "time", 0.0))
            if timestamp <= 0:
                raise ExecutionError("MT5 exit deal has an invalid close time")
            profit_loss = sum(
                float(getattr(deal, field_name, 0.0) or 0.0)
                for field_name in ("profit", "swap", "commission", "fee")
            )
            results.append(
                ClosedPositionResult(
                    closed_at=datetime.fromtimestamp(timestamp, timezone.utc),
                    profit_loss=profit_loss,
                )
            )
        return sorted(results, key=lambda item: item.closed_at)

    def position_side(self, position: Any) -> str:
        """Translate a broker position type into AAQTS BUY/SELL vocabulary."""
        position_type = getattr(position, "type", None)
        if position_type == self.mt5.POSITION_TYPE_BUY:
            return "BUY"
        if position_type == self.mt5.POSITION_TYPE_SELL:
            return "SELL"
        raise ExecutionError("MT5 position has an unsupported direction")

    def remaining_loss_at_stop(self, position: Any) -> float:
        """Estimate additional broker P/L loss from current price to its stop."""
        self._ensure_connected()
        side = self.position_side(position)
        stop_loss = float(getattr(position, "sl", 0.0) or 0.0)
        if stop_loss <= 0:
            raise ExecutionError(
                f"Managed position {getattr(position, 'ticket', '?')} has no stop loss"
            )
        current_price = float(
            getattr(position, "price_current", 0.0)
            or getattr(position, "price_open", 0.0)
        )
        volume = float(getattr(position, "volume", 0.0))
        order_type = (
            self.mt5.ORDER_TYPE_BUY if side == "BUY" else self.mt5.ORDER_TYPE_SELL
        )
        projected = self.mt5.order_calc_profit(
            order_type,
            position.symbol,
            volume,
            current_price,
            stop_loss,
        )
        if projected is None or not isfinite(float(projected)):
            raise ExecutionError(
                f"MT5 could not calculate stop risk: {self.mt5.last_error()}"
            )
        return max(0.0, -float(projected))

    def symbol_info(self, symbol: str) -> Any:
        """Return validated broker metadata for one visible MT5 symbol."""
        self._ensure_connected()
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise ExecutionError(f"Unknown MT5 symbol: {symbol}")
        if not getattr(info, "visible", False):
            if not self.mt5.symbol_select(symbol, True):
                raise ExecutionError(f"Could not select symbol: {symbol}")
            info = self.mt5.symbol_info(symbol)
            if info is None:
                raise ExecutionError(
                    f"Symbol information is unavailable after selecting {symbol}"
                )
        return info

    def symbol_tick(self, symbol: str) -> Any:
        """Return the current executable quote for one validated symbol."""
        self.symbol_info(symbol)
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ExecutionError(f"No current tick is available for {symbol}")
        return tick

    def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: Optional[float],
        stop_loss: float,
        take_profit: float,
        comment: str = "AAQTS",
        *,
        reference_entry: Optional[float] = None,
        risk_amount: Optional[float] = None,
    ) -> TradeResult:
        self._ensure_connected()
        if not self.accept_new_trades:
            raise ExecutionError("New entries are paused")

        side = side.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ExecutionError("side must be BUY or SELL")
        if risk_amount is None and (volume is None or volume <= 0):
            raise ExecutionError("volume must be greater than zero")
        if risk_amount is not None and (
            not isfinite(float(risk_amount)) or float(risk_amount) <= 0
        ):
            raise ExecutionError("risk_amount must be finite and greater than zero")
        if self.config.require_stop_loss and stop_loss <= 0:
            raise ExecutionError("A valid stop loss is mandatory")
        if self.config.require_take_profit and take_profit <= 0:
            raise ExecutionError("A valid take profit is mandatory")

        info = self.symbol_info(symbol)
        if getattr(info, "trade_mode", 0) == 0:
            raise ExecutionError(f"Trading is disabled for {symbol}")

        tick = self.symbol_tick(symbol)

        is_buy = side == "BUY"
        price = tick.ask if is_buy else tick.bid
        if reference_entry is not None:
            stop_loss, take_profit = self._translate_protection(
                side=side,
                broker_entry=price,
                reference_entry=float(reference_entry),
                reference_stop=float(stop_loss),
                reference_target=float(take_profit),
            )
        self._validate_protection(side, price, stop_loss, take_profit, info)
        if risk_amount is not None:
            volume = self._volume_for_risk(
                symbol=symbol,
                side=side,
                entry=price,
                stop_loss=stop_loss,
                risk_amount=float(risk_amount),
                info=info,
            )
        assert volume is not None
        volume = self._normalize_volume(volume, info)
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
        success = (
            result is not None and getattr(result, "retcode", None) == success_code
        )
        trade_result = self._to_result(result, success)
        if not success:
            raise ExecutionError(
                f"MT5 order_send failed: {trade_result.retcode} {trade_result.comment}"
            )
        return trade_result

    def modify_protection(
        self, position_ticket: int, stop_loss: float, take_profit: float
    ) -> TradeResult:
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        side = "BUY" if position.type == self.mt5.POSITION_TYPE_BUY else "SELL"
        info = self.symbol_info(position.symbol)
        tick = self.symbol_tick(position.symbol)
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
        check = self.mt5.order_check(request)
        if check is None or getattr(check, "retcode", None) != 0:
            detail = getattr(check, "comment", self.mt5.last_error())
            raise ExecutionError(
                f"MT5 protection order_check rejected the request: {detail}"
            )
        result = self.mt5.order_send(request)
        success_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        success = (
            result is not None and getattr(result, "retcode", None) == success_code
        )
        trade_result = self._to_result(result, success, position.ticket)
        if not success:
            raise ExecutionError(f"Protection update failed: {trade_result.comment}")
        return trade_result

    def move_to_break_even(
        self,
        position_ticket: int,
        offset_points: float = 0.0,
    ) -> TradeResult:
        """Move a profitable managed position's stop to entry plus an offset."""
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        info = self.symbol_info(position.symbol)
        entry = float(position.price_open)
        offset = max(0.0, float(offset_points)) * float(info.point)
        stop_loss = (
            entry + offset
            if position.type == self.mt5.POSITION_TYPE_BUY
            else entry - offset
        )
        take_profit = float(getattr(position, "tp", 0.0) or 0.0)
        if take_profit <= 0:
            raise ExecutionError(
                "Cannot move to break-even without an existing take profit"
            )
        return self.modify_protection(
            position_ticket,
            self._round_price(stop_loss, info),
            take_profit,
        )

    def update_trailing_stop(
        self,
        position_ticket: int,
        stop_loss: float,
    ) -> TradeResult:
        """Advance one managed stop while preserving the broker-side target."""
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        take_profit = float(getattr(position, "tp", 0.0) or 0.0)
        if take_profit <= 0:
            raise ExecutionError(
                "Cannot trail a position without an existing take profit"
            )
        return self.modify_protection(
            position_ticket,
            float(stop_loss),
            take_profit,
        )

    def partial_close(
        self,
        position_ticket: int,
        volume: float,
        comment: str = "AAQTS partial",
    ) -> TradeResult:
        """Close a broker-valid fraction of one managed position."""
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        info = self.symbol_info(position.symbol)
        requested = self._normalize_volume(float(volume), info)
        current_volume = float(position.volume)
        if requested >= current_volume:
            raise ExecutionError(
                "Partial-close volume must be smaller than the open volume"
            )

        remaining = round(current_volume - requested, 8)
        if remaining + 1e-12 < float(info.volume_min):
            raise ExecutionError(
                "Partial close would leave a position below broker minimum volume"
            )
        return self._close_volume(position, requested, comment)

    def close_position(
        self, position_ticket: int, comment: str = "AAQTS close"
    ) -> TradeResult:
        self._ensure_connected()
        position = self._position_by_ticket(position_ticket)
        return self._close_volume(position, float(position.volume), comment)

    def _close_volume(
        self,
        position: Any,
        volume: float,
        comment: str,
    ) -> TradeResult:
        tick = self.symbol_tick(position.symbol)
        info = self.symbol_info(position.symbol)

        closing_buy = position.type != self.mt5.POSITION_TYPE_BUY
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": self._normalize_volume(volume, info),
            "type": self.mt5.ORDER_TYPE_BUY
            if closing_buy
            else self.mt5.ORDER_TYPE_SELL,
            "position": position.ticket,
            "price": tick.ask if closing_buy else tick.bid,
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": comment[:31],
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }
        check = self.mt5.order_check(request)
        if check is None or getattr(check, "retcode", None) != 0:
            detail = getattr(check, "comment", self.mt5.last_error())
            raise ExecutionError(
                f"MT5 close order_check rejected the request: {detail}"
            )
        result = self.mt5.order_send(request)
        success_code = getattr(self.mt5, "TRADE_RETCODE_DONE", 10009)
        success = (
            result is not None and getattr(result, "retcode", None) == success_code
        )
        trade_result = self._to_result(result, success, position.ticket)
        if not success:
            raise ExecutionError(f"Close failed: {trade_result.comment}")
        return trade_result

    def close_all(self) -> list[TradeResult]:
        results = []
        for position in list(self.positions(managed_only=True)):
            results.append(
                self.close_position(position.ticket, "AAQTS emergency close")
            )
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
        wanted_type = (
            self.mt5.POSITION_TYPE_BUY if side == "BUY" else self.mt5.POSITION_TYPE_SELL
        )
        if any(p.symbol == symbol and p.type == wanted_type for p in positions):
            raise ExecutionError(f"Duplicate {symbol} {side} position rejected")

    def _validate_protection(
        self, side: str, entry: float, sl: float, tp: float, info: Any
    ) -> None:
        if side == "BUY" and not (sl < entry < tp):
            raise ExecutionError("BUY protection must satisfy SL < entry < TP")
        if side == "SELL" and not (tp < entry < sl):
            raise ExecutionError("SELL protection must satisfy TP < entry < SL")
        minimum = max(getattr(info, "trade_stops_level", 0), 0) * info.point
        if minimum and (abs(entry - sl) < minimum or abs(tp - entry) < minimum):
            raise ExecutionError("SL/TP violates the broker minimum stop distance")

    @staticmethod
    def _translate_protection(
        *,
        side: str,
        broker_entry: float,
        reference_entry: float,
        reference_stop: float,
        reference_target: float,
    ) -> tuple[float, float]:
        """Apply source-market stop/target distances to the broker quote."""
        if not all(
            isfinite(value) and value > 0
            for value in (
                broker_entry,
                reference_entry,
                reference_stop,
                reference_target,
            )
        ):
            raise ExecutionError("Reference and broker prices must be finite and positive")
        if side == "BUY" and not (
            reference_stop < reference_entry < reference_target
        ):
            raise ExecutionError("BUY reference protection must satisfy SL < entry < TP")
        if side == "SELL" and not (
            reference_target < reference_entry < reference_stop
        ):
            raise ExecutionError("SELL reference protection must satisfy TP < entry < SL")

        stop_distance = abs(reference_entry - reference_stop)
        target_distance = abs(reference_target - reference_entry)
        if side == "BUY":
            return broker_entry - stop_distance, broker_entry + target_distance
        return broker_entry + stop_distance, broker_entry - target_distance

    def _volume_for_risk(
        self,
        *,
        symbol: str,
        side: str,
        entry: float,
        stop_loss: float,
        risk_amount: float,
        info: Any,
    ) -> float:
        """Size from broker contract economics without exceeding approved risk."""
        order_type = (
            self.mt5.ORDER_TYPE_BUY if side == "BUY" else self.mt5.ORDER_TYPE_SELL
        )
        projected = self.mt5.order_calc_profit(
            order_type,
            symbol,
            1.0,
            float(entry),
            float(stop_loss),
        )
        if projected is None or not isfinite(float(projected)):
            raise ExecutionError(
                f"MT5 could not calculate entry risk: {self.mt5.last_error()}"
            )
        loss_per_lot = abs(float(projected))
        if loss_per_lot <= 0:
            raise ExecutionError("MT5 calculated zero loss at the protective stop")

        minimum = float(info.volume_min)
        maximum = float(info.volume_max)
        raw_volume = float(risk_amount) / loss_per_lot
        minimum_risk = loss_per_lot * minimum
        if raw_volume + 1e-12 < minimum:
            raise ExecutionError(
                "Broker minimum volume would exceed approved risk "
                f"({minimum_risk:.2f} > {risk_amount:.2f})"
            )
        return min(raw_volume, maximum)

    @staticmethod
    def _normalize_volume(volume: float, info: Any) -> float:
        minimum = float(info.volume_min)
        maximum = float(info.volume_max)
        step = float(info.volume_step)
        if volume < minimum or volume > maximum:
            raise ExecutionError(f"Volume must be between {minimum} and {maximum}")
        # Floor to the broker step so normalization can never increase risk.
        steps = floor(((volume - minimum) / step) + 1e-12)
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
    def _as_utc(value: datetime, field_name: str) -> datetime:
        if not isinstance(value, datetime):
            raise ExecutionError(f"{field_name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ExecutionError(f"{field_name} must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _to_result(
        result: Any, success: bool, position: Optional[int] = None
    ) -> TradeResult:
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
