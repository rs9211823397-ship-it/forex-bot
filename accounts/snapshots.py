"""Read-only multi-account snapshots for the Telegram parent dashboard."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from accounts.credentials import EnvironmentCredentialProvider
from accounts.registry import AccountPlatform, TradingAccount
from execution.mt5_executor import AAQTS_MAGIC

_MT5_LOCK = threading.RLock()


@dataclass(frozen=True)
class AccountView:
    account_id: str
    status: str
    balance: float = 0.0
    equity: float = 0.0
    floating_pnl: float = 0.0
    margin_used: float = 0.0
    free_margin: float = 0.0
    open_positions: int = 0
    reason: str = ""
    as_of_utc: str = ""

    @property
    def connected(self) -> bool:
        return self.status == "CONNECTED"


class MultiAccountSnapshotReader:
    """Dispatch non-mutating account reads to MT5 or an MT4 bridge."""

    def __init__(
        self,
        credentials: EnvironmentCredentialProvider | None = None,
        *,
        mt5_module: Any = None,
        urlopen_fn: Callable[..., Any] = urlopen,
        timeout_seconds: float = 8.0,
    ):
        self.credentials = credentials or EnvironmentCredentialProvider()
        self._mt5_module = mt5_module
        self._urlopen = urlopen_fn
        self.timeout_seconds = float(timeout_seconds)

    def read(self, account: TradingAccount) -> AccountView:
        if not account.enabled:
            return self._view(account, "DISABLED", reason="Account is disabled")
        readiness = self.credentials.readiness(account)
        if not readiness.ready:
            return self._view(
                account,
                "SETUP_REQUIRED",
                reason="Missing host configuration: " + ", ".join(readiness.missing),
            )
        if account.platform is AccountPlatform.PAPER:
            return self._view(
                account,
                "CONNECTED",
                reason="Paper account registered",
            )
        if account.platform is AccountPlatform.MT5:
            return self._read_mt5(account)
        if account.platform is AccountPlatform.MT4:
            return self._read_mt4_bridge(account)
        return self._view(account, "UNSUPPORTED", reason="Unsupported platform")

    def read_many(
        self, accounts: tuple[TradingAccount, ...]
    ) -> tuple[AccountView, ...]:
        # MetaTrader5 exposes process-global terminal state. Serial reads avoid
        # cross-account leakage and each read validates the returned login.
        return tuple(self.read(account) for account in accounts)

    def _mt5(self):
        if self._mt5_module is not None:
            return self._mt5_module
        try:
            import MetaTrader5 as mt5
        except ImportError as exc:
            raise RuntimeError("MetaTrader5 package is unavailable") from exc
        return mt5

    def _read_mt5(self, account: TradingAccount) -> AccountView:
        credentials = self.credentials.credentials(account)
        try:
            login = int(account.login)
        except ValueError:
            return self._view(
                account,
                "AUTH_FAILED",
                reason="MT5 login must be numeric",
            )

        try:
            mt5 = self._mt5()
        except RuntimeError as exc:
            return self._view(account, "TERMINAL_UNAVAILABLE", reason=str(exc))

        with _MT5_LOCK:
            initialized = False
            try:
                initialized = bool(
                    mt5.initialize(
                        path=credentials.terminal_path,
                        login=login,
                        password=credentials.password,
                        server=account.server,
                    )
                )
                if not initialized:
                    return self._view(
                        account,
                        "AUTH_FAILED",
                        reason=f"MT5 initialization failed: {mt5.last_error()}",
                    )
                terminal = mt5.terminal_info()
                info = mt5.account_info()
                if terminal is None or info is None:
                    return self._view(
                        account,
                        "TERMINAL_UNAVAILABLE",
                        reason="Terminal/account information is unavailable",
                    )
                returned_login = str(getattr(info, "login", ""))
                if returned_login != account.login:
                    return self._view(
                        account,
                        "AUTH_FAILED",
                        reason="Connected terminal returned a different account",
                    )
                positions = [
                    position
                    for position in list(mt5.positions_get() or [])
                    if getattr(position, "magic", None) == AAQTS_MAGIC
                ]
                status = (
                    "CONNECTED" if getattr(terminal, "connected", True) else "DEGRADED"
                )
                reason = ""
                if not getattr(info, "trade_allowed", False):
                    status = "TRADING_DISABLED"
                    reason = "Trading is disabled on this account"
                return AccountView(
                    account_id=account.account_id,
                    status=status,
                    balance=float(getattr(info, "balance", 0.0) or 0.0),
                    equity=float(getattr(info, "equity", 0.0) or 0.0),
                    floating_pnl=float(getattr(info, "profit", 0.0) or 0.0),
                    margin_used=float(getattr(info, "margin", 0.0) or 0.0),
                    free_margin=float(getattr(info, "margin_free", 0.0) or 0.0),
                    open_positions=len(positions),
                    reason=reason,
                    as_of_utc=datetime.now(timezone.utc).isoformat(),
                )
            except Exception as exc:  # noqa: BLE001 - third-party MT5 boundary
                return self._view(
                    account,
                    "TERMINAL_UNAVAILABLE",
                    reason=f"MT5 read failed: {exc}",
                )
            finally:
                if initialized:
                    mt5.shutdown()

    def _read_mt4_bridge(self, account: TradingAccount) -> AccountView:
        credentials = self.credentials.credentials(account)
        query = urlencode({"login": account.login})
        request = Request(
            f"{account.bridge_url}/v1/account/snapshot?{query}",
            headers={
                "Authorization": f"Bearer {credentials.bridge_token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            returned_login = str(payload.get("login", ""))
            if returned_login != account.login:
                return self._view(
                    account,
                    "AUTH_FAILED",
                    reason="MT4 bridge returned a different account",
                )
            return AccountView(
                account_id=account.account_id,
                status=str(payload.get("status", "CONNECTED")).upper(),
                balance=float(payload.get("balance", 0.0)),
                equity=float(payload.get("equity", 0.0)),
                floating_pnl=float(payload.get("floating_pnl", 0.0)),
                margin_used=float(payload.get("margin_used", 0.0)),
                free_margin=float(payload.get("free_margin", 0.0)),
                open_positions=int(payload.get("open_positions", 0)),
                reason=str(payload.get("reason", "")),
                as_of_utc=str(
                    payload.get("as_of_utc", datetime.now(timezone.utc).isoformat())
                ),
            )
        except Exception as exc:  # noqa: BLE001 - HTTP/JSON bridge boundary
            return self._view(
                account,
                "BRIDGE_UNAVAILABLE",
                reason=f"MT4 bridge read failed: {exc}",
            )

    @staticmethod
    def _view(account: TradingAccount, status: str, *, reason: str = "") -> AccountView:
        return AccountView(
            account_id=account.account_id,
            status=status,
            reason=reason,
            as_of_utc=datetime.now(timezone.utc).isoformat(),
        )


def aggregate_views(views: tuple[AccountView, ...]) -> dict[str, float | int]:
    return {
        "accounts": len(views),
        "connected": sum(view.connected for view in views),
        "balance": sum(view.balance for view in views),
        "equity": sum(view.equity for view in views),
        "floating_pnl": sum(view.floating_pnl for view in views),
        "open_positions": sum(view.open_positions for view in views),
        "issues": sum(view.status not in {"CONNECTED", "DISABLED"} for view in views),
    }
