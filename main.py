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
    NEWS_BLOCKED_IMPACTS,
    NEWS_CALENDAR_CACHE,
    NEWS_CALENDAR_FILE,
    NEWS_CALENDAR_URL,
    NEWS_FILTER_ENABLED,
    NEWS_MAX_STALE_MINUTES,
    NEWS_POST_EVENT_MINUTES,
    NEWS_PRE_EVENT_MINUTES,
    NEWS_REFRESH_MINUTES,
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
from risk.news_calendar import build_news_provider
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
from runtime_state import engine_instance_lock, write_runtime_state
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
                blocked_news_impacts=NEWS_BLOCKED_IMPACTS,
                news_pre_event_buffer=timedelta(minutes=NEWS_PRE_EVENT_MINUTES),
                news_post_event_buffer=timedelta(minutes=NEWS_POST_EVENT_MINUTES),
            )
        )
        self.news_provider = build_news_provider(
            enabled=NEWS_FILTER_ENABLED,
            calendar_file=NEWS_CALENDAR_FILE,
            calendar_url=NEWS_CALENDAR_URL,
            cache_path=NEWS_CALENDAR_CACHE,
            refresh_minutes=NEWS_REFRESH_MINUTES,
            max_stale_minutes=NEWS_MAX_STALE_MINUTES,
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
        else:
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
                closed_at=item.closed_at,
                profit_loss=item.profit_loss,
            )
            for item in self.execution.closed_position_results(
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

    def _record_equity(self, decision_time: datetime) -> float:
        equity = self._account_equity()
        point = EquityPoint(decision_time, equity)
        if not self.equity_history or self.equity_history[-1] != point:
            self.equity_history.append(point)
            if len(self.equity_history) > 5000:
                self.equity_history = self.equity_history[-5000:]
        return equity

    def run_cycle(self) -> None:
        """Run one complete closed-candle trading cycle."""
        self._process_control_commands()
        now = datetime.now(timezone.utc)
        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            phase="CYCLE_START",
            cycle_started_at=now.isoformat(),
        )
        try:
            equity = self._record_equity(now)
            atr_by_source: dict[str, float] = {}
            for category, symbols in __import__("config.settings", fromlist=["SYMBOLS"]).SYMBOLS.items():
                for symbol in symbols:
                    self._process_symbol(symbol, category, now, equity, atr_by_source)
            self.latest_atr_by_symbol = atr_by_source
            management = self.execution.manage_positions(atr_by_source)
            if management.get("errors"):
                logger.warning("Position management errors: %s", management["errors"])
            write_runtime_state(
                account_id=self.account_id,
                status=self.controller.status(),
                phase="CYCLE_COMPLETE",
                cycle_completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            write_runtime_state(
                account_id=self.account_id,
                status=self.controller.status(),
                phase="CYCLE_ERROR",
                error=str(exc),
            )
            raise

    def _process_symbol(
        self,
        symbol: str,
        category: str,
        decision_time: datetime,
        equity: float,
        atr_by_source: dict[str, float],
    ) -> None:
        lower = self.market.download_data(symbol, TRADING_TIMEFRAME, as_of=decision_time)
        higher = self.market.download_data(symbol, HIGHER_TIMEFRAME, as_of=decision_time)
        lower = self.indicators.calculate_all(lower)
        higher = self.indicators.calculate_all(higher)
        analysis = self.strategy_router.generate_analysis(lower, symbol, higher)
        signal = analysis.get("signal", "HOLD")
        confidence = analysis.get("confidence", 0)
        self.trade_logger.log_signal(symbol, signal, confidence)
        latest = lower.iloc[-1]
        atr = float(latest.get("ATR", 0.0) or 0.0)
        if atr > 0:
            atr_by_source[symbol] = atr
        if signal not in {"BUY", "SELL"}:
            return

        trade = self.trade_manager.prepare_trade(lower, signal)
        if not trade:
            logger.info("%s qualified signal had no valid trade plan", symbol)
            return

        paper_position = self.risk_manager.calculate_position_size(
            entry=trade["entry"],
            stop_loss=trade["stop_loss"],
            account_balance=equity,
            risk_percent=RISK_PERCENT,
            symbol=symbol,
        )
        requested_risk = equity * (RISK_PERCENT / 100.0)
        if EXECUTION_MODE == "MT5_DEMO":
            # Quantity is deliberately a positive placeholder in broker mode;
            # the executor sizes the final lot from approved dollar risk using
            # broker-native symbol contract metadata.
            requested_quantity = max(float(paper_position or 0.0), 1.0)
        else:
            if paper_position is None or paper_position <= 0:
                logger.info("%s position size rejected", symbol)
                return
            requested_quantity = float(paper_position)

        assessment = self.portfolio_risk.assess(
            TradeRiskRequest(
                decision_time=decision_time,
                symbol=symbol,
                direction=signal,
                requested_quantity=requested_quantity,
                risk_amount=requested_risk,
                equity=equity,
                asset_class=category,
                currency_exposures=self._currency_exposures(symbol, signal),
            ),
            self._risk_context(decision_time),
        )
        if not assessment.allowed:
            logger.info(
                "%s risk blocked %s: %s",
                symbol,
                signal,
                ",".join(assessment.reason_codes),
            )
            return

        result = self.execution.execute(
            source_symbol=symbol,
            signal=signal,
            risk_plan=trade,
            paper_position_size=assessment.approved_quantity,
            approved_risk_amount=assessment.approved_risk_amount,
        )
        self.trade_logger.log_trade(symbol, trade, result)

    def _run_forever_locked(self) -> None:
        write_runtime_state(
            account_id=self.account_id,
            status="STARTING",
            phase="ENGINE_STARTING",
            execution_mode=EXECUTION_MODE,
            news_filter_enabled=NEWS_FILTER_ENABLED,
        )
        print(self.controller.start_bot())
        try:
            while self.controller.status() != "STOPPED":
                self._process_control_commands()
                time.sleep(1.0)
        finally:
            self.controller.shutdown()
            write_runtime_state(
                account_id=self.account_id,
                status="STOPPED",
                phase="ENGINE_STOPPED",
            )

    def run_forever(self) -> None:
        """Own the single-engine lock for this account until shutdown."""
        with engine_instance_lock(self.account_id):
            self._run_forever_locked()


def main() -> None:
    TradingApplication().run_forever()


if __name__ == "__main__":
    main()
