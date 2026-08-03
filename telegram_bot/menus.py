"""Inline-keyboard layouts for the AAQTS Telegram parent console."""

from __future__ import annotations

from math import ceil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from accounts.registry import TradingAccount
from telegram_bot.security import TelegramRole

PAGE_SIZE = 6


def home_keyboard(role: TelegramRole) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🏦 Accounts", callback_data="nav:a:0"),
            InlineKeyboardButton("📊 Portfolio", callback_data="nav:p"),
        ],
        [
            InlineKeyboardButton("📈 Positions", callback_data="nav:pos"),
            InlineKeyboardButton("🧠 Signals", callback_data="nav:sig"),
        ],
        [
            InlineKeyboardButton("🛡 Risk Center", callback_data="nav:risk"),
            InlineKeyboardButton("🔔 Alerts", callback_data="nav:alerts"),
        ],
    ]
    if role >= TelegramRole.RISK_MANAGER:
        rows.append(
            [
                InlineKeyboardButton("📜 Audit Log", callback_data="nav:audit"),
                InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings"),
            ]
        )
    else:
        rows.append([InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings")])
    if role >= TelegramRole.OPERATOR:
        rows.append(
            [InlineKeyboardButton("🆘 Safety Controls", callback_data="nav:safety")]
        )
    rows.append([InlineKeyboardButton("↻ Refresh", callback_data="nav:h")])
    return InlineKeyboardMarkup(rows)


def single_account_home_keyboard(
    role: TelegramRole,
    account: TradingAccount | None,
) -> InlineKeyboardMarkup:
    """Return the compact owner dashboard used by the default deployment."""

    rows = []
    if account is None:
        if role >= TelegramRole.OWNER:
            rows.append(
                [
                    InlineKeyboardButton(
                        "➕ Set Up My Account", callback_data="add:start"
                    )
                ]
            )
        rows.append(
            [InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings")]
        )
        rows.append([InlineKeyboardButton("↻ Refresh", callback_data="nav:h")])
        return InlineKeyboardMarkup(rows)

    token = account.callback_token
    rows.extend(
        [
            [
                InlineKeyboardButton("📊 Dashboard", callback_data=f"acc:{token}"),
                InlineKeyboardButton(
                    "📈 Positions", callback_data=f"av:pos:{token}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📈 Performance", callback_data=f"av:perf:{token}"
                ),
                InlineKeyboardButton("🧠 Signals", callback_data="nav:sig"),
            ],
            [
                InlineKeyboardButton(
                    "🛡 Risk", callback_data=f"av:risk:{token}"
                ),
                InlineKeyboardButton("🔔 Alerts", callback_data="nav:alerts"),
            ],
            [
                InlineKeyboardButton(
                    "🧾 Controls", callback_data=f"av:ctl:{token}"
                ),
                InlineKeyboardButton("⚙️ Settings", callback_data="nav:settings"),
            ],
        ]
    )
    if role >= TelegramRole.RISK_MANAGER:
        rows.append(
            [InlineKeyboardButton("📜 Audit Log", callback_data="nav:audit")]
        )
    if role >= TelegramRole.OPERATOR:
        rows.append(
            [InlineKeyboardButton("🆘 Safety Controls", callback_data="nav:safety")]
        )
    rows.append([InlineKeyboardButton("↻ Refresh", callback_data="nav:h")])
    return InlineKeyboardMarkup(rows)


def accounts_keyboard(
    accounts: tuple[TradingAccount, ...],
    page: int,
    role: TelegramRole,
) -> InlineKeyboardMarkup:
    pages = max(1, ceil(len(accounts) / PAGE_SIZE))
    page = min(max(0, int(page)), pages - 1)
    start = page * PAGE_SIZE
    visible = accounts[start : start + PAGE_SIZE]
    rows = []
    for account in visible:
        mode = "🔒" if account.is_live else "🧪"
        enabled = "🟢" if account.enabled else "⚫"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{enabled} {mode} {account.label} · {account.platform.value}",
                    callback_data=f"acc:{account.callback_token}",
                )
            ]
        )
    navigation = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton("‹ Previous", callback_data=f"nav:a:{page - 1}")
        )
    navigation.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
    if page + 1 < pages:
        navigation.append(
            InlineKeyboardButton("Next ›", callback_data=f"nav:a:{page + 1}")
        )
    rows.append(navigation)
    if role >= TelegramRole.OWNER:
        rows.append([InlineKeyboardButton("➕ Add Account", callback_data="add:start")])
    rows.append([InlineKeyboardButton("‹ Parent Home", callback_data="nav:h")])
    return InlineKeyboardMarkup(rows)


def account_keyboard(
    account: TradingAccount,
    role: TelegramRole,
    *,
    single_account_mode: bool = False,
) -> InlineKeyboardMarkup:
    token = account.callback_token
    rows = [
        [
            InlineKeyboardButton("📈 Positions", callback_data=f"av:pos:{token}"),
            InlineKeyboardButton("📊 Performance", callback_data=f"av:perf:{token}"),
        ],
        [
            InlineKeyboardButton(
                "🧠 Strategy & Symbols", callback_data=f"av:str:{token}"
            ),
            InlineKeyboardButton("🛡 Account Risk", callback_data=f"av:risk:{token}"),
        ],
        [
            InlineKeyboardButton("↻ Refresh", callback_data=f"acc:{token}"),
            InlineKeyboardButton("🧾 Controls", callback_data=f"av:ctl:{token}"),
        ],
    ]
    if role >= TelegramRole.OPERATOR and account.enabled and not account.is_live:
        rows.append(
            [
                InlineKeyboardButton("⏸ Pause Entries", callback_data=f"ctl:p:{token}"),
                InlineKeyboardButton(
                    "▶ Resume Entries", callback_data=f"ctl:r:{token}"
                ),
            ]
        )
        rows.append(
            [InlineKeyboardButton("▶ Start Engine", callback_data=f"ctl:b:{token}")]
        )
    if role >= TelegramRole.OWNER:
        toggle = (
            "Enable Account" if not account.enabled else "Disable Account (flat only)"
        )
        rows.append(
            [InlineKeyboardButton(f"⛔ {toggle}", callback_data=f"acct:t:{token}")]
        )
    if role >= TelegramRole.OWNER and account.enabled and not account.is_live:
        rows.append(
            [
                InlineKeyboardButton(
                    "🚨 Emergency Close…", callback_data=f"safe:e:{token}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "‹ Home" if single_account_mode else "‹ Accounts",
                callback_data="nav:h" if single_account_mode else "nav:a:0",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def safety_keyboard(
    role: TelegramRole, *, single_account_mode: bool = False
) -> InlineKeyboardMarkup:
    rows = []
    if role >= TelegramRole.OPERATOR:
        rows.append(
            [
                InlineKeyboardButton(
                    "⏸ Pause Entries"
                    if single_account_mode
                    else "⏸ Pause All Entries",
                    callback_data="safe:p:all",
                ),
                InlineKeyboardButton(
                    "▶ Resume / Start"
                    if single_account_mode
                    else "▶ Resume / Start All",
                    callback_data="safe:r:all",
                ),
            ]
        )
    if role >= TelegramRole.OWNER:
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        "⏹ Stop Engine…"
                        if single_account_mode
                        else "⏹ Stop All Engines…",
                        callback_data="safe:s:all",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚨 Emergency Close…"
                        if single_account_mode
                        else "🚨 Emergency Close All…",
                        callback_data="safe:e:all",
                    )
                ],
            ]
        )
    rows.append([InlineKeyboardButton("‹ Home", callback_data="nav:h")])
    return InlineKeyboardMarkup(rows)


def confirmation_keyboard(nonce: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔐 Verify and Confirm", callback_data=f"confirm:{nonce}"
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data="confirm:cancel")],
        ]
    )


def back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("‹ Home", callback_data="nav:h")]]
    )


def add_platform_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("MetaTrader 5", callback_data="add:platform:MT5"),
                InlineKeyboardButton("MetaTrader 4", callback_data="add:platform:MT4"),
            ],
            [InlineKeyboardButton("Cancel", callback_data="add:cancel")],
        ]
    )


def add_broker_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Exness", callback_data="add:broker:EXNESS")],
            [InlineKeyboardButton("Other broker", callback_data="add:broker:OTHER")],
            [InlineKeyboardButton("Cancel", callback_data="add:cancel")],
        ]
    )


def add_environment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Demo", callback_data="add:env:DEMO"),
                InlineKeyboardButton("Live 🔒", callback_data="add:env:LIVE"),
            ],
            [InlineKeyboardButton("Cancel", callback_data="add:cancel")],
        ]
    )
