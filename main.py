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
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_LOSS_PERCENT,
    MAX_EQUITY_DRAWDOWN_PERCENT,
    MAX_PORTFOLIO_RISK_PERCENT,
    MAX_WEEKLY_LOSS_PERCENT,
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
    PORTFOLIO_MAX_ABS_CORRELATION,
    PORTFOLIO_MAX_CORRELATED_RISK_PERCENT,
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
from risk.portfolio import CorrelationObservation, CurrencyExposure, OpenRiskPosition
from risk.protection import ClosedTradeOutcome, EquityPoint, PortfolioRiskManager, ProtectionConfig, RiskContext, TradeRiskRequest
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
        self.signal_engine = SignalEngine.production(higher_timeframe=HIGHER_TIMEFRAME, lower_timeframe=TRADING_TIMEFRAME)
        self.strategy_router = RegimeStrategyRouter(self.signal_engine, higher_timeframe=HIGHER_TIMEFRAME, lower_timeframe=TRADING_TIMEFRAME)
        self.trade_manager = TradeManager()
        self.risk_manager = RiskManager()
        self.portfolio_risk = PortfolioRiskManager(
            ProtectionConfig(
                max_daily_loss_percent=MAX_DAILY_LOSS_PERCENT,
                max_weekly_loss_percent=MAX_WEEKLY_LOSS_PERCENT,
                max_equity_drawdown_percent=MAX_EQUITY_DRAWDOWN_PERCENT,
                max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
                max_open_trades=MT5_MAX_OPEN_POSITIONS,
                max_portfolio_risk_percent=MAX_PORTFOLIO_RISK_PERCENT,
                max_abs_correlation=PORTFOLIO_MAX_ABS_CORRELATION,
                max_correlated_risk_percent=PORTFOLIO_MAX_CORRELATED_RISK_PERCENT,
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
        self.latest_correlations: tuple[CorrelationObservation, ...] = ()
        self.loop = BotLoop(interval=BOT_INTERVAL_SECONDS)
        self.controller = BotController.configured(bot_loop=self.loop, execution_router=self.execution, callback=self.run_cycle)

    def _handle_control_request(self, request: ControlRequest) -> str:
        if request.account_id != self.account_id:
            raise ValueError("Control request targeted a different account")
        if request.action is ControlAction.PAUSE_ENTRIES:
            result = self.controller.pause_bot()
        elif request.action is ControlAction.RESUME_ENTRIES:
            result = self.controller.resume_bot()
        elif request.action is ControlAction.STOP_ENGINE:
            result = self.controller.stop_bot()
        elif request.action is ControlAction.EMERGENCY_CLOSE:
            closed = self.controller.emergency_stop(); result = f"EMERGENCY STOP COMPLETED; CLOSED {len(closed)} POSITIONS"
        else:
            raise ValueError(f"Unsupported control action: {request.action}")
        write_runtime_state(account_id=self.account_id, status=self.controller.status(), phase=f"CONTROL_{request.action.value}", last_control_request=request.request_id)
        return result

    def _process_control_commands(self) -> None:
        results = self.control_commands.process_available(self.account_id, self._handle_control_request)
        for request, result, success in results:
            (logger.info if success else logger.error)("Control request %s (%s) result: %s", request.request_id, request.action.value, result)

    @staticmethod
    def _parse_time(value: object, fallback: datetime) -> datetime:
        if isinstance(value, datetime): parsed = value
        elif isinstance(value, (int, float)):
            try: parsed = datetime.fromtimestamp(float(value), timezone.utc)
            except (OverflowError, OSError, ValueError): return fallback
        else:
            try: parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError): return fallback
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _currency_exposures(source_symbol: str, direction: str) -> tuple[CurrencyExposure, ...]:
        try: definition = symbol_by_data(source_symbol); base, quote = definition.base_asset, definition.quote_asset
        except KeyError: return ()
        if base == quote: return ()
        base_direction = 1 if direction == "BUY" else -1
        return (CurrencyExposure(base, base_direction), CurrencyExposure(quote, -base_direction))

    @staticmethod
    def _source_symbol(broker_symbol: str) -> str:
        normalized = str(broker_symbol).strip().upper()
        for source, broker in MT5_SYMBOL_MAP.items():
            if str(broker).strip().upper() == normalized: return source
        return normalized

    @staticmethod
    def _frame_is_demo_safe(frame) -> bool:
        return bool(frame is not None and not getattr(frame, "empty", True) and getattr(frame, "attrs", {}).get("source") == "MT5" and getattr(frame, "attrs", {}).get("fresh") is True)

    @staticmethod
    def _build_correlations(frames: dict[str, object], observed_at: datetime) -> tuple[CorrelationObservation, ...]:
        symbols = sorted(frames); observations: list[CorrelationObservation] = []
        for index, first in enumerate(symbols):
            first_frame = frames[first]
            if getattr(first_frame, "empty", True) or "close" not in first_frame: continue
            first_returns = first_frame["close"].astype(float).pct_change().dropna().tail(120)
            for second in symbols[index + 1:]:
                second_frame = frames[second]
                if getattr(second_frame, "empty", True) or "close" not in second_frame: continue
                second_returns = second_frame["close"].astype(float).pct_change().dropna().tail(120)
                aligned = first_returns.to_frame("first").join(second_returns.to_frame("second"), how="inner").dropna()
                if len(aligned) < 30: continue
                value = float(aligned["first"].corr(aligned["second"]))
                if value != value: continue
                observations.append(CorrelationObservation(first_symbol=first, second_symbol=second, observed_at=observed_at, correlation=max(-1.0, min(1.0, value))))
        return tuple(observations)

    def _account_equity(self) -> float:
        return self.execution.account_snapshot().equity

    def _risk_context(self, decision_time: datetime) -> RiskContext:
        if self.execution.mode == "MT5_DEMO": return self._mt5_risk_context(decision_time)
        positions = []
        for trade in self.paper_trader.open_trades:
            try:
                instrument = get_instrument_spec(trade["symbol"]); quantity = float(trade["position"])
                risk_amount = instrument.planned_loss_per_quantity(entry_reference=trade.get("entry_reference", trade["entry"]), stop_reference=trade["stop_loss"], side=trade["signal"]) * quantity
                positions.append(OpenRiskPosition(symbol=trade["symbol"], direction=trade["signal"], opened_at=self._parse_time(trade.get("opened_at"), decision_time), risk_amount=risk_amount, quantity=quantity, strategy="aaqts", currency_exposures=self._currency_exposures(trade["symbol"], trade["signal"])))
            except (KeyError, TypeError, ValueError): logger.exception("Ignoring malformed open paper position")
        closed = []
        for trade in self.paper_trader.closed_trades:
            if "closed_at" not in trade: continue
            closed.append(ClosedTradeOutcome(closed_at=self._parse_time(trade["closed_at"], decision_time), profit_loss=float(trade.get("pnl", 0.0))))
        return RiskContext(open_positions=tuple(positions), closed_trades=tuple(closed), equity_history=tuple(self.equity_history), correlations=self.latest_correlations, news_provider=self.news_provider)

    def _mt5_risk_context(self, decision_time: datetime) -> RiskContext:
        positions = []
        for position in self.execution.positions():
            source_symbol = self._source_symbol(position.symbol); direction = self.execution.position_side(position)
            positions.append(OpenRiskPosition(symbol=source_symbol, direction=direction, opened_at=self._parse_time(getattr(position, "time", None), decision_time), risk_amount=self.execution.remaining_loss_at_stop(position), quantity=float(getattr(position, "volume", 0.0)), strategy="aaqts", currency_exposures=self._currency_exposures(source_symbol, direction)))
        history_start = decision_time - timedelta(days=8)
        closed = tuple(ClosedTradeOutcome(closed_at=result.closed_at, profit_loss=result.profit_loss) for result in self.execution.closed_position_results(history_start, decision_time))
        return RiskContext(open_positions=tuple(positions), closed_trades=closed, equity_history=tuple(self.equity_history), correlations=self.latest_correlations, news_provider=self.news_provider)

    def _process_symbol(self, symbol, data, higher_tf) -> float:
        if self.execution.mode == "MT5_DEMO":
            if not self._frame_is_demo_safe(data): raise RuntimeError(f"Unsafe/stale lower-timeframe data blocked for {symbol}")
            if not self._frame_is_demo_safe(higher_tf): raise RuntimeError(f"Unsafe/stale higher-timeframe data blocked for {symbol}")
        analyzed = self.indicators.add_indicators(data)
        signal = self.strategy_router.generate_analysis(analyzed, symbol, higher_tf)
        trade = self.trade_manager.calculate_trade(analyzed, signal)
        current_price = float(trade["current_price"]); self.latest_atr_by_symbol[symbol] = float(trade["atr"])
        self.trade_logger.log_signal(symbol, signal["signal"], signal["confidence"])
        if self.execution.mode == "PAPER": self.paper_trader.check_trade(symbol, current_price)
        if signal["signal"] not in {"BUY", "SELL"}: return current_price
        risk_plan = self.risk_manager.calculate_trade_levels(signal["signal"], current_price, trade["atr"])
        if not risk_plan: return current_price
        equity = self._account_equity(); risk_multiplier = float(signal.get("risk_multiplier", 1.0)); requested_risk = equity * (RISK_PERCENT / 100.0) * risk_multiplier
        if self.execution.mode == "PAPER":
            instrument = get_instrument_spec(symbol)
            requested_quantity = self.risk_manager.position_size(equity, risk_plan["entry"], risk_plan["stop_loss"], instrument=instrument, side=signal["signal"], risk_multiplier=risk_multiplier)
            if requested_quantity <= 0:
                logger.warning("Paper position size rejected for %s (equity=%.2f requested_risk=%.2f)", symbol, equity, requested_risk); return current_price
        else: requested_quantity = 1.0
        decision_time = datetime.now(timezone.utc)
        assessment = self.portfolio_risk.assess(TradeRiskRequest(decision_time=decision_time, symbol=symbol, direction=signal["signal"], requested_quantity=requested_quantity, risk_amount=requested_risk, equity=equity, volatility_ratio=float(trade["atr"]) / current_price, currency_exposures=self._currency_exposures(symbol, signal["signal"])), self._risk_context(decision_time))
        if not assessment.allowed:
            logger.warning("Portfolio risk blocked %s: %s", symbol, ", ".join(assessment.reason_codes)); return current_price
        if self.execution.mode == "PAPER": approved_quantity = assessment.approved_quantity; self.trade_logger.log_trade(symbol, risk_plan, approved_quantity)
        else: approved_quantity = requested_quantity; logger.info("MT5 broker sizing approved for %s: risk_amount=%.2f portfolio_action=%s", symbol, assessment.approved_risk_amount, assessment.action.value)
        result = self.execution.execute(source_symbol=symbol, signal=signal["signal"], risk_plan=risk_plan, paper_position_size=approved_quantity, approved_risk_amount=assessment.approved_risk_amount)
        logger.info("Execution result for %s: %r", symbol, result)
        return current_price

    def run_cycle(self) -> None:
        self.latest_atr_by_symbol = {}
        write_runtime_state(account_id=self.account_id, status=self.controller.status(), execution_mode=EXECUTION_MODE, phase="DOWNLOADING_MARKET_DATA", trading_timeframe=TRADING_TIMEFRAME, higher_timeframe=HIGHER_TIMEFRAME, market_data_provider=self.market.provider)
        lower_frames = self.market.download_all_data(interval=TRADING_TIMEFRAME); higher_frames = self.market.download_all_data(interval=HIGHER_TIMEFRAME)
        observed_at = datetime.now(timezone.utc); self.latest_correlations = self._build_correlations(lower_frames, observed_at); prices = {}
        expected = set(MT5_SYMBOL_MAP) if self.execution.mode == "MT5_DEMO" else set(lower_frames)
        missing_lower = sorted(expected.difference(lower_frames)); missing_higher = sorted(expected.difference(higher_frames))
        if self.execution.mode == "MT5_DEMO" and (missing_lower or missing_higher): logger.error("Demo data health degraded; affected symbols will fail closed | lower=%s higher=%s", missing_lower, missing_higher)
        for symbol, data in lower_frames.items():
            if self.controller.status() != "RUNNING": break
            if self.execution.mode == "MT5_DEMO" and symbol not in higher_frames:
                logger.error("Skipping %s: required higher-timeframe data unavailable", symbol); continue
            try: prices[symbol] = self._process_symbol(symbol, data, higher_frames.get(symbol))
            except Exception: logger.exception("Cycle failed for %s", symbol)
        if self.execution.mode == "PAPER": self.paper_trader.update_equity(prices)
        management = self.execution.manage_positions(self.latest_atr_by_symbol)
        if management.get("errors"): logger.error("Position-management errors: %s", management["errors"])
        now = datetime.now(timezone.utc); account = self.execution.account_snapshot(); self.equity_history.append(EquityPoint(timestamp=now, equity=account.equity)); self.equity_history = self.equity_history[-10_000:]
        if self.execution.mode == "PAPER": stats = self.paper_trader.get_stats(); closed_trades = stats["total_trades"]; closed_window = "all"
        else: stats = {"equity": account.equity, "balance": account.balance}; closed_trades = len(self.execution.closed_position_results(now - timedelta(days=7), now)); closed_window = "7d"
        write_runtime_state(account_id=self.account_id, status=self.controller.status(), execution_mode=EXECUTION_MODE, phase="IDLE", market_data_provider=self.market.provider, market_data_healthy=not (missing_lower or missing_higher), missing_lower_symbols=missing_lower, missing_higher_symbols=missing_higher, correlation_observations=len(self.latest_correlations), equity=stats["equity"], balance=stats["balance"], floating_pnl=(stats["floating_pnl"] if self.execution.mode == "PAPER" else account.equity - account.balance), open_positions=len(self.execution.positions()), closed_trades=closed_trades, closed_trades_window=closed_window, starting_balance=stats.get("starting_balance", stats["balance"]), wins=stats.get("wins", 0), losses=stats.get("losses", 0))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    app = TradingApplication()
    with engine_instance_lock(app.account_id):
        try:
            app.controller.start_bot()
            while app.controller.status() != "STOPPED": app._process_control_commands(); time.sleep(0.5)
        except KeyboardInterrupt: logger.info("AAQTS shutdown requested")
        finally: app.controller.stop_bot()


if __name__ == "__main__": main()
