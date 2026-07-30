from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional


AAQTS_MAGIC = 20260730


class ExecutionError(RuntimeError):
    """Raised whenever trade execution cannot safely continue."""


@dataclass(frozen=True)
class ExecutionConfig:
    """
    Global MT5 execution configuration.
    """

    terminal_path: Optional[str] = None

    magic: int = AAQTS_MAGIC

    deviation: int = 20

    max_open_positions: int = 3

    allow_duplicate_direction: bool = False

    require_stop_loss: bool = True

    require_take_profit: bool = True

    maximum_retry_attempts: int = 3

    retry_delay_seconds: float = 0.75

    maximum_spread_points: float = 30

    enable_break_even: bool = True

    break_even_trigger_rr: float = 1.0

    enable_trailing_stop: bool = True

    trailing_atr_multiplier: float = 1.5

    enable_partial_close: bool = True

    partial_close_ratio: float = 0.50

    trade_comment: str = "AAQTS"

    log_all_requests: bool = True


@dataclass(frozen=True)
class TradeResult:
    """
    Unified execution response.
    """

    success: bool

    retcode: Optional[int]

    comment: str

    order: Optional[int] = None

    deal: Optional[int] = None

    position: Optional[int] = None

    symbol: Optional[str] = None

    volume: Optional[float] = None

    price: Optional[float] = None

    stop_loss: Optional[float] = None

    take_profit: Optional[float] = None

    execution_time_ms: Optional[float] = None

    retries: int = 0

    request: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:

        return {
            "success": self.success,
            "retcode": self.retcode,
            "comment": self.comment,
            "order": self.order,
            "deal": self.deal,
            "position": self.position,
            "symbol": self.symbol,
            "volume": self.volume,
            "price": self.price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "execution_time_ms": self.execution_time_ms,
            "retries": self.retries,
            "request": dict(self.request),
        }


class MT5Executor:
    """
    Production-grade MetaTrader 5 execution engine.

    Features
    --------
    • Safe connection management
    • Automatic reconnection
    • Market execution
    • Pending orders
    • Position recovery
    • Break-even support
    • Trailing stop
    • Partial close
    • Retry handling
    • Spread validation
    • Margin validation
    • Broker rule validation
    """

    ####################################################################
    # INITIALIZATION
    ####################################################################

    def __init__(
        self,
        config: Optional[ExecutionConfig] = None,
        adapter: Any = None,
    ):

        self.config = config or ExecutionConfig()

        if adapter is None:

            try:
                import MetaTrader5 as adapter

            except ImportError as exc:

                raise ExecutionError(
                    "MetaTrader5 package is not installed."
                ) from exc

        self.mt5 = adapter

        self.connected = False

        self.accept_new_trades = True

        self.connection_time = None

        self.last_execution = None

        self.last_error = None

        self.trade_counter = 0

        self.retry_counter = 0

        self._cached_account = None

        self._cached_terminal = None

        self._cached_symbols = {}

        self._managed_positions = {}

            ####################################################################
    # CONNECTION MANAGEMENT
    ####################################################################

    def connect(self) -> bool:
        """
        Initialize MT5 and validate terminal/account status.
        """

        if self.connected:
            return True

        kwargs = {}

        if self.config.terminal_path:
            kwargs["path"] = self.config.terminal_path

        if not self.mt5.initialize(**kwargs):

            raise ExecutionError(
                f"MT5 initialization failed: {self.mt5.last_error()}"
            )

        self.connected = True

        self.connection_time = time.time()

        self._cached_terminal = self.mt5.terminal_info()
        self._cached_account = self.mt5.account_info()

        if self._cached_terminal is None:
            self.shutdown()

            raise ExecutionError(
                "Unable to retrieve terminal information."
            )

        if self._cached_account is None:
            self.shutdown()

            raise ExecutionError(
                "Unable to retrieve account information."
            )

        if not self._cached_terminal.trade_allowed:

            self.shutdown()

            raise ExecutionError(
                "Algorithmic trading is disabled."
            )

        if not self._cached_account.trade_allowed:

            self.shutdown()

            raise ExecutionError(
                "Trading is disabled on this account."
            )

        if not self._cached_account.trade_expert:

            self.shutdown()

            raise ExecutionError(
                "Expert Advisors are disabled."
            )

        return True


    def reconnect(self) -> bool:
        """
        Force reconnection.
        """

        self.shutdown()

        time.sleep(1)

        return self.connect()


    def shutdown(self) -> None:

        try:

            self.mt5.shutdown()

        except Exception:
            pass

        self.connected = False

        self.connection_time = None

        self._cached_account = None

        self._cached_terminal = None

        self._cached_symbols.clear()


    ####################################################################
    # EXECUTION CONTROL
    ####################################################################

    def pause(self):

        self.accept_new_trades = False


    def resume(self):

        self.accept_new_trades = True


    ####################################################################
    # ACCOUNT INFORMATION
    ####################################################################

    def account_info(self):

        self._ensure_connected()

        account = self.mt5.account_info()

        if account is None:

            raise ExecutionError(
                "Unable to retrieve account information."
            )

        self._cached_account = account

        return account


    def terminal_info(self):

        self._ensure_connected()

        terminal = self.mt5.terminal_info()

        if terminal is None:

            raise ExecutionError(
                "Unable to retrieve terminal information."
            )

        self._cached_terminal = terminal

        return terminal


    ####################################################################
    # SYMBOL MANAGEMENT
    ####################################################################

    def symbol_info(self, symbol: str):

        self._ensure_connected()

        if symbol in self._cached_symbols:

            return self._cached_symbols[symbol]

        info = self.mt5.symbol_info(symbol)

        if info is None:

            raise ExecutionError(
                f"Unknown symbol: {symbol}"
            )

        if (
            not info.visible
            and not self.mt5.symbol_select(symbol, True)
        ):

            raise ExecutionError(
                f"Unable to activate symbol: {symbol}"
            )

        self._cached_symbols[symbol] = info

        return info


    def symbol_tick(self, symbol: str):

        tick = self.mt5.symbol_info_tick(symbol)

        if tick is None:

            raise ExecutionError(
                f"No market data available for {symbol}"
            )

        return tick


    ####################################################################
    # POSITION DISCOVERY
    ####################################################################

    def positions(
        self,
        symbol: Optional[str] = None,
        managed_only: bool = True,
    ):

        self._ensure_connected()

        raw = (
            self.mt5.positions_get(symbol=symbol)
            if symbol
            else self.mt5.positions_get()
        )

        positions = list(raw or [])

        if managed_only:

            positions = [

                p

                for p in positions

                if getattr(
                    p,
                    "magic",
                    None,
                ) == self.config.magic

            ]

        return positions


    def recover_positions(self):

        positions = self.positions(
            managed_only=True
        )

        self._managed_positions = {

            p.ticket: p

            for p in positions

        }

        return positions


    ####################################################################
    # MARKET VALIDATION
    ####################################################################

    def validate_market(
        self,
        symbol: str,
    ):

        info = self.symbol_info(symbol)

        tick = self.symbol_tick(symbol)

        spread = (
            tick.ask
            - tick.bid
        )

        spread_points = (
            spread
            / info.point
        )

        if (
            spread_points
            > self.config.maximum_spread_points
        ):

            raise ExecutionError(
                f"Spread too high ({spread_points:.1f} points)"
            )

        return {

            "symbol": symbol,

            "spread_points": round(
                spread_points,
                2,
            ),

            "bid": tick.bid,

            "ask": tick.ask,

            "digits": info.digits,

            "point": info.point,

            "volume_min": info.volume_min,

            "volume_max": info.volume_max,

            "volume_step": info.volume_step,

        }


    ####################################################################
    # MARGIN CHECK
    ####################################################################

    def check_margin(
        self,
        symbol,
        side,
        volume,
    ):

        info = self.symbol_info(symbol)

        tick = self.symbol_tick(symbol)

        order_type = (
            self.mt5.ORDER_TYPE_BUY
            if side == "BUY"
            else self.mt5.ORDER_TYPE_SELL
        )

        price = (
            tick.ask
            if side == "BUY"
            else tick.bid
        )

        margin = self.mt5.order_calc_margin(
            order_type,
            symbol,
            volume,
            price,
        )

        if margin is None:

            raise ExecutionError(
                "Unable to calculate margin."
            )

        account = self.account_info()

        if margin > account.margin_free:

            raise ExecutionError(
                "Insufficient free margin."
            )

        return margin

            ####################################################################
    # MARKET EXECUTION
    ####################################################################

    def place_market_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        stop_loss: float,
        take_profit: float,
        comment: Optional[str] = None,
    ) -> TradeResult:

        self._ensure_connected()

        if not self.accept_new_trades:

            raise ExecutionError(
                "New trade entries are currently paused."
            )

        side = side.upper().strip()

        if side not in ("BUY", "SELL"):

            raise ExecutionError(
                "side must be BUY or SELL"
            )

        if volume <= 0:

            raise ExecutionError(
                "Volume must be greater than zero."
            )

        info = self.symbol_info(symbol)

        tick = self.symbol_tick(symbol)

        self.validate_market(symbol)

        self.check_margin(
            symbol,
            side,
            volume,
        )

        volume = self._normalize_volume(
            volume,
            info,
        )

        if side == "BUY":

            price = tick.ask

            order_type = self.mt5.ORDER_TYPE_BUY

        else:

            price = tick.bid

            order_type = self.mt5.ORDER_TYPE_SELL

        self._validate_protection(
            side,
            price,
            stop_loss,
            take_profit,
            info,
        )

        self._validate_position_limits(
            symbol,
            side,
        )

        request = {

            "action":
                self.mt5.TRADE_ACTION_DEAL,

            "symbol":
                symbol,

            "volume":
                volume,

            "type":
                order_type,

            "price":
                self._round_price(
                    price,
                    info,
                ),

            "sl":
                self._round_price(
                    stop_loss,
                    info,
                ),

            "tp":
                self._round_price(
                    take_profit,
                    info,
                ),

            "deviation":
                self.config.deviation,

            "magic":
                self.config.magic,

            "comment":
                (
                    comment
                    or self.config.trade_comment
                )[:31],

            "type_time":
                self.mt5.ORDER_TIME_GTC,

            "type_filling":
                self._filling_mode(
                    info,
                ),
        }

        if self.config.log_all_requests:

            print(
                "[AAQTS]",
                request,
            )

        retries = 0

        start = time.perf_counter()

        while retries <= self.config.maximum_retry_attempts:

            check = self.mt5.order_check(
                request
            )

            if (
                check is None
                or getattr(
                    check,
                    "retcode",
                    None,
                ) != 0
            ):

                detail = getattr(
                    check,
                    "comment",
                    self.mt5.last_error(),
                )

                raise ExecutionError(
                    f"order_check failed: {detail}"
                )

            result = self.mt5.order_send(
                request
            )

            success_code = getattr(
                self.mt5,
                "TRADE_RETCODE_DONE",
                10009,
            )

            if (
                result is not None
                and getattr(
                    result,
                    "retcode",
                    None,
                )
                == success_code
            ):

                elapsed = (
                    time.perf_counter()
                    - start
                ) * 1000

                self.trade_counter += 1

                self.last_execution = time.time()

                return TradeResult(

                    success=True,

                    retcode=result.retcode,

                    comment=result.comment,

                    order=getattr(
                        result,
                        "order",
                        None,
                    ),

                    deal=getattr(
                        result,
                        "deal",
                        None,
                    ),

                    position=(
                        getattr(result, "position", None)
                        or getattr(result, "order", None)
                    )

                    symbol=symbol,

                    volume=volume,

                    price=price,

                    stop_loss=stop_loss,

                    take_profit=take_profit,

                    execution_time_ms=round(
                        elapsed,
                        2,
                    ),

                    retries=retries,

                    request=request,

                )

            retries += 1

            self.retry_counter += 1

            self.last_error = result

            if (
                retries
                > self.config.maximum_retry_attempts
            ):

                break

            time.sleep(
                self.config.retry_delay_seconds
            )

            tick = self.symbol_tick(symbol)

            if side == "BUY":

                request["price"] = self._round_price(
                    tick.ask,
                    info,
                )

            else:

                request["price"] = self._round_price(
                    tick.bid,
                    info,
                )

        raise ExecutionError(

            f"Trade execution failed after "
            f"{retries} attempts."

        )

            ####################################################################
    # POSITION MANAGEMENT
    ####################################################################

    def modify_protection(
        self,
        position_ticket: int,
        stop_loss: float,
        take_profit: float,
    ) -> TradeResult:

        self._ensure_connected()

        position = self._position_by_ticket(
            position_ticket
        )

        info = self.symbol_info(
            position.symbol
        )

        tick = self.symbol_tick(
            position.symbol
        )

        side = (
            "BUY"
            if position.type
            == self.mt5.POSITION_TYPE_BUY
            else "SELL"
        )

        price = (
            tick.bid
            if side == "BUY"
            else tick.ask
        )

        self._validate_protection(
            side,
            price,
            stop_loss,
            take_profit,
            info,
        )

        request = {

            "action":
                self.mt5.TRADE_ACTION_SLTP,

            "position":
                position.ticket,

            "symbol":
                position.symbol,

            "sl":
                self._round_price(
                    stop_loss,
                    info,
                ),

            "tp":
                self._round_price(
                    take_profit,
                    info,
                ),

            "magic":
                self.config.magic,

        }

        result = self.mt5.order_send(
            request
        )

        success = (
            result is not None
            and getattr(
                result,
                "retcode",
                None,
            )
            == getattr(
                self.mt5,
                "TRADE_RETCODE_DONE",
                10009,
            )
        )

        if not success:

            raise ExecutionError(
                f"Protection update failed: "
                f"{getattr(result,'comment','Unknown')}"
            )

        return self._to_result(
            result,
            True,
            position.ticket,
        )

    ####################################################################
    # BREAK EVEN
    ####################################################################

    def move_to_break_even(
        self,
        position_ticket: int,
    ) -> TradeResult:

        self._ensure_connected()

        position = self._position_by_ticket(
            position_ticket
        )

        entry = position.price_open

        return self.modify_protection(
            position_ticket,
            entry,
            position.tp,
        )

    ####################################################################
    # TRAILING STOP
    ####################################################################

    def update_trailing_stop(
        self,
        position_ticket: int,
        new_stop: float,
    ) -> TradeResult:

        self._ensure_connected()

        position = self._position_by_ticket(
            position_ticket
        )

        if (
            position.type
            == self.mt5.POSITION_TYPE_BUY
        ):

            if new_stop <= position.sl:

                raise ExecutionError(
                    "Trailing stop must only move upward."
                )

        else:

            if (
                position.sl != 0
                and new_stop >= position.sl
            ):

                raise ExecutionError(
                    "Trailing stop must only move downward."
                )

        return self.modify_protection(

            position.ticket,

            new_stop,

            position.tp,

        )

    ####################################################################
    # PARTIAL CLOSE
    ####################################################################

    def partial_close(
        self,
        ticket: int,
        volume: float,
        comment="AAQTS Partial",
    ) -> TradeResult:

        self._ensure_connected()

        position = self._position_by_ticket(
            ticket
        )

        info = self.symbol_info(
            position.symbol
        )

        tick = self.symbol_tick(
            position.symbol
        )

        volume = self._normalize_volume(
            volume,
            info,
        )

        if volume >= position.volume:

            raise ExecutionError(
                "Partial volume must be smaller than current volume."
            )

        closing_buy = (
            position.type
            != self.mt5.POSITION_TYPE_BUY
        )

        request = {

            "action":
                self.mt5.TRADE_ACTION_DEAL,

            "position":
                position.ticket,

            "symbol":
                position.symbol,

            "volume":
                volume,

            "type":
                (
                    self.mt5.ORDER_TYPE_BUY
                    if closing_buy
                    else self.mt5.ORDER_TYPE_SELL
                ),

            "price":
                (
                    tick.ask
                    if closing_buy
                    else tick.bid
                ),

            "deviation":
                self.config.deviation,

            "magic":
                self.config.magic,

            "comment":
                comment[:31],

            "type_time":
                self.mt5.ORDER_TIME_GTC,

            "type_filling":
                self._filling_mode(
                    info
                ),

        }

        result = self.mt5.order_send(
            request
        )

        success = (
            result is not None
            and getattr(
                result,
                "retcode",
                None,
            )
            == getattr(
                self.mt5,
                "TRADE_RETCODE_DONE",
                10009,
            )
        )

        if not success:

            raise ExecutionError(
                f"Partial close failed: "
                f"{getattr(result,'comment','Unknown')}"
            )

        return self._to_result(
            result,
            True,
            ticket,
        )

    ####################################################################
    # CLOSE POSITION
    ####################################################################

    def close_position(
        self,
        ticket: int,
        comment="AAQTS Close",
    ) -> TradeResult:

        self._ensure_connected()

        position = self._position_by_ticket(
            ticket
        )

        return self.partial_close(

            ticket,

            position.volume,

            comment,

        )

    ####################################################################
    # CLOSE ALL
    ####################################################################

    def close_all(self):

        results = []

        for position in list(

            self.positions(
                managed_only=True
            )

        ):

            try:

                results.append(

                    self.close_position(
                        position.ticket,
                        "AAQTS Emergency Close",
                    )

                )

            except Exception as exc:

                print(exc)

        return results

    ####################################################################
    # EMERGENCY STOP
    ####################################################################

    def emergency_stop(self):

        self.pause()

        return self.close_all()

            ####################################################################
    # INTERNAL HELPERS
    ####################################################################

    def _position_by_ticket(
        self,
        ticket: int,
    ):

        positions = self.positions(
            managed_only=True
        )

        for position in positions:

            if position.ticket == ticket:

                return position

        raise ExecutionError(
            f"Position {ticket} not found."
        )

    ####################################################################

    def _validate_position_limits(
        self,
        symbol: str,
        side: str,
    ):

        positions = self.positions(
            managed_only=True
        )

        if (
            len(positions)
            >= self.config.max_open_positions
        ):

            raise ExecutionError(
                "Maximum open-position limit reached."
            )

        if self.config.allow_duplicate_direction:

            return

        desired = (
            self.mt5.POSITION_TYPE_BUY
            if side == "BUY"
            else self.mt5.POSITION_TYPE_SELL
        )

        for position in positions:

            if (
                position.symbol == symbol
                and position.type == desired
            ):

                raise ExecutionError(
                    f"Duplicate {side} trade on {symbol}."
                )

    ####################################################################

    def _validate_protection(
        self,
        side,
        entry,
        sl,
        tp,
        info,
    ):

        if side == "BUY":

            if not (
                sl < entry < tp
            ):

                raise ExecutionError(
                    "BUY requires SL < Entry < TP."
                )

        else:

            if not (
                tp < entry < sl
            ):

                raise ExecutionError(
                    "SELL requires TP < Entry < SL."
                )

        minimum = max(
            getattr(
                info,
                "trade_stops_level",
                0,
            ),
            0,
        ) * info.point

        if minimum:

            if (
                abs(entry - sl)
                < minimum
            ):

                raise ExecutionError(
                    "Stop Loss too close."
                )

            if (
                abs(tp - entry)
                < minimum
            ):

                raise ExecutionError(
                    "Take Profit too close."
                )

    ####################################################################

    @staticmethod
    def _normalize_volume(
        volume,
        info,
    ):

        minimum = float(
            info.volume_min
        )

        maximum = float(
            info.volume_max
        )

        step = float(
            info.volume_step
        )

        if volume < minimum:

            volume = minimum

        if volume > maximum:

            volume = maximum

        steps = round(
            (
                volume - minimum
            )
            / step
        )

        volume = (
            minimum
            + (
                steps
                * step
            )
        )

        return round(
            volume,
            8,
        )

    ####################################################################

    def _filling_mode(
        self,
        info,
    ):

        advertised = int(
            getattr(
                info,
                "filling_mode",
                0,
            )
        )

        if advertised & 1:

            return self.mt5.ORDER_FILLING_FOK

        if advertised & 2:

            return self.mt5.ORDER_FILLING_IOC

        return self.mt5.ORDER_FILLING_RETURN

    ####################################################################

    @staticmethod
    def _round_price(
        price,
        info,
    ):

        return round(
            float(price),
            int(info.digits),
        )

    ####################################################################

    def _ensure_connected(self):

        if self.connected:

            return

        self.connect()

    ####################################################################

    def _log(
        self,
        message: str,
    ):

        if self.config.log_all_requests:

            print(
                "[AAQTS]",
                message,
            )

    ####################################################################

    def _sleep_before_retry(self):

        time.sleep(
            self.config.retry_delay_seconds
        )

    ####################################################################

    @staticmethod
    def _is_success(
        mt5,
        result,
    ):

        if result is None:

            return False

        success = getattr(
            mt5,
            "TRADE_RETCODE_DONE",
            10009,
        )

        return (
            getattr(
                result,
                "retcode",
                None,
            )
            == success
        )

    ####################################################################

    @staticmethod
    def _to_result(
        result,
        success,
        position=None,
    ):

        if result is None:

            return TradeResult(

                success=False,

                retcode=None,

                comment="No MT5 response",

                position=position,

            )

        return TradeResult(

            success=success,

            retcode=getattr(
                result,
                "retcode",
                None,
            ),

            comment=str(
                getattr(
                    result,
                    "comment",
                    "",
                )
            ),

            order=getattr(
                result,
                "order",
                None,
            ),

            deal=getattr(
                result,
                "deal",
                None,
            ),

            position=(
                position
                or getattr(
                    result,
                    "order",
                    None,
                )
            ),

        )