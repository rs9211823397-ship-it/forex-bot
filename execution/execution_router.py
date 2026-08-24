"""Route validated trade plans to paper, MT5 demo, or guarded MT5 live execution.

PAPER remains the default. MT5_LIVE requires an explicit real-money release
acknowledgement plus a pinned real account and server.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config.settings import (
    EXECUTION_MODE,
    MT5_EXPECTED_LOGIN,
    MT5_LOGIN,
    MT5_MAX_OPEN_POSITIONS,
    MT5_MAX_SPREAD_STOP_RATIO,
    MT5_MAX_TICK_AGE_SECONDS,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_SERVER_UTC_OFFSET_MINUTES,
    MT5_SYMBOL_MAP,
    MT5_SYMBOL_SUFFIX,
    MT5_TERMINAL_PATH,
    MT5_USE_PREAUTHENTICATED_SESSION,
    STRATEGY_MODE,
    UTBOT_BREAK_EVEN_TRIGGER_R,
    UTBOT_EXIT_MODE,
    UTBOT_TEST_LOT,
    UTBOT_TRAILING_ATR_MULTIPLIER,
    UTBOT_TRAILING_START_R,
)
from config.symbols import executable_symbol_map
from execution.live_mt5_executor import LiveMT5Executor
from execution.mt5_executor import (
    AccountSnapshot,
    ClosedPositionResult,
    ExecutionConfig,
    ExecutionError,
    MT5Executor,
)
from execution.mt5_trade_audit import MT5TradeAudit
from execution.position_manager import PositionManager, PositionManagerConfig
from mt5_time import mt5_epoch_to_utc_seconds
from runtime_state import RUNTIME_DIR


logger = logging.getLogger(__name__)
VALID_MODES = {"PAPER", "MT5_DEMO", "MT5_LIVE"}
BROKER_MODES = {"MT5_DEMO", "MT5_LIVE"}
LIVE_ACK_VALUE = "I_UNDERSTAND_REAL_MONEY"


def _stop_loss_cooldown_minutes() -> int:
    raw = os.getenv("AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES", "0").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES must be an integer"
        ) from exc
    if value < 0 or value > 1440:
        raise ValueError(
            "AAQTS_MT5_STOP_LOSS_COOLDOWN_MINUTES must be between 0 and 1440"
        )
    return value


def _strategy_risk_isolation_enabled(mode: str) -> bool:
    """Return whether AAQTS should use strategy-only risk equity.

    Demo defaults to isolated risk accounting so another EA on the same MT5
    account cannot change AAQTS sizing/drawdown merely through its PnL. Live
    keeps broker account equity unless the operator explicitly opts in.
    """
    raw = os.getenv("AAQTS_ISOLATE_STRATEGY_RISK")
    if raw is None:
        return mode == "MT5_DEMO"
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("AAQTS_ISOLATE_STRATEGY_RISK must be true or false")


def _position_management_symbol_map() -> dict[str, str]:
    """Return the full broker map used only for already-open position care."""
    return {
        source: f"{broker}{MT5_SYMBOL_SUFFIX}"
        for source, broker in executable_symbol_map().items()
    }


class ExecutionRouter:
    def __init__(
        self,
        paper_trader: Any,
        mode: str = EXECUTION_MODE,
        mt5_executor: Optional[MT5Executor] = None,
        position_manager: Optional[PositionManager] = None,
        trade_audit: Optional[MT5TradeAudit] = None,
        signal_exit_mode: Optional[bool] = None,
        signal_test_lot: Optional[float] = None,
        protected_utbot_mode: Optional[bool] = None,
        opposite_signal_exit: Optional[bool] = None,
    ) -> None:
        self.paper_trader = paper_trader
        self.mode = mode.upper().strip()
        if self.mode not in VALID_MODES:
            raise ValueError(f"Unsupported execution mode: {self.mode}")
        self.signal_exit_mode = (
            STRATEGY_MODE == "UT_BOT" and UTBOT_EXIT_MODE == "OPPOSITE_SIGNAL"
            if signal_exit_mode is None
            else bool(signal_exit_mode)
        )
        self.protected_utbot_mode = (
            STRATEGY_MODE == "UT_BOT" and UTBOT_EXIT_MODE == "ATR_TRAIL"
            if protected_utbot_mode is None
            else bool(protected_utbot_mode)
        )
        if self.signal_exit_mode and self.protected_utbot_mode:
            raise ValueError("UT Bot cannot use protected and unprotected modes together")
        self.opposite_signal_exit = (
            self.signal_exit_mode or self.protected_utbot_mode
            if opposite_signal_exit is None
            else bool(opposite_signal_exit)
        )
        self.signal_test_lot = float(
            UTBOT_TEST_LOT if signal_test_lot is None else signal_test_lot
        )
        if self.signal_test_lot <= 0:
            raise ValueError("signal_test_lot must be positive")
        if self.signal_exit_mode and self.mode == "MT5_LIVE":
            raise ExecutionError(
                "UT Bot opposite-signal mode without broker SL/TP is locked to PAPER/MT5_DEMO"
            )

        self._isolate_strategy_risk = _strategy_risk_isolation_enabled(self.mode)
        self._strategy_risk_anchor_time: datetime | None = None
        self._strategy_risk_anchor_balance: float | None = None
        self._position_lock = threading.RLock()

        if self.mode == "MT5_LIVE":
            acknowledgement = os.getenv("AAQTS_LIVE_TRADING_ACK", "").strip()
            if acknowledgement != LIVE_ACK_VALUE:
                raise ExecutionError(
                    "MT5_LIVE is locked. Set AAQTS_LIVE_TRADING_ACK="
                    f"{LIVE_ACK_VALUE} only when intentionally enabling real-money orders."
                )
            if not MT5_EXPECTED_LOGIN:
                raise ExecutionError("MT5_LIVE requires a pinned expected account login")
            if not MT5_SERVER:
                raise ExecutionError("MT5_LIVE requires an explicitly expected MT5 server")

        self.mt5_executor = mt5_executor
        if self.mode in BROKER_MODES and self.mt5_executor is None:
            if self.mode == "MT5_DEMO" and not MT5_EXPECTED_LOGIN:
                raise ExecutionError(
                    "MT5_DEMO requires a pinned expected account login"
                )
            credential_fields = (bool(MT5_LOGIN), bool(MT5_PASSWORD), bool(MT5_SERVER))
            if not MT5_USE_PREAUTHENTICATED_SESSION and any(credential_fields) and not all(
                credential_fields
            ):
                raise ExecutionError(
                    "MT5 credentials must provide LOGIN, PASSWORD, and SERVER together"
                )
            config = ExecutionConfig(
                terminal_path=MT5_TERMINAL_PATH,
                login=int(MT5_LOGIN) if MT5_LOGIN else None,
                expected_login=(int(MT5_EXPECTED_LOGIN) if MT5_EXPECTED_LOGIN else None),
                password=MT5_PASSWORD,
                server=MT5_SERVER,
                # One position per configured symbol remains enforced.  The
                # old three-position portfolio cap is not part of this demo
                # signal-lifecycle experiment.
                max_open_positions=(20 if self.signal_exit_mode else MT5_MAX_OPEN_POSITIONS),
                require_stop_loss=not self.signal_exit_mode,
                # ATR_TRAIL intentionally has no fixed target: a broker-side
                # stop is advanced to break-even and then trailed while the
                # opposite UT crossover remains a final exit.
                require_take_profit=not (
                    self.signal_exit_mode or self.protected_utbot_mode
                ),
                max_tick_age_seconds=MT5_MAX_TICK_AGE_SECONDS,
                server_utc_offset_minutes=MT5_SERVER_UTC_OFFSET_MINUTES,
                max_spread_stop_ratio=MT5_MAX_SPREAD_STOP_RATIO,
                fill_audit_path=str(RUNTIME_DIR / "mt5_fill_audit.jsonl"),
            )
            self.mt5_executor = (
                LiveMT5Executor(config) if self.mode == "MT5_LIVE" else MT5Executor(config)
            )

        self.position_manager = position_manager
        if (
            self.mode in BROKER_MODES
            and self.position_manager is None
            and not self.signal_exit_mode
        ):
            assert self.mt5_executor is not None
            manager_config = None
            if self.protected_utbot_mode:
                manager_config = PositionManagerConfig(
                    enable_break_even=True,
                    break_even_trigger_rr=UTBOT_BREAK_EVEN_TRIGGER_R,
                    enable_trailing_stop=True,
                    trailing_start_rr=UTBOT_TRAILING_START_R,
                    trailing_atr_multiplier=UTBOT_TRAILING_ATR_MULTIPLIER,
                    enable_tp1=False,
                    enable_tp2=False,
                    enable_runner=True,
                    enable_time_exit=False,
                    require_initial_stop_loss=True,
                )
            self.position_manager = PositionManager(
                self.mt5_executor,
                config=manager_config,
            )

        self.trade_audit = trade_audit
        if self.mode in BROKER_MODES and self.trade_audit is None:
            assert self.mt5_executor is not None
            mt5_api = getattr(self.mt5_executor, "mt5", None)
            config = getattr(self.mt5_executor, "config", None)
            if mt5_api is not None and config is not None and hasattr(mt5_api, "history_deals_get"):
                self.trade_audit = MT5TradeAudit(self.mt5_executor)

    def _capture_strategy_risk_anchor(self) -> None:
        if (
            self.mode not in BROKER_MODES
            or not self._isolate_strategy_risk
            or self._strategy_risk_anchor_time is not None
        ):
            return
        assert self.mt5_executor is not None
        actual = self.mt5_executor.account_snapshot()
        self._strategy_risk_anchor_time = datetime.now(timezone.utc)
        self._strategy_risk_anchor_balance = float(actual.balance)
        logger.info(
            "AAQTS strategy-risk isolation anchored at %.2f; non-AAQTS PnL will not affect risk sizing",
            self._strategy_risk_anchor_balance,
        )

    def start(self) -> list[Any]:
        if self.mode not in BROKER_MODES:
            return []
        assert self.mt5_executor is not None
        self.mt5_executor.connect()
        self._capture_strategy_risk_anchor()
        recovered = []
        if self.position_manager is not None:
            with self._position_lock:
                recovered = self.position_manager.recover_positions(reset_registry=True)
        if self.trade_audit is not None:
            self.trade_audit.sync_closed()
        return recovered

    def _validate_entry_quote(self, mt5_symbol: str, risk_plan: dict[str, float]) -> None:
        assert self.mt5_executor is not None
        info = self.mt5_executor.symbol_info(mt5_symbol)
        tick = self.mt5_executor.symbol_tick(mt5_symbol)
        bid = float(getattr(tick, "bid", 0.0) or 0.0)
        ask = float(getattr(tick, "ask", 0.0) or 0.0)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise ExecutionError(f"Invalid executable quote for {mt5_symbol}")

        timestamp_ms = float(getattr(tick, "time_msc", 0.0) or 0.0)
        timestamp_s = timestamp_ms / 1000.0 if timestamp_ms > 0 else float(
            getattr(tick, "time", 0.0) or 0.0
        )
        if timestamp_s <= 0:
            raise ExecutionError(f"MT5 tick for {mt5_symbol} has no valid timestamp")
        timestamp_s = mt5_epoch_to_utc_seconds(
            timestamp_s,
            MT5_SERVER_UTC_OFFSET_MINUTES,
        )
        age = datetime.now(timezone.utc).timestamp() - timestamp_s
        if age < -5 or age > MT5_MAX_TICK_AGE_SECONDS:
            raise ExecutionError(
                f"Stale MT5 tick for {mt5_symbol}: age={age:.1f}s "
                f"max={MT5_MAX_TICK_AGE_SECONDS:.1f}s"
            )

        point = float(getattr(info, "point", 0.0) or 0.0)
        spread = ask - bid
        stop_distance = abs(float(risk_plan["entry"]) - float(risk_plan["stop_loss"]))
        reference = max(stop_distance, point, 1e-12)
        ratio = spread / reference
        if ratio > MT5_MAX_SPREAD_STOP_RATIO:
            raise ExecutionError(
                f"Spread too wide for {mt5_symbol}: spread/stop={ratio:.3f} "
                f"> {MT5_MAX_SPREAD_STOP_RATIO:.3f}"
            )

    def _enforce_stop_loss_cooldown(self, source_symbol: str, side: str) -> None:
        """Block churn after an AAQTS-managed stop loss on the same symbol."""
        if self.mode not in BROKER_MODES or self.trade_audit is None:
            return
        cooldown_minutes = _stop_loss_cooldown_minutes()
        if cooldown_minutes <= 0:
            return
        broker_symbol = str(MT5_SYMBOL_MAP.get(source_symbol, "")).strip().upper()
        if not broker_symbol:
            return
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=cooldown_minutes)
        recent = self.trade_audit.managed_closed_deals(start, end)
        stop_losses = [
            item
            for item in recent
            if str(getattr(item, "symbol", "")).strip().upper() == broker_symbol
            and str(getattr(item, "exit_reason", "")).strip().upper() == "STOP_LOSS"
        ]
        if not stop_losses:
            return
        latest = max(stop_losses, key=lambda item: item.closed_at)
        elapsed = max(0.0, (end - latest.closed_at).total_seconds() / 60.0)
        remaining = max(0.0, cooldown_minutes - elapsed)
        raise ExecutionError(
            f"Stop-loss cooldown active for {source_symbol}: blocked {side} re-entry; "
            f"last AAQTS stop was {elapsed:.1f}m ago, {remaining:.1f}m remaining"
        )

    def execute(
        self,
        source_symbol: str,
        signal: str,
        risk_plan: dict[str, float],
        paper_position_size: float,
        approved_risk_amount: Optional[float] = None,
    ) -> Any:
        if not risk_plan:
            raise ValueError("risk_plan is required")
        required = (
            {"entry"}
            if self.signal_exit_mode
            else {"entry", "stop_loss", "take_profit"}
        )
        missing = required.difference(risk_plan)
        if missing:
            raise ValueError("risk_plan is missing: " + ", ".join(sorted(missing)))
        side = signal.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Only BUY or SELL signals can be executed")
        if self.mode == "PAPER":
            return self.paper_trader.open_trade(
                source_symbol,
                side,
                risk_plan["entry"],
                0.0 if self.signal_exit_mode else risk_plan["stop_loss"],
                0.0 if self.signal_exit_mode else risk_plan["take_profit"],
                self.signal_test_lot if self.signal_exit_mode else paper_position_size,
            )

        assert self.mt5_executor is not None
        mt5_symbol = MT5_SYMBOL_MAP.get(source_symbol)
        if not mt5_symbol:
            raise ExecutionError(f"No MT5 symbol mapping configured for {source_symbol}")
        if (
            not self.signal_exit_mode
            and (approved_risk_amount is None or approved_risk_amount <= 0)
        ):
            raise ExecutionError("MT5 execution requires a positive portfolio-approved risk amount")
        if not self.signal_exit_mode:
            self._enforce_stop_loss_cooldown(source_symbol, side)
            self._validate_entry_quote(mt5_symbol, risk_plan)
        result = self.mt5_executor.place_market_order(
            symbol=mt5_symbol,
            side=side,
            volume=(self.signal_test_lot if self.signal_exit_mode else None),
            stop_loss=(0.0 if self.signal_exit_mode else risk_plan["stop_loss"]),
            take_profit=(0.0 if self.signal_exit_mode else risk_plan["take_profit"]),
            comment=f"AAQTS {source_symbol}",
            reference_entry=(None if self.signal_exit_mode else risk_plan["entry"]),
            risk_amount=(
                None if self.signal_exit_mode else float(approved_risk_amount)
            ),
            source_symbol=source_symbol,
        )
        managed = None
        if self.position_manager is not None:
            with self._position_lock:
                managed = self.position_manager.register_execution_result(result)
        if self.trade_audit is not None:
            self.trade_audit.record_entry(
                source_symbol=source_symbol,
                side=side,
                risk_plan=risk_plan,
                result=result,
                managed_position=managed,
                volume_override=(self.signal_test_lot if self.signal_exit_mode else None),
            )
        return result

    def close_on_opposite_signal(
        self,
        source_symbol: str,
        side: str,
        current_price: Optional[float] = None,
    ) -> list[Any]:
        """Close an existing opposite position before an optional reversal."""

        if not self.opposite_signal_exit:
            return []
        wanted = str(side).upper().strip()
        if wanted not in {"BUY", "SELL"}:
            raise ValueError("Opposite-signal exit requires BUY or SELL")
        if self.mode == "PAPER":
            closed = self.paper_trader.close_trade_on_signal(
                source_symbol,
                wanted,
                current_price=current_price,
            )
            return [] if closed is None else [closed]

        assert self.mt5_executor is not None
        broker_symbol = MT5_SYMBOL_MAP.get(source_symbol)
        if not broker_symbol:
            raise ExecutionError(f"No MT5 symbol mapping configured for {source_symbol}")
        positions = self.mt5_executor.positions(symbol=broker_symbol, managed_only=True)
        opposite = [
            position
            for position in positions
            if self.mt5_executor.position_side(position) != wanted
        ]
        results = []
        with self._position_lock:
            for position in opposite:
                results.append(
                    self.mt5_executor.close_position(
                        int(position.ticket),
                        comment="AAQTS opposite UT exit",
                    )
                )
        if results and self.trade_audit is not None:
            self.trade_audit.sync_closed()
        return results

    def manage_positions(self, atr_by_source_symbol: Optional[dict[str, float]] = None) -> dict[str, Any]:
        if self.signal_exit_mode:
            return {
                "managed": False,
                "reason": "utbot_opposite_signal_exit",
                "reports": [],
                "errors": [],
            }
        if self.mode not in BROKER_MODES or self.position_manager is None:
            return {"managed": False, "reason": "paper_mode_uses_price_checks", "reports": [], "errors": []}
        atr_by_source_symbol = atr_by_source_symbol or {}
        management_map = _position_management_symbol_map()
        broker_atr = {
            management_map[source]: float(atr)
            for source, atr in atr_by_source_symbol.items()
            if source in management_map
        }
        with self._position_lock:
            report = self.position_manager.manage_positions(
                broker_atr, force_sync=False
            )
        if self.trade_audit is not None:
            try:
                self.trade_audit.sync_closed()
            except Exception as exc:
                logger.exception("MT5 trade-audit synchronization failed during position management")
                report.setdefault("errors", []).append(f"trade_audit: {exc}")
        return report

    def pause(self) -> None:
        if self.mt5_executor is not None:
            self.mt5_executor.pause()

    def resume(self) -> None:
        if self.mt5_executor is not None:
            self.mt5_executor.resume()

    def emergency_stop(self) -> list[Any]:
        if self.mode not in BROKER_MODES or self.mt5_executor is None:
            return []
        results = self.mt5_executor.emergency_stop()
        if self.trade_audit is not None:
            self.trade_audit.sync_closed()
        return results

    def positions(self) -> list[Any]:
        if self.mode not in BROKER_MODES or self.mt5_executor is None:
            return list(getattr(self.paper_trader, "open_trades", []))
        return self.mt5_executor.positions(managed_only=True)

    def account_snapshot(self) -> AccountSnapshot:
        if self.mode == "PAPER":
            return AccountSnapshot(balance=float(self.paper_trader.balance), equity=float(self.paper_trader.equity))
        assert self.mt5_executor is not None
        actual = self.mt5_executor.account_snapshot()
        if not self._isolate_strategy_risk:
            return actual

        self._capture_strategy_risk_anchor()
        assert self._strategy_risk_anchor_time is not None
        assert self._strategy_risk_anchor_balance is not None
        end = datetime.now(timezone.utc)
        if self.trade_audit is not None:
            closed = self.trade_audit.closed_position_results(
                self._strategy_risk_anchor_time,
                end,
            )
        else:
            closed = self.mt5_executor.closed_position_results(
                self._strategy_risk_anchor_time,
                end,
            )
        realized = sum(float(item.profit_loss) for item in closed)
        floating = sum(
            float(getattr(position, "profit", 0.0) or 0.0)
            + float(getattr(position, "swap", 0.0) or 0.0)
            for position in self.mt5_executor.positions(managed_only=True)
        )
        isolated_balance = self._strategy_risk_anchor_balance + realized
        isolated_equity = isolated_balance + floating
        return AccountSnapshot(
            balance=isolated_balance,
            equity=isolated_equity,
            login=actual.login,
            server=actual.server,
            trade_mode=actual.trade_mode,
        )

    def closed_position_results(self, start_time: datetime, end_time: datetime) -> list[ClosedPositionResult]:
        if self.mode not in BROKER_MODES or self.mt5_executor is None:
            return []
        if self.trade_audit is not None:
            return self.trade_audit.closed_position_results(start_time, end_time)
        return self.mt5_executor.closed_position_results(start_time, end_time)

    def position_side(self, position: Any) -> str:
        if self.mode not in BROKER_MODES or self.mt5_executor is None:
            return str(position["signal"]).upper()
        return self.mt5_executor.position_side(position)

    def remaining_loss_at_stop(self, position: Any) -> float:
        if self.mode not in BROKER_MODES or self.mt5_executor is None:
            raise ExecutionError("Broker stop-risk calculation requires MT5 execution")
        return self.mt5_executor.remaining_loss_at_stop(position)

    def shutdown(self) -> None:
        if self.trade_audit is not None and self.mode in BROKER_MODES:
            try:
                self.trade_audit.sync_closed()
            except Exception:
                logger.exception("Final MT5 trade-audit synchronization failed")
        if self.mt5_executor is not None:
            self.mt5_executor.shutdown()
