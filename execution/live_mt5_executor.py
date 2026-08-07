"""Fail-closed MT5 executor for explicitly authorized real-money trading.

This class reuses the validated order/sizing implementation from MT5Executor
but changes connection validation so only a pinned REAL account is accepted.
It never permits an unpinned session and it verifies the configured server.
"""

from __future__ import annotations

from execution.mt5_executor import ExecutionError, MT5Executor


class LiveMT5Executor(MT5Executor):
    """MT5Executor variant that accepts only the explicitly pinned REAL account."""

    def connect(self) -> bool:
        if self.config.expected_login is None:
            raise ExecutionError("MT5_LIVE requires a pinned expected login")
        if not str(self.config.server or "").strip():
            raise ExecutionError("MT5_LIVE requires an explicitly pinned/expected server")

        kwargs = {}
        if self.config.terminal_path:
            kwargs["path"] = self.config.terminal_path
        if self.config.login is not None:
            if not self.config.password or not self.config.server:
                raise ExecutionError("Explicit MT5 login requires both password and server")
            kwargs.update(
                login=int(self.config.login),
                password=self.config.password,
                server=self.config.server,
            )

        self.connected = bool(self.mt5.initialize(**kwargs))
        if not self.connected:
            raise ExecutionError(f"MT5 initialization failed: {self.mt5.last_error()}")

        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if terminal is None or account is None:
            self.shutdown()
            raise ExecutionError("MT5 terminal/account information is unavailable")

        actual_login = int(getattr(account, "login", -1))
        if actual_login != int(self.config.expected_login):
            self.shutdown()
            raise ExecutionError("MT5_LIVE connected to an unexpected account login")

        actual_server = str(getattr(account, "server", "") or "").strip()
        if actual_server.lower() != str(self.config.server).strip().lower():
            self.shutdown()
            raise ExecutionError("MT5_LIVE connected to an unexpected server")

        real_mode = getattr(self.mt5, "ACCOUNT_TRADE_MODE_REAL", 2)
        if getattr(account, "trade_mode", None) != real_mode:
            self.shutdown()
            raise ExecutionError("MT5_LIVE requires a REAL broker account; demo/contest accounts are blocked")

        if not getattr(terminal, "trade_allowed", False):
            self.shutdown()
            raise ExecutionError("Algorithmic trading is disabled in the MT5 terminal")
        if not getattr(account, "trade_allowed", False) or not getattr(account, "trade_expert", False):
            self.shutdown()
            raise ExecutionError("Trading or expert trading is disabled on the live account")
        return True


__all__ = ["LiveMT5Executor"]
