"""Launch one isolated AAQTS worker process per enabled trading account."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from accounts.credentials import EnvironmentCredentialProvider
from accounts.registry import (
    AccountEnvironment,
    AccountPlatform,
    AccountRegistry,
    TradingAccount,
    select_accounts_for_mode,
)
from config.settings import PRIMARY_ACCOUNT_ID, SINGLE_ACCOUNT_MODE
from control_plane import ControlCommandStore

logger = logging.getLogger("aaqts.account-supervisor")


class AccountSupervisor:
    """Keep safe demo/paper workers isolated by account and terminal path."""

    def __init__(
        self,
        registry: AccountRegistry,
        *,
        credentials: EnvironmentCredentialProvider | None = None,
        project_root: str | Path | None = None,
        runtime_dir: str | Path | None = None,
        single_account_mode: bool = False,
        primary_account_id: str = "",
    ):
        self.registry = registry
        self.credentials = credentials or EnvironmentCredentialProvider()
        self.project_root = Path(project_root or Path(__file__).resolve().parent)
        self.runtime_dir = Path(runtime_dir or self.project_root / "runtime")
        if not self.runtime_dir.is_absolute():
            self.runtime_dir = self.project_root / self.runtime_dir
        self.commands = ControlCommandStore(self.runtime_dir / "control")
        self.single_account_mode = bool(single_account_mode)
        self.primary_account_id = str(primary_account_id).strip().lower()
        self.processes: dict[str, subprocess.Popen] = {}
        self.retry_after: dict[str, float] = {}
        self.running = True

    def eligible_accounts(self) -> tuple[TradingAccount, ...]:
        try:
            accounts = select_accounts_for_mode(
                self.registry.list_accounts(),
                single_account_mode=self.single_account_mode,
                primary_account_id=self.primary_account_id,
                enabled_only=True,
            )
        except RuntimeError as exc:
            logger.error("Account supervisor is locked: %s", exc)
            return ()
        terminal_owners: dict[str, str] = {}
        eligible = []
        for account in accounts:
            if account.environment is AccountEnvironment.LIVE:
                logger.warning("Skipping locked live account %s", account.account_id)
                continue
            if self.commands.restart_blocked(account.account_id):
                logger.info(
                    "Skipping intentionally stopped account %s",
                    account.account_id,
                )
                continue
            readiness = self.credentials.readiness(account)
            if not readiness.ready:
                logger.warning(
                    "Skipping account %s; setup missing: %s",
                    account.account_id,
                    ", ".join(readiness.missing),
                )
                continue
            if account.platform is AccountPlatform.MT5:
                terminal = self.credentials.credentials(
                    account
                ).terminal_path.casefold()
                owner = terminal_owners.get(terminal)
                if owner is not None:
                    logger.error(
                        "Skipping %s: MT5 terminal path is already assigned to %s",
                        account.account_id,
                        owner,
                    )
                    continue
                terminal_owners[terminal] = account.account_id
            eligible.append(account)
        return tuple(eligible)

    def start_account(self, account: TradingAccount) -> subprocess.Popen:
        if account.account_id in self.processes:
            return self.processes[account.account_id]
        environment = dict(os.environ)
        environment.update(
            {
                "AAQTS_ACCOUNT_ID": account.account_id,
                "AAQTS_ACCOUNT_STATE_DIR": str(
                    self.runtime_dir / "accounts" / account.account_id
                ),
                "AAQTS_RUNTIME_DIR": str(self.runtime_dir),
                "AAQTS_CONTROL_QUEUE_DIR": str(self.runtime_dir / "control"),
                "PYTHONUNBUFFERED": "1",
            }
        )
        if account.platform is AccountPlatform.PAPER:
            environment["AAQTS_EXECUTION_MODE"] = "PAPER"
            command = [sys.executable, "main.py"]
        elif account.platform is AccountPlatform.MT5:
            credentials = self.credentials.credentials(account)
            use_session = credentials.use_preauthenticated_session
            environment.update(
                {
                    "AAQTS_EXECUTION_MODE": "MT5_DEMO",
                    "AAQTS_MT5_LOGIN": "" if use_session else account.login,
                    "AAQTS_MT5_EXPECTED_LOGIN": account.login,
                    "AAQTS_MT5_PASSWORD": "" if use_session else credentials.password,
                    "AAQTS_MT5_SERVER": "" if use_session else account.server,
                    "AAQTS_MT5_TERMINAL_PATH": credentials.terminal_path,
                }
            )
            command = [sys.executable, "main.py"]
        elif account.platform is AccountPlatform.MT4:
            command = [
                sys.executable,
                "-m",
                "accounts.mt4_bridge_worker",
                "--account-id",
                account.account_id,
            ]
        else:  # pragma: no cover
            raise ValueError(f"Unsupported platform: {account.platform}")
        process = subprocess.Popen(
            command,
            cwd=self.project_root,
            env=environment,
        )
        self.processes[account.account_id] = process
        logger.info(
            "Started account worker %s (pid=%s)", account.account_id, process.pid
        )
        return process

    def start_all(self) -> None:
        for account in self.eligible_accounts():
            self.start_account(account)

    def reconcile(self) -> None:
        """Start newly registered workers and stop disabled/removed workers."""

        desired = {account.account_id: account for account in self.eligible_accounts()}
        for account_id, process in tuple(self.processes.items()):
            if account_id in desired:
                continue
            if process.poll() is None:
                process.terminate()
            self.processes.pop(account_id, None)
            logger.info("Stopped account worker %s", account_id)
        for account_id, account in desired.items():
            process = self.processes.get(account_id)
            if process is None or process.poll() is not None:
                if time.monotonic() < self.retry_after.get(account_id, 0.0):
                    continue
                if process is not None:
                    self.processes.pop(account_id, None)
                self.start_account(account)

    def reap(self) -> None:
        for account_id, process in tuple(self.processes.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            logger.warning(
                "Account worker %s exited with code %s",
                account_id,
                return_code,
            )
            self.processes.pop(account_id, None)
            self.retry_after[account_id] = time.monotonic() + 10.0

    def stop_all(self) -> None:
        self.running = False
        for process in self.processes.values():
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 10
        for process in self.processes.values():
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
        self.processes.clear()

    def run(self) -> None:
        while self.running:
            self.reap()
            self.reconcile()
            time.sleep(1)


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    project_root = Path(__file__).resolve().parent
    runtime_dir = Path(os.getenv("AAQTS_RUNTIME_DIR", "runtime"))
    if not runtime_dir.is_absolute():
        runtime_dir = project_root / runtime_dir
    supervisor = AccountSupervisor(
        AccountRegistry(
            runtime_dir / "accounts_registry.json",
            max_accounts=1 if SINGLE_ACCOUNT_MODE else 100,
        ),
        project_root=project_root,
        runtime_dir=runtime_dir,
        single_account_mode=SINGLE_ACCOUNT_MODE,
        primary_account_id=PRIMARY_ACCOUNT_ID,
    )

    def shutdown(signum, frame):
        del signum, frame
        supervisor.stop_all()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        supervisor.run()
    finally:
        supervisor.stop_all()


if __name__ == "__main__":
    main()
