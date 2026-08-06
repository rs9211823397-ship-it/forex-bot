"""Route validated trade plans to paper or MT5 demo execution.

The router keeps strategy code independent from the execution venue. PAPER is
always the default. MT5_LIVE is deliberately rejected until a separate live
release gate exists.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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
    MT5_SYMBOL_MAP,
    MT5_SYMBOL_SUFFIX,
    MT5_TERMINAL_PATH,
)
from config.symbols import executable_symbol_map
from execution.mt5_executor import (
    AccountSnapshot,
    ClosedPositionResult,
    ExecutionConfig,
    ExecutionError,
    MT5Executor,
)
from execution.mt5_trade_audit import MT5TradeAudit
from execution.position_manager import PositionManager


logger = logging.getLogger(__name__)
VALID_MODES = {"PAPER", "MT5_DEMO", "MT5_LIVE"}


def _position_management_symbol_map() -> dict[str, str]:
    """Return the full broker map used only for already-open position care.

    New entries intentionally use the filtered ``MT5_SYMBOL_MAP``. Position
    management must not use that filter: disabling a symbol for new entries
    must never stop break-even/trailing/exit management for a position that was
    opened before the symbol was disabled.
    """

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
    ) -> None:
        self.paper_trader = paper_trader
        self.mode = mode.upper().strip()
        if self.mode not in VALID_MODES:
            raise ValueError(f"Unsupported execution mode: {self.mode}")
        if self.mode == "MT5_LIVE":
            raise ExecutionError(
                "MT5_LIVE is locked. Use PAPER or MT5_DEMO until the live-release gate is implemented."
            )

        self.mt5_executor = mt5_executor
        if self.mode == "MT5_DEMO" and self.mt5_executor is None:
            self.mt5_executor = MT5Executor(
                ExecutionConfig(
                    terminal_path=MT5_TERMINAL_PATH,
                    login=int(MT5_LOGIN) if MT5_LOGIN else None,
                    expected_login=(int(MT5_EXPECTED_LOGIN) if MT5_EXPECTED_LOGIN else None),
                    password=MT5_PASSWORD,
                    server=MT5_SERVER,
                    max_open_positions=MT5_MAX_OPEN_POSITIONS,
                    max_tick_age_seconds=MT5_MAX_TICK_AGE_SECONDS,
                    max_spread_stop_ratio=MT5_MAX_SPREAD_STOP_RATIO,
                )
            )
        self.position_manager = position_manager
        if self.mode == "MT5_DEMO" and self.position_manager is None:
            assert self.mt5_executor is not None
            self.position_manager = PositionManager(self.mt5_executor)

        self.trade_audit = trade_audit
        if self.mode == "MT5_DEMO" and self.trade_audit is None:
            assert self.mt5_executor is not None
            mt5_api = getattr(self.mt5_executor, "mt5", None)
            config = getattr(self.mt5_executor, "config", None)
            if mt5_api is not None and config is not None and hasattr(mt5_api, "history_deals_get"):
                self.trade_audit = MT5TradeAudit(self.mt5_executor)

    def start(self) -> list[Any]:
        if self.mode != "MT5_DEMO":
            return []
        assert self.mt5_executor is not None
        assert self.position_manager is not None
        self.mt5_executor.connect()
        recovered = self.position_manager.recover_positions(reset_registry=True)
        if self.trade_audit is not None:
            self.trade_audit.sync_closed()
        return recovered

    def _validate_entry_quote(self, mt5_symbol: str, risk_plan: dict[str, float]) -> None:
        """Fail closed on stale executable ticks or spread disproportionate to risk."""
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

    def execute(self, source_symbol: str, signal: str, risk_plan: dict[str, float], paper_position_size: float, approved_risk_amount: Optional[float] = None) -> Any:
        if not risk_plan:
            raise ValueError("risk_plan is required")
        required = {"entry", "stop_loss", "take_profit"}
        missing = required.difference(risk_plan)
        if missing:
            raise ValueError("risk_plan is missing: " + ", ".join(sorted(missing)))
        side = signal.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Only BUY or SELL signals can be executed")
        if self.mode == "PAPER":
            return self.paper_trader.open_trade(source_symbol, side, risk_plan["entry"], risk_plan["stop_loss"], risk_plan["take_profit"], paper_position_size)

        assert self.mt5_executor is not None
        mt5_symbol = MT5_SYMBOL_MAP.get(source_symbol)
        if not mt5_symbol:
            raise ExecutionError(f"No MT5 symbol mapping configured for {source_symbol}")
        if approved_risk_amount is None or approved_risk_amount <= 0:
            raise ExecutionError("MT5_DEMO requires a positive portfolio-approved risk amount")
        self._validate_entry_quote(mt5_symbol, risk_plan)
        result = self.mt5_executor.place_market_order(
            symbol=mt5_symbol, side=side, volume=None,
            stop_loss=risk_plan["stop_loss"], take_profit=risk_plan["take_profit"],
            comment=f"AAQTS {source_symbol}", reference_entry=risk_plan["entry"],
            risk_amount=approved_risk_amount,
        )
        managed = None
        if self.position_manager is not None:
            managed = self.position_manager.register_execution_result(result)
        if self.trade_audit is not None:
            self.trade_audit.record_entry(source_symbol=source_symbol, side=side, risk_plan=risk_plan, result=result, managed_position=managed)
        return result

    def manage_positions(self, atr_by_source_symbol: Optional[dict[str, float]] = None) -> dict[str, Any]:
        if self.mode != "MT5_DEMO" or self.position_manager is None:
            return {"managed": False, "reason": "paper_mode_uses_price_checks", "reports": [], "errors": []}
        atr_by_source_symbol = atr_by_source_symbol or {}
        management_map = _position_management_symbol_map()
        broker_atr = {
            management_map[source]: float(atr)
            for source, atr in atr_by_source_symbol.items()
            if source in management_map
        }
        report = self.position_manager.manage_positions(broker_atr, force_sync=False)
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
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return []
        results = self.mt5_executor.emergency_stop()
        if self.trade_audit is not None:
            self.trade_audit.sync_closed()
        return results

    def positions(self) -> list[Any]:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return list(getattr(self.paper_trader, "open_trades", []))
        return self.mt5_executor.positions(managed_only=True)

    def account_snapshot(self) -> AccountSnapshot:
        if self.mode == "PAPER":
            return AccountSnapshot(balance=float(self.paper_trader.balance), equity=float(self.paper_trader.equity))
        assert self.mt5_executor is not None
        return self.mt5_executor.account_snapshot()

    def closed_position_results(self, start_time: datetime, end_time: datetime) -> list[ClosedPositionResult]:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return []
        if self.trade_audit is not None:
            return self.trade_audit.closed_position_results(start_time, end_time)
        return self.mt5_executor.closed_position_results(start_time, end_time)

    def position_side(self, position: Any) -> str:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return str(position["signal"]).upper()
        return self.mt5_executor.position_side(position)

    def remaining_loss_at_stop(self, position: Any) -> float:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            raise ExecutionError("Broker stop-risk calculation requires MT5_DEMO")
        return self.mt5_executor.remaining_loss_at_stop(position)

    def shutdown(self) -> None:
        if self.trade_audit is not None and self.mode == "MT5_DEMO":
            try:
                self.trade_audit.sync_closed()
            except Exception:
                logger.exception("Final MT5 trade-audit synchronization failed")
        if self.mt5_executor is not None:
            self.mt5_executor.shutdown()
