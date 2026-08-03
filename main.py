"""AAQTS application entry point.

PAPER is the default execution mode. MT5_DEMO requires an explicit environment
setting, and MT5_LIVE remains blocked by :class:`ExecutionRouter`.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from bot_controller import BotController
from bot_loop import BotLoop
from config.instruments import get_instrument_spec
from config.symbols import symbol_by_data
from config.settings import (
    BOT_INTERVAL_SECONDS,
    EXECUTION_MODE,
    HIGHER_TIMEFRAME,
    MT5_MAX_OPEN_POSITIONS,
    MT5_SYMBOL_MAP,
    NEWS_CALENDAR_FILE,
    NEWS_FILTER_ENABLED,
    RISK_PERCENT,
    TRADING_TIMEFRAME,
)
from control_plane import ControlAction, ControlCommandStore, ControlRequest
from data.market_data import MarketData
from execution.execution_router import ExecutionRouter
from execution.trade_manager import TradeManager
from indicators.technical import TechnicalIndicators
from logs.logger import TradeLogger
from paper.paper_trader import PaperTrader
from risk.news_calendar import JsonNewsEventProvider
from risk.portfolio import CurrencyExposure, OpenRiskPosition
from risk.protection import (
    ClosedTradeOutcome,
    EquityPoint,
    PortfolioRiskManager,
    ProtectionConfig,
    RiskContext,
    TradeRiskRequest,
)
from risk.risk_manager import RiskManager
from runtime_state import write_runtime_state
from strategy.signal_engine import SignalEngine
from strategy.regime_router import RegimeStrategyRouter


logger = logging.getLogger(__name__)


class TradingApplication:
    """Compose market data, strategy, risk, and execution services."""

    def __init__(self) -> None:
        self.account_id = os.getenv("AAQTS_ACCOUNT_ID", "primary").strip() or "primary"
        command_root = os.getenv("AAQTS_CONTROL_QUEUE_DIR", "runtime/control").strip()
        self.control_commands = ControlCommandStore(command_root)
        self.market = MarketData()
        self.indicators = TechnicalIndicators()
        self.signal_engine = SignalEngine.production(
            higher_timeframe=HIGHER_TIMEFRAME,
            lower_timeframe=TRADING_TIMEFRAME,
        )
        self.strategy_router = RegimeStrategyRouter(
            self.signal_engine,
            higher_timeframe=HIGHER_TIMEFRAME,
            lower_timeframe=TRADING_TIMEFRAME,
        )
        self.trade_manager = TradeManager()
        self.risk_manager = RiskManager()
        self.portfolio_risk = PortfolioRiskManager(
            ProtectionConfig(
                max_daily_loss_percent=2.0,
                max_weekly_loss_percent=5.0,
                max_equity_drawdown_percent=10.0,
                max_consecutive_losses=3,
                max_open_trades=MT5_MAX_OPEN_POSITIONS,
                max_portfolio_risk_percent=3.0,
                news_filter_enabled=NEWS_FILTER_ENABLED,
                fail_closed_on_news_error=True,
            )
        )
        self.news_provider = (
            JsonNewsEventProvider(NEWS_CALENDAR_FILE) if NEWS_FILTER_ENABLED else None
        )
        self.paper_trader = PaperTrader()
        self.execution = ExecutionRouter(self.paper_trader)
        self.trade_logger = TradeLogger()
        self.equity_history: list[EquityPoint] = []
        self.latest_atr_by_symbol: dict[str, float] = {}
        self.loop = BotLoop(interval=BOT_INTERVAL_SECONDS)
        self.controller = BotController.configured(
            bot_loop=self.loop,
            execution_router=self.execution,
            callback=self.run_cycle,
        )

    def _handle_control_request(self, request: ControlRequest) -> str:
        """Apply one already-authorized Telegram command to this engine."""

        if request.account_id != self.account_id:
            raise ValueError("Control request targeted a different account")
        if request.action is ControlAction.PAUSE_ENTRIES:
            result = self.controller.pause_bot()
        elif request.action is ControlAction.RESUME_ENTRIES:
            result = self.controller.resume_bot()
        elif request.action is ControlAction.STOP_ENGINE:
            result = self.controller.stop_bot()
        elif request.action is ControlAction.EMERGENCY_CLOSE:
            closed = self.controller.emergency_stop()
            result = f"EMERGENCY STOP COMPLETED; CLOSED {len(closed)} POSITIONS"
        else:  # pragma: no cover - enum validation protects this boundary.
            raise ValueError(f"Unsupported control action: {request.action}")
        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            phase=f"CONTROL_{request.action.value}",
            last_control_request=request.request_id,
        )
        return result

    def _process_control_commands(self) -> None:
        results = self.control_commands.process_available(
            self.account_id,
            self._handle_control_request,
        )
        for request, result, success in results:
            log = logger.info if success else logger.error
            log(
                "Control request %s (%s) result: %s",
                request.request_id,
                request.action.value,
                result,
            )

    @staticmethod
    def _parse_time(value: object, fallback: datetime) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            try:
                parsed = datetime.fromtimestamp(float(value), timezone.utc)
            except (OverflowError, OSError, ValueError):
                return fallback
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _currency_exposures(
        source_symbol: str,
        direction: str,
    ) -> tuple[CurrencyExposure, ...]:
        try:
            definition = symbol_by_data(source_symbol)
            base, quote = definition.base_asset, definition.quote_asset
        except KeyError:
            return ()
        if base == quote:
            return ()
        base_direction = 1 if direction == "BUY" else -1
        return (
            CurrencyExposure(base, base_direction),
            CurrencyExposure(quote, -base_direction),
        )

    @staticmethod
    def _source_symbol(broker_symbol: str) -> str:
        normalized = str(broker_symbol).strip().upper()
        for source, broker in MT5_SYMBOL_MAP.items():
            if str(broker).strip().upper() == normalized:
                return source
        return normalized

    def _account_equity(self) -> float:
        return self.execution.account_snapshot().equity

    def _risk_context(self, decision_time: datetime) -> RiskContext:
        if self.execution.mode == "MT5_DEMO":
            return self._mt5_risk_context(decision_time)

        positions = []
        for trade in self.paper_trader.open_trades:
            try:
                instrument = get_instrument_spec(trade["symbol"])
                quantity = float(trade["position"])
                risk_amount = (
                    instrument.planned_loss_per_quantity(
                        entry_reference=trade.get(
                            "entry_reference", trade["entry"]
                        ),
                        stop_reference=trade["stop_loss"],
                        side=trade["signal"],
                    )
                    * quantity
                )
                positions.append(
                    OpenRiskPosition(
                        symbol=trade["symbol"],
                        direction=trade["signal"],
                        opened_at=self._parse_time(
                            trade.get("opened_at"), decision_time
                        ),
                        risk_amount=risk_amount,
                        quantity=quantity,
                        strategy="aaqts",
                        currency_exposures=self._currency_exposures(
                            trade["symbol"],
                            trade["signal"],
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.exception("Ignoring malformed open paper position")

        closed = []
        for trade in self.paper_trader.closed_trades:
            if "closed_at" not in trade:
                continue
            closed.append(
                ClosedTradeOutcome(
                    closed_at=self._parse_time(trade["closed_at"], decision_time),
                    profit_loss=float(trade.get("pnl", 0.0)),
                )
            )

        return RiskContext(
            open_positions=tuple(positions),
            closed_trades=tuple(closed),
            equity_history=tuple(self.equity_history),
            news_provider=self.news_provider,
        )

    def _mt5_risk_context(self, decision_time: datetime) -> RiskContext:
        """Build risk state only from the connected broker demo account."""
        equity = self._account_equity()
        positions = []
        for position in self.execution.positions():
            source_symbol = self._source_symbol(position.symbol)
            direction = self.execution.position_side(position)
            positions.append(
                OpenRiskPosition(
                    symbol=source_symbol,
                    direction=direction,
                    opened_at=self._parse_time(
                        getattr(position, "time", None),
                        decision_time,
                    ),
                    risk_amount=self.execution.remaining_loss_at_stop(position),
                    quantity=float(getattr(position, "volume", 0.0)),
                    strategy="aaqts",
                    currency_exposures=self._currency_exposures(
                        source_symbol,
                        direction,
                    ),
                )
            )

        history_start = decision_time - timedelta(days=8)
        closed = tuple(
            ClosedTradeOutcome(
                closed_at=result.closed_at,
                profit_loss=result.profit_loss,
            )
            for result in self.execution.closed_position_results(
                history_start,
                decision_time,
            )
        )
        return RiskContext(
            open_positions=tuple(positions),
            closed_trades=closed,
            equity_history=tuple(self.equity_history),
            news_provider=self.news_provider,
        )

    def _process_symbol(self, symbol, data, higher_tf) -> float:
        analyzed = self.indicators.add_indicators(data)
        signal = self.strategy_router.generate_analysis(analyzed, symbol, higher_tf)
        trade = self.trade_manager.calculate_trade(analyzed, signal)
        current_price = float(trade["current_price"])
        self.latest_atr_by_symbol[symbol] = float(trade["atr"])

        self.trade_logger.log_signal(symbol, signal["signal"], signal["confidence"])
        if self.execution.mode == "PAPER":
            self.paper_trader.check_trade(symbol, current_price)

        if signal["signal"] not in {"BUY", "SELL"}:
            return current_price

        risk_plan = self.risk_manager.calculate_trade_levels(
            signal["signal"], current_price, trade["atr"]
        )
        if not risk_plan:
            return current_price

        instrument = get_instrument_spec(symbol)
        equity = self._account_equity()
        quantity = self.risk_manager.position_size(
            equity,
            risk_plan["entry"],
            risk_plan["stop_loss"],
            instrument=instrument,
            side=signal["signal"],
            risk_multiplier=float(signal.get("risk_multiplier", 1.0)),
        )
        if quantity <= 0:
            logger.warning("Position size rejected for %s", symbol)
            return current_price

        decision_time = datetime.now(timezone.utc)
        requested_risk = (
            equity * (RISK_PERCENT / 100.0) * float(signal.get("risk_multiplier", 1.0))
        )
        assessment = self.portfolio_risk.assess(
            TradeRiskRequest(
                decision_time=decision_time,
                symbol=symbol,
                direction=signal["signal"],
                requested_quantity=quantity,
                risk_amount=requested_risk,
                equity=equity,
                volatility_ratio=float(trade["atr"]) / current_price,
                currency_exposures=self._currency_exposures(
                    symbol,
                    signal["signal"],
                ),
            ),
            self._risk_context(decision_time),
        )
        if not assessment.allowed:
            logger.warning(
                "Portfolio risk blocked %s: %s",
                symbol,
                ", ".join(assessment.reason_codes),
            )
            return current_price

        quantity = assessment.approved_quantity
        self.trade_logger.log_trade(symbol, risk_plan, quantity)
        result = self.execution.execute(
            source_symbol=symbol,
            signal=signal["signal"],
            risk_plan=risk_plan,
            paper_position_size=quantity,
        )
        logger.info("Execution result for %s: %r", symbol, result)
        return current_price

    def run_cycle(self) -> None:
        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            execution_mode=EXECUTION_MODE,
            phase="DOWNLOADING_MARKET_DATA",
            trading_timeframe=TRADING_TIMEFRAME,
            higher_timeframe=HIGHER_TIMEFRAME,
        )
        lower_frames = self.market.download_all_data(interval=TRADING_TIMEFRAME)
        higher_frames = self.market.download_all_data(interval=HIGHER_TIMEFRAME)
        prices = {}

        for symbol, data in lower_frames.items():
            if self.controller.status() != "RUNNING":
                break
            try:
                prices[symbol] = self._process_symbol(
                    symbol, data, higher_frames.get(symbol)
                )
            except Exception:
                logger.exception("Cycle failed for %s", symbol)

        if self.execution.mode == "PAPER":
            self.paper_trader.update_equity(prices)
        management = self.execution.manage_positions(self.latest_atr_by_symbol)
        if management.get("errors"):
            logger.error(
                "Position-management errors: %s",
                management["errors"],
            )
        now = datetime.now(timezone.utc)
        account = self.execution.account_snapshot()
        self.equity_history.append(EquityPoint(timestamp=now, equity=account.equity))
        self.equity_history = self.equity_history[-10_000:]
        if self.execution.mode == "PAPER":
            stats = self.paper_trader.get_stats()
            closed_trades = stats["total_trades"]
            closed_window = "all"
        else:
            stats = {
                "equity": account.equity,
                "balance": account.balance,
            }
            closed_trades = len(
                self.execution.closed_position_results(
                    now - timedelta(days=7),
                    now,
                )
            )
            closed_window = "7d"
        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            execution_mode=EXECUTION_MODE,
            phase="IDLE",
            equity=stats["equity"],
            balance=stats["balance"],
            floating_pnl=(
                stats["floating_pnl"]
                if self.execution.mode == "PAPER"
                else account.equity - account.balance
            ),
            open_positions=len(self.execution.positions()),
            closed_trades=closed_trades,
            closed_trades_window=closed_window,
            starting_balance=stats.get("starting_balance", stats["balance"]),
            wins=stats.get("wins", 0),
            win_rate=stats.get("win_rate", 0.0),
            total_pnl=stats.get("total_pnl", 0.0),
        )

    def run_forever(self) -> None:
        initial_state = {
            "account_id": self.account_id,
            "status": "STARTING",
            "execution_mode": EXECUTION_MODE,
            "phase": "STARTING",
        }
        if self.execution.mode == "PAPER":
            stats = self.paper_trader.get_stats()
            initial_state.update(
                balance=stats["balance"],
                equity=stats["equity"],
                floating_pnl=stats["floating_pnl"],
                open_positions=len(self.paper_trader.open_trades),
                starting_balance=stats["starting_balance"],
                closed_trades=stats["total_trades"],
                wins=stats["wins"],
                win_rate=stats["win_rate"],
                total_pnl=stats["total_pnl"],
            )
        write_runtime_state(
            **initial_state,
        )
        try:
            print(self.controller.start_bot())
            next_heartbeat = 0.0
            while self.controller.is_running:
                self._process_control_commands()
                now = time.monotonic()
                if now >= next_heartbeat:
                    write_runtime_state(
                        account_id=self.account_id,
                        status=self.controller.status(),
                        execution_mode=EXECUTION_MODE,
                    )
                    next_heartbeat = now + 30.0
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("AAQTS shutdown requested")
        except Exception as exc:
            write_runtime_state(
                account_id=self.account_id,
                status="ERROR",
                execution_mode=EXECUTION_MODE,
                phase="FAILED",
                error=str(exc),
            )
            raise
        finally:
            if self.controller.is_running:
                self.controller.stop_bot()
            else:
                self.execution.shutdown()
            write_runtime_state(
                account_id=self.account_id,
                status="STOPPED",
                execution_mode=EXECUTION_MODE,
                phase="SHUTDOWN",
            )


def main() -> None:
    TradingApplication().run_forever()


if __name__ == "__main__":
    main()
