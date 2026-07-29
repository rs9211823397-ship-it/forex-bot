import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# Project root ko Python import path me add karo
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# .env isi telegram_bot folder se load hoga
load_dotenv(Path(__file__).with_name(".env"))

from runtime.bot_runtime import runtime  # noqa: E402


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user
    name = user.first_name if user else "Trader"

    await update.effective_message.reply_text(
        f"Welcome {name}! 🚀\n\n"
        "AAQTS Trading Manager is online.\n\n"
        "Commands:\n"
        "/status - System status\n"
        "/balance - Paper account balance\n"
        "/equity - Current account equity\n"
        "/positions - Open paper trades\n"
        "/profit - Trading profit/loss\n"
        "/help - Show all commands"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.effective_message.reply_text(
        "AAQTS Trading Manager Commands\n\n"
        "/start - Start Telegram assistant\n"
        "/status - Show trading engine status\n"
        "/balance - Show paper account balance\n"
        "/equity - Show equity and floating P/L\n"
        "/positions - Show open positions\n"
        "/profit - Show trading statistics\n"
        "/help - Show this message"
    )


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    engine_status = runtime.bot.status()
    trader = runtime.paper_trader

    await update.effective_message.reply_text(
        "📊 AAQTS System Status\n\n"
        f"Telegram Bot: ONLINE\n"
        f"Trading Engine: {engine_status}\n"
        f"Trading Mode: PAPER\n"
        f"Open Positions: {len(trader.open_trades)}\n"
        f"Closed Trades: {len(trader.closed_trades)}\n"
        f"Live Trading: DISABLED"
    )


async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    trader = runtime.paper_trader

    await update.effective_message.reply_text(
        "💰 Paper Account Balance\n\n"
        f"Starting Balance: ${trader.starting_balance:,.2f}\n"
        f"Current Balance: ${trader.balance:,.2f}"
    )


async def equity(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    trader = runtime.paper_trader

    await update.effective_message.reply_text(
        "📈 Paper Account Equity\n\n"
        f"Balance: ${trader.balance:,.2f}\n"
        f"Floating P/L: ${trader.floating_pnl:,.2f}\n"
        f"Equity: ${trader.equity:,.2f}"
    )


async def positions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    trades = runtime.paper_trader.open_trades

    if not trades:
        await update.effective_message.reply_text(
            "📭 No open paper positions."
        )
        return

    lines = ["📂 Open Paper Positions\n"]

    for index, trade in enumerate(trades, start=1):
        lines.append(
            f"{index}. {trade.get('symbol', 'UNKNOWN')}\n"
            f"Side: {trade.get('signal', 'N/A')}\n"
            f"Entry: {trade.get('entry', 0)}\n"
            f"Position: {trade.get('position', 0)}\n"
            f"Stop Loss: {trade.get('stop_loss', 0)}\n"
            f"Take Profit: {trade.get('take_profit', 0)}\n"
            f"Status: {trade.get('status', 'UNKNOWN')}\n"
        )

    message = "\n".join(lines)

    # Telegram message limit se bachne ke liye
    await update.effective_message.reply_text(message[:4000])


async def profit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    stats = runtime.paper_trader.get_stats()

    await update.effective_message.reply_text(
        "📊 Paper Trading Performance\n\n"
        f"Net P/L: ${stats['total_pnl']:,.2f}\n"
        f"Floating P/L: ${stats['floating_pnl']:,.2f}\n"
        f"Total Closed Trades: {stats['total_trades']}\n"
        f"Wins: {stats['wins']}\n"
        f"Win Rate: {stats['win_rate']}%\n"
        f"Current Balance: ${stats['balance']:,.2f}\n"
        f"Current Equity: ${stats['equity']:,.2f}"
    )


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing from telegram_bot/.env"
        )

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("equity", equity))
    application.add_handler(CommandHandler("positions", positions))
    application.add_handler(CommandHandler("profit", profit))

    print("AAQTS Telegram bot is running...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
