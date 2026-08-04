import asyncio
import logging
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Ensure project root is importable when this file is run directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from accounts.credentials import EnvironmentCredentialProvider, account_env_prefix
from accounts.registry import (
    AccountEnvironment,
    AccountPlatform,
    AccountRegistry,
    TradingAccount,
    select_accounts_for_mode,
)
from accounts.snapshots import MultiAccountSnapshotReader, aggregate_views
from config.settings import (
    EXECUTION_MODE,
    MT5_MAX_OPEN_POSITIONS,
    MT5_TERMINAL_PATH,
    PRIMARY_ACCOUNT_ID,
    RISK_PERCENT,
    SINGLE_ACCOUNT_MODE,
    SYMBOLS,
)
from control_plane import ControlAction, ControlCommandStore
from execution.mt5_executor import AAQTS_MAGIC
from paper.paper_trader import PaperTrader
from runtime_state import RUNTIME_DIR as SHARED_RUNTIME_DIR
from runtime_state import (
    heartbeat_is_fresh,
    read_all_runtime_states,
    read_runtime_state,
    runtime_state_file,
)
from telegram_bot.alert_monitor import (
    TradeAlertMonitor,
    is_subscribed,
    paper_closed_position_details,
    paper_daily_summary_snapshot,
    read_paper_positions,
    subscribe,
    unsubscribe,
)
from telegram_bot.audit import TelegramAuditLog
from telegram_bot.dashboard import format_dashboard, mt5_dashboard_snapshot
from telegram_bot.menus import (
    account_keyboard,
    accounts_keyboard,
    add_broker_keyboard,
    add_environment_keyboard,
    add_platform_keyboard,
    back_home_keyboard,
    confirmation_keyboard,
    home_keyboard,
    safety_keyboard,
    single_account_home_keyboard,
)
from telegram_bot.security import (
    CONTROL_ROLE,
    OWNER_ROLE,
    READ_ROLE,
    TelegramAccessPolicy,
    TelegramRole,
)
from telegram_bot.totp import TotpVerifier

load_dotenv(PROJECT_ROOT / ".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("aaqts.telegram")
paper_trader = PaperTrader()
RUNTIME_DIR = SHARED_RUNTIME_DIR
ACCOUNT_REGISTRY = AccountRegistry(
    RUNTIME_DIR / "accounts_registry.json",
    max_accounts=1 if SINGLE_ACCOUNT_MODE else 100,
)
CREDENTIALS = EnvironmentCredentialProvider()
ACCOUNT_READER = MultiAccountSnapshotReader(CREDENTIALS)
CONTROL_COMMANDS = ControlCommandStore(RUNTIME_DIR / "control")
ACCESS_POLICY = TelegramAccessPolicy.from_env()
AUDIT_LOG = TelegramAuditLog(RUNTIME_DIR / "telegram_audit.jsonl")
TOTP = TotpVerifier.from_env()

(
    ADD_LABEL,
    ADD_PLATFORM,
    ADD_BROKER,
    ADD_BROKER_NAME,
    ADD_ENV,
    ADD_LOGIN,
    ADD_SERVER,
    ADD_CONNECTION,
) = range(8)


def _role(update: Update) -> TelegramRole | None:
    user_id = update.effective_user.id if update.effective_user else None
    return ACCESS_POLICY.role_for(user_id)


def _managed_accounts(*, enabled_only: bool = False) -> tuple[TradingAccount, ...]:
    """Return only the configured account scope; ambiguous scopes fail closed."""

    try:
        return select_accounts_for_mode(
            ACCOUNT_REGISTRY.list_accounts(),
            single_account_mode=SINGLE_ACCOUNT_MODE,
            primary_account_id=PRIMARY_ACCOUNT_ID,
            enabled_only=enabled_only,
        )
    except RuntimeError as exc:
        logger.error("Account scope is not configured safely: %s", exc)
        return ()


def _resolve_managed_token(token: str) -> TradingAccount:
    account = ACCOUNT_REGISTRY.resolve_token(token)
    allowed = {item.account_id for item in _managed_accounts()}
    if account.account_id not in allowed:
        raise KeyError("Account is outside the configured Telegram scope")
    return account


def _account_menu(
    account: TradingAccount, role: TelegramRole
) -> InlineKeyboardMarkup:
    return account_keyboard(
        account,
        role,
        single_account_mode=SINGLE_ACCOUNT_MODE,
    )


def _home_menu(role: TelegramRole) -> InlineKeyboardMarkup:
    if SINGLE_ACCOUNT_MODE:
        account = next(iter(_managed_accounts()), None)
        return single_account_home_keyboard(role, account)
    return home_keyboard(role)


async def ensure_access(
    update: Update,
    minimum: TelegramRole = READ_ROLE,
    *,
    private_for_control: bool = False,
) -> TelegramRole | None:
    user_id = update.effective_user.id if update.effective_user else None
    role = ACCESS_POLICY.role_for(user_id)
    if role is None or role < minimum:
        message = (
            "⛔ Telegram access is not configured for this user.\n\n"
            f"Your Telegram user ID: {user_id}\n"
            "The owner must add this numeric ID to the server allowlist."
        )
        if update.callback_query:
            await update.callback_query.answer(
                f"Access denied. User ID: {user_id}", show_alert=True
            )
        elif update.effective_message:
            await update.effective_message.reply_text(message)
        return None
    if private_for_control and (
        not update.effective_chat or update.effective_chat.type != ChatType.PRIVATE
    ):
        if update.callback_query:
            await update.callback_query.answer(
                "Controls are allowed only in a private chat", show_alert=True
            )
        elif update.effective_message:
            await update.effective_message.reply_text(
                "⛔ Trading controls are allowed only in a private chat."
            )
        return None
    return role


def _home_text(role: TelegramRole) -> str:
    all_accounts = ACCOUNT_REGISTRY.list_accounts()
    accounts = _managed_accounts()
    enabled = sum(account.enabled for account in accounts)
    live = sum(account.is_live for account in accounts)
    status, state = runtime_status()
    worker_states = read_all_runtime_states()
    fresh_workers = sum(heartbeat_is_fresh(item) for item in worker_states)
    if SINGLE_ACCOUNT_MODE:
        if accounts:
            account_line = (
                f"Account: {accounts[0].label} · {accounts[0].platform.value} "
                f"{accounts[0].environment.value}"
            )
        elif len(all_accounts) > 1 and not PRIMARY_ACCOUNT_ID:
            account_line = (
                "Account: SELECTION REQUIRED\n"
                "Set AAQTS_PRIMARY_ACCOUNT_ID to one registered account."
            )
        elif PRIMARY_ACCOUNT_ID and not accounts:
            account_line = "Account: CONFIGURATION ERROR"
        else:
            account_line = "Account: NOT SET UP"
        return (
            "🤖 AAQTS MY ACCOUNT\n\n"
            f"{account_line}\n"
            f"Engine: {status}\n"
            f"Worker: {'CONNECTED' if fresh_workers else 'OFFLINE'}\n"
            f"Execution mode: {state.get('execution_mode', EXECUTION_MODE)}\n"
            "Live execution: LOCKED 🔒\n"
            f"Role: {role.name.replace('_', ' ')}"
        )
    return (
        "🤖 AAQTS PARENT CONTROL\n\n"
        f"Engine: {status}\n"
        f"Registered accounts: {len(accounts)} ({enabled} enabled)\n"
        f"Fresh workers: {fresh_workers}/{len(worker_states)}\n"
        f"Live accounts: {live} 🔒\n"
        f"Execution mode: {state.get('execution_mode', EXECUTION_MODE)}\n"
        f"Role: {role.name.replace('_', ' ')}\n\n"
        "Scope: ALL ACCOUNTS"
    )


async def _edit_or_reply(
    update: Update, text: str, reply_markup: InlineKeyboardMarkup
) -> None:
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=text, reply_markup=reply_markup
            )
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    elif update.effective_message:
        await update.effective_message.reply_text(text=text, reply_markup=reply_markup)


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
    role = await ensure_access(update)
    if role is None:
        return
    if update.effective_chat:
        subscribe(update.effective_chat.id)
    await _edit_or_reply(update, _home_text(role), _home_menu(role))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    role = await ensure_access(update)
    if role is None or not update.effective_message:
        return
    await update.effective_message.reply_text(
        "🤖 AAQTS COMMANDS\n\n"
        "/menu - Account control buttons\n"
        "/status - Engine status\n"
        "/dashboard - Current primary account dashboard\n"
        "/balance - Primary account balance\n"
        "/equity - Primary account equity\n"
        "/positions - AAQTS-managed positions\n"
        "/profit - Trading performance\n"
        "/analysis - Market analysis\n"
        "/alerts - Alert subscription\n"
        "/cancel - Cancel account setup"
    )


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await ensure_access(update) is None:
        return
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
    if await ensure_access(update) is None:
        return
    if not update.message or not update.effective_chat:
        return
    subscribe(update.effective_chat.id)
    await update.message.reply_text(
        "🔔 Automatic AAQTS alerts enabled.\n\n"
        "You will receive trade-open, trade-close and daily-summary notifications."
    )


async def alerts_off_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if await ensure_access(update) is None:
        return
    if not update.message or not update.effective_chat:
        return
    unsubscribe(update.effective_chat.id)
    await update.message.reply_text("🔕 Automatic AAQTS alerts disabled for this chat.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await ensure_access(update) is None:
        return
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
    if await ensure_access(update) is None:
        return
    if not update.message:
        return
    try:
        snapshot = await asyncio.to_thread(mt5_dashboard_snapshot)
        await update.message.reply_text(format_dashboard(snapshot))
    except Exception as exc:
        logger.exception("Dashboard command failed")
        await update.message.reply_text(f"❌ Could not build live dashboard.\n\n{exc}")


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await ensure_access(update) is None:
        return
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
    if await ensure_access(update) is None:
        return
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
    if await ensure_access(update) is None:
        return
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
        await update.message.reply_text(
            "📭 OPEN POSITIONS\n\nNo AAQTS positions are open."
        )
        return

    lines = ["📈 AAQTS OPEN POSITIONS", ""]
    if EXECUTION_MODE == "MT5_DEMO":
        for index, position in enumerate(positions, start=1):
            side = "BUY" if getattr(position, "type", 0) == 0 else "SELL"
            lines.extend(
                [
                    f"{index}. {getattr(position, 'symbol', 'Unknown')} | {side}",
                    f"Ticket: {getattr(position, 'ticket', 'N/A')}",
                    f"Volume: {getattr(position, 'volume', 'N/A')}",
                    f"Entry: {getattr(position, 'price_open', 'N/A')}",
                    f"Current: {getattr(position, 'price_current', 'N/A')}",
                    f"P/L: {money(getattr(position, 'profit', 0.0))}",
                    f"SL: {getattr(position, 'sl', 'N/A')}",
                    f"TP: {getattr(position, 'tp', 'N/A')}",
                    "",
                ]
            )
    else:
        for index, trade in enumerate(positions, start=1):
            lines.extend(
                [
                    f"{index}. {trade.get('symbol', 'Unknown')} | {trade.get('signal', 'Unknown')}",
                    f"Entry: {trade.get('entry', 'N/A')}",
                    f"SL: {trade.get('stop_loss', 'N/A')}",
                    f"TP: {trade.get('take_profit', 'N/A')}",
                    "",
                ]
            )

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        await update.message.reply_text(text[start : start + 3900])


async def profit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await ensure_access(update) is None:
        return
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
            signal = signal_engine.generate_analysis(
                analyzed_data, symbol, higher_tf_data.get(symbol)
            )
            results.append(
                {
                    "symbol": symbol,
                    "signal": signal.get("signal", "HOLD"),
                    "confidence": signal.get("confidence", 0),
                    "reasons": signal.get("reasons", []),
                    "decision_report": signal.get("decision_report", {}),
                }
            )
        except Exception as exc:
            logger.exception("Analysis failed for %s", symbol)
            results.append(
                {
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
                }
            )

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
    if await ensure_access(update) is None:
        return
    if not update.message:
        return
    await update.message.reply_text("🔍 Running AAQTS market analysis. Please wait...")
    try:
        result = await asyncio.to_thread(run_analysis_sync)
        for start in range(0, len(result), 3900):
            await update.message.reply_text(result[start : start + 3900])
    except Exception as exc:
        logger.exception("Market analysis command failed")
        await update.message.reply_text(f"❌ Analysis failed.\n\nError: {exc}")


def _account_status_icon(status: str) -> str:
    if status == "CONNECTED":
        return "🟢"
    if status in {"DISABLED", "SETUP_REQUIRED"}:
        return "⚫" if status == "DISABLED" else "🟡"
    return "🔴"


async def _show_accounts(update: Update, role: TelegramRole, page: int = 0) -> None:
    accounts = _managed_accounts()
    enabled = sum(account.enabled for account in accounts)
    text = (
        "🏦 MANAGED ACCOUNTS\n\n"
        f"Registered: {len(accounts)}\n"
        f"Enabled: {enabled}\n"
        f"Disabled: {len(accounts) - enabled}\n\n"
        "🔒 means a registered live account; live execution remains locked."
    )
    if not accounts:
        text += "\n\nNo accounts registered yet."
    await _edit_or_reply(update, text, accounts_keyboard(accounts, page, role))


async def _show_portfolio(update: Update) -> None:
    accounts = _managed_accounts(enabled_only=True)
    views = await asyncio.to_thread(ACCOUNT_READER.read_many, accounts)
    totals = aggregate_views(views)
    issues = [
        f"• {view.account_id}: {view.status}"
        for view in views
        if view.status != "CONNECTED"
    ]
    text = (
        "📊 PARENT PORTFOLIO\n\n"
        f"Connected: {totals['connected']}/{totals['accounts']}\n"
        f"Balance: {money(totals['balance'])}\n"
        f"Equity: {money(totals['equity'])}\n"
        f"Floating P/L: {money(totals['floating_pnl'])}\n"
        f"AAQTS positions: {totals['open_positions']}\n"
        f"Accounts needing attention: {totals['issues']}"
    )
    if issues:
        text += "\n\n" + "\n".join(issues[:8])
    await _edit_or_reply(update, text, back_home_keyboard())


async def _show_positions_overview(update: Update) -> None:
    accounts = _managed_accounts(enabled_only=True)
    views = await asyncio.to_thread(ACCOUNT_READER.read_many, accounts)
    lines = ["📈 AAQTS POSITIONS BY ACCOUNT", ""]
    for account, view in zip(accounts, views):
        lines.append(
            f"{_account_status_icon(view.status)} {account.label}: "
            f"{view.open_positions} positions · {money(view.floating_pnl)}"
        )
    if not accounts:
        lines.append("No enabled accounts are registered.")
    await _edit_or_reply(update, "\n".join(lines), back_home_keyboard())


async def _show_account(update: Update, role: TelegramRole, token: str) -> None:
    try:
        account = _resolve_managed_token(token)
    except KeyError:
        await _edit_or_reply(
            update, "❌ Account no longer exists.", back_home_keyboard()
        )
        return
    view = await asyncio.to_thread(ACCOUNT_READER.read, account)
    missing = CREDENTIALS.readiness(account).missing
    setup = ""
    if missing:
        setup = "\nSetup required: " + ", ".join(missing)
    text = (
        f"{_account_status_icon(view.status)} {account.label}\n\n"
        f"Account ID: {account.account_id}\n"
        f"Broker: {account.broker}\n"
        f"Platform: {account.platform.value}\n"
        f"Mode: {account.environment.value}{' 🔒' if account.is_live else ''}\n"
        f"Login: {account.masked_login}\n"
        f"Server: {account.server}\n"
        f"Group: {account.group}\n"
        f"Connection: {view.status}\n\n"
        f"Balance: {money(view.balance)}\n"
        f"Equity: {money(view.equity)}\n"
        f"Floating P/L: {money(view.floating_pnl)}\n"
        f"AAQTS positions: {view.open_positions}"
        f"{setup}"
    )
    if view.reason and not missing:
        text += f"\nDetail: {view.reason}"
    await _edit_or_reply(update, text, _account_menu(account, role))


def _resolve_scope(scope: str) -> tuple[TradingAccount, ...]:
    if scope == "all":
        return tuple(
            account
            for account in _managed_accounts(enabled_only=True)
            if not account.is_live
        )
    return (_resolve_managed_token(scope),)


def _queue_action(
    accounts: tuple[TradingAccount, ...],
    action: ControlAction,
    *,
    user_id: int,
    reason: str,
) -> tuple[str, ...]:
    request_ids = []
    for account in accounts:
        if account.is_live:
            raise RuntimeError(
                f"Live control is locked for account {account.account_id}"
            )
        if action is ControlAction.RESUME_ENTRIES:
            CONTROL_COMMANDS.clear_restart_block(account.account_id)
        request = CONTROL_COMMANDS.submit(
            account.account_id,
            action,
            requested_by=user_id,
            reason=reason,
        )
        request_ids.append(request.request_id)
    return tuple(request_ids)


async def _submit_control(
    update: Update,
    role: TelegramRole,
    accounts: tuple[TradingAccount, ...],
    action: ControlAction,
) -> None:
    user_id = update.effective_user.id
    if not accounts:
        await _edit_or_reply(
            update, "No enabled accounts match this scope.", back_home_keyboard()
        )
        return
    try:
        request_ids = _queue_action(
            accounts,
            action,
            user_id=user_id,
            reason=f"Telegram {action.value.lower()}",
        )
        AUDIT_LOG.write(
            action.value,
            user_id=user_id,
            role=role.name,
            account_ids=tuple(item.account_id for item in accounts),
            detail={"request_ids": list(request_ids)},
        )
        text = (
            f"✅ {action.value.replace('_', ' ')} queued\n\n"
            f"Accounts: {len(accounts)}\n"
            "The target engine worker will execute and record the result."
        )
    except Exception as exc:
        logger.exception("Could not queue Telegram control")
        AUDIT_LOG.write(
            action.value,
            user_id=user_id,
            role=role.name,
            account_ids=tuple(item.account_id for item in accounts),
            outcome="FAILED",
            detail={"error": str(exc)},
        )
        text = f"❌ Control request rejected.\n\n{exc}"
    await _edit_or_reply(update, text, back_home_keyboard())


async def _request_dangerous_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    role: TelegramRole,
    accounts: tuple[TradingAccount, ...],
    action: ControlAction,
) -> None:
    if not TOTP.configured:
        await _edit_or_reply(
            update,
            "🔒 Dangerous controls are locked.\n\n"
            "Configure TELEGRAM_CONTROL_TOTP_SECRET on the host first.",
            back_home_keyboard(),
        )
        return
    nonce = secrets.token_hex(4)
    expires = datetime.now(timezone.utc) + timedelta(seconds=30)
    # Kept only in memory and bound to both the Telegram user and nonce.
    context.bot_data.setdefault("confirmations", {})[
        (update.effective_user.id, nonce)
    ] = {
        "action": action.value,
        "account_ids": [account.account_id for account in accounts],
        "expires": expires.isoformat(),
        "role": role.name,
    }
    text = (
        f"⚠️ CONFIRM {action.value.replace('_', ' ')}\n\n"
        f"Scope: {len(accounts)} account(s)\n"
        f"Accounts: {', '.join(account.label for account in accounts[:8])}\n"
        "Only AAQTS-managed positions are eligible for emergency closure.\n"
        "Manual/unmanaged positions will not be touched.\n\n"
        "Confirmation expires in 30 seconds."
    )
    await _edit_or_reply(update, text, confirmation_keyboard(nonce))


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    role = await ensure_access(update)
    if role is None:
        return
    await query.answer()
    data = query.data or ""

    if data == "noop":
        return
    if data == "nav:h":
        await _edit_or_reply(update, _home_text(role), _home_menu(role))
        return
    if data.startswith("nav:a:"):
        try:
            page = int(data.rsplit(":", 1)[1])
        except ValueError:
            page = 0
        await _show_accounts(update, role, page)
        return
    if data == "nav:p":
        await _show_portfolio(update)
        return
    if data == "nav:pos":
        await _show_positions_overview(update)
        return
    if data == "nav:sig":
        await _edit_or_reply(
            update,
            "🧠 SIGNALS\n\nUse /analysis for the current causal market analysis. "
            "Trade execution remains automatic and risk-gated.",
            back_home_keyboard(),
        )
        return
    if data == "nav:risk":
        scope_text = (
            "Your configured limits remain the hard ceiling for this account."
            if SINGLE_ACCOUNT_MODE
            else "Parent limits remain the hard ceiling for every child account."
        )
        await _edit_or_reply(
            update,
            "🛡 RISK CENTER\n\n"
            f"{scope_text}\n"
            "• Daily loss protection\n"
            "• Weekly loss protection\n"
            "• Equity drawdown protection\n"
            "• Portfolio/open-position limits\n"
            "• News and correlated-exposure gates\n\n"
            "Risk editing is intentionally locked until persistent per-account "
            "risk profiles are connected to the engine workers.",
            back_home_keyboard(),
        )
        return
    if data == "nav:alerts":
        chat_id = update.effective_chat.id
        enabled = is_subscribed(chat_id)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Enable", callback_data="alerts:on"),
                    InlineKeyboardButton("Disable", callback_data="alerts:off"),
                ],
                [InlineKeyboardButton("‹ Home", callback_data="nav:h")],
            ]
        )
        await _edit_or_reply(
            update,
            "🔔 ALERTS\n\nStatus: " + ("ENABLED ✅" if enabled else "DISABLED ❌"),
            keyboard,
        )
        return
    if data in {"alerts:on", "alerts:off"}:
        if data.endswith("on"):
            subscribe(update.effective_chat.id)
        else:
            unsubscribe(update.effective_chat.id)
        await query.edit_message_text(
            "🔔 Alerts " + ("enabled." if data.endswith("on") else "disabled."),
            reply_markup=back_home_keyboard(),
        )
        return
    if data == "nav:audit":
        if role < TelegramRole.RISK_MANAGER:
            await query.edit_message_text(
                "⛔ Risk Manager or Owner role required.",
                reply_markup=back_home_keyboard(),
            )
            return
        records = AUDIT_LOG.recent(8)
        lines = ["📜 RECENT AUDIT EVENTS", ""]
        for record in records:
            lines.append(
                f"• {record.get('event')} · {record.get('outcome')} · "
                f"{len(record.get('account_ids', []))} account(s)"
            )
        if not records:
            lines.append("No control events recorded yet.")
        await _edit_or_reply(update, "\n".join(lines), back_home_keyboard())
        return
    if data == "nav:settings":
        accounts = _managed_accounts()
        ready = sum(CREDENTIALS.readiness(item).ready for item in accounts)
        await _edit_or_reply(
            update,
            "⚙️ SETTINGS\n\n"
            f"Role: {role.name.replace('_', ' ')}\n"
            f"Mode: {'SINGLE ACCOUNT' if SINGLE_ACCOUNT_MODE else 'MULTI ACCOUNT'}\n"
            f"Account capacity: {len(accounts)}/{ACCOUNT_REGISTRY.max_accounts}\n"
            f"Host-ready accounts: {ready}/{len(accounts)}\n"
            f"TOTP safety: {'CONFIGURED' if TOTP.configured else 'NOT CONFIGURED'}\n"
            "Credentials: host environment only; never stored in Telegram.",
            back_home_keyboard(),
        )
        return
    if data == "nav:safety":
        if role < CONTROL_ROLE:
            await query.edit_message_text(
                "⛔ Operator role required.", reply_markup=back_home_keyboard()
            )
            return
        await _edit_or_reply(
            update,
            "🆘 SAFETY CONTROLS\n\n"
            "Pause Entries blocks new trades while existing positions remain managed.\n"
            "Stop Engine stops automation; broker SL/TP remain active.\n"
            "Emergency Close closes AAQTS-managed positions and stops the engine.",
            safety_keyboard(role, single_account_mode=SINGLE_ACCOUNT_MODE),
        )
        return
    if data.startswith("acc:"):
        await _show_account(update, role, data.split(":", 1)[1])
        return
    if data.startswith("av:"):
        _, section, token = data.split(":", 2)
        account = _resolve_managed_token(token)
        view = await asyncio.to_thread(ACCOUNT_READER.read, account)
        active_symbols = [symbol for group in SYMBOLS.values() for symbol in group]
        control_records = CONTROL_COMMANDS.recent(account.account_id, limit=5)
        control_text = "No control requests for this account."
        if control_records:
            control_text = "\n".join(
                f"• {record.get('action')} · "
                f"{record.get('status', record.get('queue_state', 'PENDING'))}"
                for record in control_records
            )
        labels = {
            "pos": (
                f"AAQTS-managed positions: {view.open_positions}\n"
                f"Floating P/L: {money(view.floating_pnl)}\n"
                f"Connection: {view.status}"
            ),
            "perf": (
                f"Balance: {money(view.balance)}\n"
                f"Equity: {money(view.equity)}\n"
                f"Floating P/L: {money(view.floating_pnl)}"
                + (
                    f"\nStarting balance: {money(view.starting_balance)}\n"
                    f"Realized P/L: {money(view.total_pnl)}\n"
                    f"Closed trades: {view.closed_trades}\n"
                    f"Wins: {view.wins}\n"
                    f"Win rate: {view.win_rate:.2f}%"
                    if account.platform is AccountPlatform.PAPER
                    else ""
                )
            ),
            "str": (
                "Strategy: causal regime router\n"
                f"Active symbol catalog: {len(active_symbols)} symbols\n"
                f"Symbols: {', '.join(active_symbols)}"
            ),
            "risk": (
                f"Base trade risk ceiling: {RISK_PERCENT}%\n"
                f"Maximum open positions: {MT5_MAX_OPEN_POSITIONS}\n"
                "Daily, weekly, drawdown, correlation and news gates: ACTIVE\n"
                + (
                    "This account cannot exceed the configured risk ceiling."
                    if SINGLE_ACCOUNT_MODE
                    else "Child limits cannot exceed the parent ceiling."
                )
            ),
            "ctl": control_text,
        }
        await query.edit_message_text(
            f"{account.label}\n\n{labels.get(section, 'Unavailable')}",
            reply_markup=_account_menu(account, role),
        )
        return
    if data.startswith("ctl:"):
        if role < CONTROL_ROLE or update.effective_chat.type != ChatType.PRIVATE:
            await query.edit_message_text(
                "⛔ Operator role and private chat are required.",
                reply_markup=back_home_keyboard(),
            )
            return
        _, code, token = data.split(":", 2)
        account = _resolve_managed_token(token)
        if code == "b":
            CONTROL_COMMANDS.clear_restart_block(account.account_id)
            AUDIT_LOG.write(
                "START_ENGINE_REQUESTED",
                user_id=update.effective_user.id,
                role=role.name,
                account_ids=(account.account_id,),
            )
            await query.edit_message_text(
                f"✅ Start requested for {account.label}.\n\n"
                "The supervisor will launch its worker.",
                reply_markup=_account_menu(account, role),
            )
            return
        action = (
            ControlAction.PAUSE_ENTRIES if code == "p" else ControlAction.RESUME_ENTRIES
        )
        await _submit_control(update, role, (account,), action)
        return
    if data.startswith("acct:t:"):
        if role < OWNER_ROLE or update.effective_chat.type != ChatType.PRIVATE:
            await query.edit_message_text(
                "⛔ Owner role and private chat are required.",
                reply_markup=back_home_keyboard(),
            )
            return
        account = _resolve_managed_token(data.split(":", 2)[2])
        if account.enabled:
            view = await asyncio.to_thread(ACCOUNT_READER.read, account)
            if view.status not in {"CONNECTED", "SETUP_REQUIRED"}:
                await query.edit_message_text(
                    "⛔ Account state could not be verified, so disable failed closed.\n\n"
                    f"Connection: {view.status}",
                    reply_markup=_account_menu(account, role),
                )
                return
            if view.open_positions:
                await query.edit_message_text(
                    "⛔ Account worker cannot be disabled while AAQTS positions "
                    f"are open ({view.open_positions}). Pause entries or use the "
                    "confirmed emergency workflow.",
                    reply_markup=_account_menu(account, role),
                )
                return
        updated = ACCOUNT_REGISTRY.set_enabled(account.account_id, not account.enabled)
        if not updated.enabled and not updated.is_live:
            _queue_action(
                (updated,),
                ControlAction.PAUSE_ENTRIES,
                user_id=update.effective_user.id,
                reason="Account disabled by owner",
            )
        AUDIT_LOG.write(
            "ACCOUNT_ENABLED" if updated.enabled else "ACCOUNT_DISABLED",
            user_id=update.effective_user.id,
            role=role.name,
            account_ids=(updated.account_id,),
        )
        await _show_account(update, role, updated.callback_token)
        return
    if data.startswith("safe:"):
        _, code, scope = data.split(":", 2)
        minimum = OWNER_ROLE if code in {"s", "e"} else CONTROL_ROLE
        if role < minimum or update.effective_chat.type != ChatType.PRIVATE:
            await query.edit_message_text(
                "⛔ Required role and private chat are missing.",
                reply_markup=back_home_keyboard(),
            )
            return
        checked_role = role
        accounts = _resolve_scope(scope)
        actions = {
            "p": ControlAction.PAUSE_ENTRIES,
            "r": ControlAction.RESUME_ENTRIES,
            "s": ControlAction.STOP_ENGINE,
            "e": ControlAction.EMERGENCY_CLOSE,
        }
        action = actions[code]
        if action in {ControlAction.STOP_ENGINE, ControlAction.EMERGENCY_CLOSE}:
            await _request_dangerous_confirmation(
                update, context, checked_role, accounts, action
            )
        else:
            await _submit_control(update, checked_role, accounts, action)
        return
    if data.startswith("confirm:"):
        if data == "confirm:cancel":
            await query.edit_message_text(
                "Cancelled.", reply_markup=back_home_keyboard()
            )
            return
        if role < OWNER_ROLE or update.effective_chat.type != ChatType.PRIVATE:
            await query.edit_message_text(
                "⛔ Owner role and private chat are required.",
                reply_markup=back_home_keyboard(),
            )
            return
        nonce = data.split(":", 1)[1]
        pending = context.bot_data.get("confirmations", {}).get(
            (update.effective_user.id, nonce)
        )
        if not pending:
            await query.edit_message_text(
                "Confirmation is invalid or expired.",
                reply_markup=back_home_keyboard(),
            )
            return
        expires = datetime.fromisoformat(pending["expires"])
        if datetime.now(timezone.utc) > expires:
            context.bot_data["confirmations"].pop(
                (update.effective_user.id, nonce), None
            )
            await query.edit_message_text(
                "Confirmation expired.", reply_markup=back_home_keyboard()
            )
            return
        context.user_data["awaiting_totp"] = {"nonce": nonce, **pending}
        await query.message.reply_text(
            "Send the current 6-digit owner TOTP code. The message will be deleted.",
            reply_markup=ForceReply(
                selective=True, input_field_placeholder="6-digit code"
            ),
        )
        return


async def totp_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = context.user_data.get("awaiting_totp")
    if not pending or not update.message:
        return
    role = await ensure_access(update, OWNER_ROLE, private_for_control=True)
    if role is None:
        return
    code = update.message.text or ""
    try:
        await update.message.delete()
    except TelegramError:
        logger.warning("Could not delete TOTP reply from Telegram")
    expires = datetime.fromisoformat(pending["expires"])
    if datetime.now(timezone.utc) > expires:
        context.user_data.pop("awaiting_totp", None)
        await update.effective_chat.send_message("❌ Confirmation expired.")
        return
    if not TOTP.verify(code):
        await update.effective_chat.send_message("❌ Invalid TOTP code.")
        return
    accounts = tuple(
        ACCOUNT_REGISTRY.get(account_id) for account_id in pending["account_ids"]
    )
    action = ControlAction(pending["action"])
    nonce = pending["nonce"]
    context.user_data.pop("awaiting_totp", None)
    context.bot_data.get("confirmations", {}).pop(
        (update.effective_user.id, nonce), None
    )
    await _submit_control(update, role, accounts, action)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return slug[:48].lower()


async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    role = await ensure_access(update, OWNER_ROLE, private_for_control=True)
    if role is None:
        return ConversationHandler.END
    await update.callback_query.answer()
    if SINGLE_ACCOUNT_MODE and ACCOUNT_REGISTRY.list_accounts():
        await update.callback_query.edit_message_text(
            "Your account is already configured. Single-account mode blocks "
            "additional account registration.",
            reply_markup=back_home_keyboard(),
        )
        return ConversationHandler.END
    context.user_data["new_account"] = {}
    await update.callback_query.message.reply_text(
        "Send a short account alias, for example DEMO-01 or EXNESS-MT5-02.",
        reply_markup=ForceReply(
            selective=True, input_field_placeholder="Account alias"
        ),
    )
    return ADD_LABEL


async def add_label_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await ensure_access(update, OWNER_ROLE, private_for_control=True) is None:
        return ConversationHandler.END
    label = (update.message.text or "").strip()
    account_id = _slug(label)
    if not account_id:
        await update.message.reply_text("Invalid alias. Send letters/numbers only.")
        return ADD_LABEL
    context.user_data["new_account"].update(
        {"label": label[:48], "account_id": account_id}
    )
    await update.message.reply_text(
        "Select the account platform.", reply_markup=add_platform_keyboard()
    )
    return ADD_PLATFORM


async def add_platform_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.callback_query.answer()
    platform = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["new_account"]["platform"] = platform
    await update.callback_query.edit_message_text(
        "Select the broker.", reply_markup=add_broker_keyboard()
    )
    return ADD_BROKER


async def add_broker_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.callback_query.answer()
    broker = update.callback_query.data.rsplit(":", 1)[1]
    if broker == "OTHER":
        await update.callback_query.message.reply_text(
            "Send the broker name.",
            reply_markup=ForceReply(
                selective=True, input_field_placeholder="Broker name"
            ),
        )
        return ADD_BROKER_NAME
    context.user_data["new_account"]["broker"] = "Exness"
    await update.callback_query.edit_message_text(
        "Select demo or live.", reply_markup=add_environment_keyboard()
    )
    return ADD_ENV


async def add_broker_name_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    broker = (update.message.text or "").strip()
    if not broker or len(broker) > 48:
        await update.message.reply_text("Broker name must contain 1-48 characters.")
        return ADD_BROKER_NAME
    context.user_data["new_account"]["broker"] = broker
    await update.message.reply_text(
        "Select demo or live.", reply_markup=add_environment_keyboard()
    )
    return ADD_ENV


async def add_environment_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.callback_query.answer()
    environment = update.callback_query.data.rsplit(":", 1)[1]
    context.user_data["new_account"]["environment"] = environment
    await update.callback_query.message.reply_text(
        "Send the MT4/MT5 trading account login number. Do not send a password.",
        reply_markup=ForceReply(
            selective=True, input_field_placeholder="Trading login"
        ),
    )
    return ADD_LOGIN


async def add_login_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    login = (update.message.text or "").strip()
    if not login.isdigit() or len(login) > 64:
        await update.message.reply_text("Trading login must be numeric.")
        return ADD_LOGIN
    context.user_data["new_account"]["login"] = login
    await update.message.reply_text(
        "Send the exact trading server shown in Exness/MetaTrader.",
        reply_markup=ForceReply(
            selective=True, input_field_placeholder="Example: Exness-MT5Trial"
        ),
    )
    return ADD_SERVER


async def add_server_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    server = (update.message.text or "").strip()
    if not server or len(server) > 128:
        await update.message.reply_text("Server must contain 1-128 characters.")
        return ADD_SERVER
    values = context.user_data["new_account"]
    values["server"] = server
    if values["platform"] == "MT5":
        prompt = (
            "Send the MT5 terminal64.exe path for this account, or send DEFAULT "
            "to use the configured terminal path."
        )
        placeholder = "C:\\Program Files\\MetaTrader 5\\terminal64.exe"
    else:
        prompt = (
            "Send the HTTPS/localhost URL of this account's MT4 bridge, or SKIP "
            "to register it as setup-required."
        )
        placeholder = "http://127.0.0.1:9001"
    await update.message.reply_text(
        prompt,
        reply_markup=ForceReply(
            selective=True, input_field_placeholder=placeholder[:64]
        ),
    )
    return ADD_CONNECTION


async def add_connection_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    connection = (update.message.text or "").strip()
    values = dict(context.user_data["new_account"])
    account_id = values["account_id"]
    try:
        ACCOUNT_REGISTRY.get(account_id)
    except KeyError:
        pass
    else:
        account_id = f"{account_id}_{values['login'][-4:]}"
    platform = AccountPlatform(values["platform"])
    terminal_path = ""
    bridge_url = ""
    if platform is AccountPlatform.MT5:
        terminal_path = (
            MT5_TERMINAL_PATH if connection.upper() == "DEFAULT" else connection
        )
    elif connection.upper() != "SKIP":
        bridge_url = connection
    try:
        account = TradingAccount(
            account_id=account_id,
            label=values["label"],
            broker=values["broker"],
            platform=platform,
            environment=AccountEnvironment(values["environment"]),
            login=values["login"],
            server=values["server"],
            enabled=True,
            terminal_path=terminal_path,
            bridge_url=bridge_url,
        )
        ACCOUNT_REGISTRY.add(account)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        await update.message.reply_text(f"❌ Account was not added.\n\n{exc}")
        return ADD_CONNECTION
    context.user_data.pop("new_account", None)
    prefix = account_env_prefix(account.account_id)
    setup = (
        f"Set {prefix}_PASSWORD on the host."
        if platform is AccountPlatform.MT5
        else f"Set {prefix}_BRIDGE_TOKEN on the host."
    )
    live_note = (
        "\nLive account is read-only; live execution remains locked."
        if account.is_live
        else ""
    )
    AUDIT_LOG.write(
        "ACCOUNT_REGISTERED",
        user_id=update.effective_user.id,
        role=TelegramRole.OWNER.name,
        account_ids=(account.account_id,),
    )
    await update.message.reply_text(
        f"✅ {account.label} registered.\n\n{setup}{live_note}",
        reply_markup=_account_menu(account, TelegramRole.OWNER),
    )
    return ConversationHandler.END


async def cancel_conversation(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("new_account", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Account setup cancelled.", reply_markup=back_home_keyboard()
        )
    elif update.effective_message:
        await update.effective_message.reply_text("Account setup cancelled.")
    return ConversationHandler.END


async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands(
            [
                BotCommand("menu", "Open account control buttons"),
                BotCommand("status", "Show engine status"),
                BotCommand("dashboard", "Show primary account dashboard"),
                BotCommand("positions", "Show AAQTS positions"),
                BotCommand("analysis", "Run market analysis"),
                BotCommand("alerts", "Show alert status"),
                BotCommand("help", "Show commands"),
                BotCommand("cancel", "Cancel account setup"),
            ]
        )
    except TelegramError:
        logger.warning("Could not update Telegram command menu")
    enabled_accounts = _managed_accounts(enabled_only=True)
    paper_accounts = tuple(
        account
        for account in enabled_accounts
        if account.platform is AccountPlatform.PAPER
    )
    if len(enabled_accounts) == 1 and len(paper_accounts) == 1:
        account = paper_accounts[0]
        paper_state_dir = RUNTIME_DIR / "accounts" / account.account_id
        heartbeat_path = runtime_state_file(account.account_id, RUNTIME_DIR)
        monitor = TradeAlertMonitor(
            application.bot,
            read_positions_fn=lambda: read_paper_positions(paper_state_dir),
            closed_position_details_fn=lambda position: paper_closed_position_details(
                paper_state_dir, position
            ),
            daily_summary_snapshot_fn=lambda: paper_daily_summary_snapshot(
                paper_state_dir, heartbeat_path
            ),
        )
    else:
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
    error = context.error
    if isinstance(error, BadRequest) and "message is not modified" in str(error).lower():
        logger.debug("Ignored duplicate Telegram message edit")
        return
    logger.exception("Unhandled Telegram bot error", exc_info=error)


def main() -> None:
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from the .env file.")
    if not ACCESS_POLICY.configured:
        raise RuntimeError(
            "Telegram owner allowlist is missing. Set TELEGRAM_OWNER_IDS or "
            "the backward-compatible TELEGRAM_CHAT_ID."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    add_account_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_account_start, pattern=r"^add:start$")],
        states={
            ADD_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_label_message)
            ],
            ADD_PLATFORM: [
                CallbackQueryHandler(
                    add_platform_callback, pattern=r"^add:platform:(MT4|MT5)$"
                )
            ],
            ADD_BROKER: [
                CallbackQueryHandler(
                    add_broker_callback, pattern=r"^add:broker:(EXNESS|OTHER)$"
                )
            ],
            ADD_BROKER_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    add_broker_name_message,
                )
            ],
            ADD_ENV: [
                CallbackQueryHandler(
                    add_environment_callback, pattern=r"^add:env:(DEMO|LIVE)$"
                )
            ],
            ADD_LOGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_login_message)
            ],
            ADD_SERVER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_server_message)
            ],
            ADD_CONNECTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    add_connection_message,
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conversation),
            CallbackQueryHandler(cancel_conversation, pattern=r"^add:cancel$"),
        ],
        allow_reentry=True,
    )
    application.add_handler(add_account_conversation)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", start_command))
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
    application.add_handler(CommandHandler("cancel", cancel_conversation))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, totp_message)
    )
    application.add_error_handler(error_handler)

    logger.info("AAQTS Telegram Manager is starting...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
