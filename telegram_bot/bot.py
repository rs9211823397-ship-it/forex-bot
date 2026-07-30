import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Ensure project root is importable when this file is run directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import EXECUTION_MODE, MT5_TERMINAL_PATH
from execution.mt5_executor import AAQTS_MAGIC
from paper.paper_trader import PaperTrader
from runtime_state import heartbeat_is_fresh, read_runtime_state
from telegram_bot.alert_monitor import (
    TradeAlertMonitor,
    is_subscribed,
    subscribe,
    unsubscribe,
)
from telegram_bot.dashboard import format_dashboard, mt5_dashboard_snapshot


load_dotenv(PROJECT_ROOT / ".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("aaqts.telegram")
paper_trader = PaperTrader()


def money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def runtime_status() -> tuple[str, dict[str, Any]]:
    state = read_runtime_state()
    if heartbeat_is_fresh(state):
        return str(state.get("status", "RUNNING")), state
    if state.get("status") == "STOPPED":
        return "STOPPED", state
    return "STOPPED (no recent heartbeat)", state


def mt5_snapshot() -> dict[str, Any]:
    """Read live account and AAQTS-managed positions directly from MT5."""
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("MetaTrader5 package is not installed.") from exc

    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")

    try:
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("MT5 account information is unavailable.")

        positions = [
            position
            for position in list(mt5.positions_get() or [])
            if getattr(position, "magic", None) == AAQTS_MAGIC
        ]
        return {
            "login": getattr(account, "login", None),
            "server": getattr(account, "server", "Unknown"),
            "balance": float(getattr(account, "balance", 0.0)),
            "equity": float(getattr(account, "equity", 0.0)),
            "profit": float(getattr(account, "profit", 0.0)),
            "margin": float(getattr(account, "margin", 0.0)),
            "margin_free": float(getattr(account, "margin_free", 0.0)),
            "positions": positions,
        }
    finally:
        mt5.shutdown()


def paper_snapshot() -> dict[str, Any]:
    paper_trader.load_trades()
    stats = paper_trader.get_stats()
    return {
        "balance": stats["balance"],
        "equity": stats["equity"],
        "profit": stats["floating_pnl"],
        "positions": paper_trader.open_trades,
        "stats": stats,
    }


def account_snapshot() -> dict[str, Any]:
    if EXECUTION_MODE == "MT5_DEMO":
        return mt5_snapshot()
    return paper_snapshot()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        subscribe(update.effective_chat.id)
    text = (
        "🤖 AAQTS TRADING MANAGER\n\n"
        "Advanced AI Quant Trading System\n\n"
        "✅ Automatic trade alerts are enabled for this chat.\n\n"
        "Available commands:\n"
        "/status - Live engine status\n"
        "/dashboard - Complete live performance dashboard\n"
        "/balance - Live account balance\n"
        "/equity - Live equity and floating P/L\n"
        "/positions - AAQTS open positions\n"
        "/profit - Current trading performance\n"
        "/analysis - Run market analysis\n"
        "/alerts - Alert subscription status\n"
        "/alerts_on - Enable automatic alerts\n"
        "/alerts_off - Disable automatic alerts\n"
        "/help - Show commands"
    )
    if update.message:
        await update.message.reply_text(text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    enabled = is_subscribed(update.effective_chat.id)
    state = "ENABLED ✅" if enabled else "DISABLED ❌"
    await update.message.reply_text(
        "🔔 AAQTS AUTOMATIC ALERTS\n\n"
        f"Status: {state}\n"
        "Includes: trade opened, trade closed, SL/TP reason and daily UTC summary."
    )


async def alerts_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    subscribe(update.effective_chat.id)
    await update.message.reply_text(
        "🔔 Automatic AAQTS alerts enabled.\n\n"
        "You will receive trade-open, trade-close and daily-summary notifications."
    )


async def alerts_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    unsubscribe(update.effective_chat.id)
    await update.message.reply_text("🔕 Automatic AAQTS alerts disabled for this chat.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    status, state = runtime_status()
    phase = state.get("phase", "Unknown")
    mode = state.get("execution_mode", EXECUTION_MODE)
    scanned = state.get("scanned_symbols", 0)
    total = state.get("total_symbols", 0)
    current_symbol = state.get("current_symbol") or "None"
    heartbeat = state.get("heartbeat_utc", "No heartbeat")

    text = (
        "⚙️ AAQTS LIVE STATUS\n\n"
        f"Bot status: {status}\n"
        f"Execution mode: {mode}\n"
        f"Phase: {phase}\n"
        f"Scan progress: {scanned}/{total}\n"
        f"Current symbol: {current_symbol}\n"
        f"Heartbeat (UTC): {heartbeat}"
    )
    await update.message.reply_text(text)


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        snapshot = await asyncio.to_thread(mt5_dashboard_snapshot)
        await update.message.reply_text(format_dashboard(snapshot))
    except Exception as exc:
        logger.exception("Dashboard command failed")
        await update.message.reply_text(f"❌ Could not build live dashboard.\n\n{exc}")


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        snapshot = await asyncio.to_thread(account_snapshot)
        label = "MT5 DEMO ACCOUNT" if EXECUTION_MODE == "MT5_DEMO" else "PAPER ACCOUNT"
        await update.message.reply_text(
            f"💰 {label}\n\n"
            f"Balance: {money(snapshot['balance'])}\n"
            f"Mode: {EXECUTION_MODE}"
        )
    except Exception as exc:
        logger.exception("Balance command failed")
        await update.message.reply_text(f"❌ Could not read account balance.\n\n{exc}")


async def equity_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        snapshot = await asyncio.to_thread(account_snapshot)
        await update.message.reply_text(
            "📊 LIVE ACCOUNT EQUITY\n\n"
            f"Balance: {money(snapshot['balance'])}\n"
            f"Floating P/L: {money(snapshot['profit'])}\n"
            f"Equity: {money(snapshot['equity'])}"
        )
    except Exception as exc:
        logger.exception("Equity command failed")
        await update.message.reply_text(f"❌ Could not read account equity.\n\n{exc}")


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        snapshot = await asyncio.to_thread(account_snapshot)
        positions = snapshot["positions"]
    except Exception as exc:
        logger.exception("Positions command failed")
        await update.message.reply_text(f"❌ Could not read positions.\n\n{exc}")
        return

    if not positions:
        await update.message.reply_text("📭 OPEN POSITIONS\n\nNo AAQTS positions are open.")
        return

    lines = ["📈 AAQTS OPEN POSITIONS", ""]
    if EXECUTION_MODE == "MT5_DEMO":
        for index, position in enumerate(positions, start=1):
            side = "BUY" if getattr(position, "type", 0) == 0 else "SELL"
            lines.extend([
                f"{index}. {getattr(position, 'symbol', 'Unknown')} | {side}",
                f"Ticket: {getattr(position, 'ticket', 'N/A')}",
                f"Volume: {getattr(position, 'volume', 'N/A')}",
                f"Entry: {getattr(position, 'price_open', 'N/A')}",
                f"Current: {getattr(position, 'price_current', 'N/A')}",
                f"P/L: {money(getattr(position, 'profit', 0.0))}",
                f"SL: {getattr(position, 'sl', 'N/A')}",
                f"TP: {getattr(position, 'tp', 'N/A')}",
                "",
            ])
    else:
        for index, trade in enumerate(positions, start=1):
            lines.extend([
                f"{index}. {trade.get('symbol', 'Unknown')} | {trade.get('signal', 'Unknown')}",
                f"Entry: {trade.get('entry', 'N/A')}",
                f"SL: {trade.get('stop_loss', 'N/A')}",
                f"TP: {trade.get('take_profit', 'N/A')}",
                "",
            ])

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        await update.message.reply_text(text[start:start + 3900])


async def profit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        snapshot = await asyncio.to_thread(account_snapshot)
        positions = snapshot["positions"]
        if EXECUTION_MODE == "MT5_DEMO":
            managed_profit = sum(float(getattr(p, "profit", 0.0)) for p in positions)
            text = (
                "📈 LIVE MT5 PERFORMANCE\n\n"
                f"AAQTS open positions: {len(positions)}\n"
                f"AAQTS floating P/L: {money(managed_profit)}\n"
                f"Account floating P/L: {money(snapshot['profit'])}\n"
                f"Equity: {money(snapshot['equity'])}"
            )
        else:
            stats = snapshot["stats"]
            text = (
                "📈 PAPER PERFORMANCE\n\n"
                f"Closed trades: {stats['total_trades']}\n"
                f"Wins: {stats['wins']}\n"
                f"Win rate: {stats['win_rate']}%\n"
                f"Net P/L: {money(stats['total_pnl'])}"
            )
        await update.message.reply_text(text)
    except Exception as exc:
        logger.exception("Profit command failed")
        await update.message.reply_text(f"❌ Could not read performance.\n\n{exc}")


def run_analysis_sync() -> str:
    from config.settings import HIGHER_TIMEFRAME, TRADING_TIMEFRAME
    from data.market_data import MarketData
    from indicators.technical import TechnicalIndicators
    from strategy.signal_engine import SignalEngine

    market = MarketData()
    indicator = TechnicalIndicators()
    signal_engine = SignalEngine()
    all_data = market.download_all_data(interval=TRADING_TIMEFRAME)
    higher_tf_data = market.download_all_data(interval=HIGHER_TIMEFRAME)
    results = []

    for symbol, data in all_data.items():
        try:
            analyzed_data = indicator.add_indicators(data)
            signal = signal_engine.generate_signal(
                analyzed_data, symbol, higher_tf_data.get(symbol)
            )
            results.append({
                "symbol": symbol,
                "signal": signal.get("signal", "HOLD"),
                "confidence": signal.get("confidence", 0),
                "reasons": signal.get("reasons", []),
                "decision_report": signal.get("decision_report", {}),
            })
        except Exception as exc:
            logger.exception("Analysis failed for %s", symbol)
            results.append({
                "symbol": symbol,
                "signal": "ERROR",
                "confidence": 0,
                "reasons": [str(exc)],
                "decision_report": {
                    "decision": "ERROR",
                    "status": "REJECTED",
                    "approved": False,
                    "confidence": 0,
                    "score": 0,
                    "reasons": [str(exc)],
                    "decision_summary": {"positive": [], "warnings": [str(exc)]},
                    "rejection_reasons": [str(exc)],
                    "report_text": f"Decision: ERROR\nStatus: REJECTED\nConfidence: 0%\nScore: 0\nRejection reasons:\n- {exc}",
                },
            })

    if not results:
        return "No market data was returned."

    lines = ["🧠 AAQTS MARKET ANALYSIS", ""]
    for result in results:
        lines.append(
            f"{result['symbol']} | {result['signal']} | {result['confidence']}%"
        )
        decision_report = result.get("decision_report") or {}
        if decision_report.get("report_text"):
            lines.append(decision_report["report_text"])
        for reason in result["reasons"][:2]:
            lines.append(f"• {reason}")
        lines.append("")
    return "\n".join(lines)


async def analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("🔍 Running AAQTS market analysis. Please wait...")
    try:
        result = await asyncio.to_thread(run_analysis_sync)
        for start in range(0, len(result), 3900):
            await update.message.reply_text(result[start:start + 3900])
    except Exception as exc:
        logger.exception("Market analysis command failed")
        await update.message.reply_text(f"❌ Analysis failed.\n\nError: {exc}")


async def post_init(application: Application) -> None:
    monitor = TradeAlertMonitor(application.bot)
    application.bot_data["trade_alert_monitor"] = monitor
    application.bot_data["trade_alert_task"] = asyncio.create_task(
        monitor.run(), name="aaqts-trade-alert-monitor"
    )


async def post_shutdown(application: Application) -> None:
    monitor = application.bot_data.get("trade_alert_monitor")
    if monitor:
        await monitor.stop()
    task = application.bot_data.get("trade_alert_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled Telegram bot error", exc_info=context.error)


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from the .env file.")

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("equity", equity_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("profit", profit_command))
    application.add_handler(CommandHandler("analysis", analysis_command))
    application.add_handler(CommandHandler("alerts", alerts_command))
    application.add_handler(CommandHandler("alerts_on", alerts_on_command))
    application.add_handler(CommandHandler("alerts_off", alerts_off_command))
    application.add_error_handler(error_handler)

    logger.info("AAQTS Telegram Manager is starting...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
