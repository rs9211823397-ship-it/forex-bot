"""Consume AAQTS control commands for one externally hosted MT4 bridge."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from accounts.credentials import EnvironmentCredentialProvider
from accounts.registry import AccountPlatform, AccountRegistry
from control_plane import ControlAction, ControlCommandStore, ControlRequest
from runtime_state import write_runtime_state


class MT4BridgeWorker:
    def __init__(
        self,
        account_id: str,
        *,
        registry: AccountRegistry,
        commands: ControlCommandStore,
        credentials: EnvironmentCredentialProvider | None = None,
    ):
        self.account = registry.get(account_id)
        if self.account.platform is not AccountPlatform.MT4:
            raise ValueError("MT4 bridge worker requires an MT4 account")
        self.commands = commands
        self.credentials = credentials or EnvironmentCredentialProvider()
        readiness = self.credentials.readiness(self.account)
        if not readiness.ready:
            raise RuntimeError(
                "MT4 bridge setup is incomplete: " + ", ".join(readiness.missing)
            )
        self.running = True

    def handle(self, request: ControlRequest) -> str:
        token = self.credentials.credentials(self.account).bridge_token
        payload = json.dumps(
            {
                "request_id": request.request_id,
                "login": self.account.login,
                "action": request.action.value,
                "reason": request.reason,
            }
        ).encode("utf-8")
        endpoint = f"{self.account.bridge_url}/v1/control"
        http_request = Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(http_request, timeout=10.0) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not bool(result.get("success", False)):
            raise RuntimeError(str(result.get("message", "MT4 bridge rejected action")))
        if request.action in {
            ControlAction.STOP_ENGINE,
            ControlAction.EMERGENCY_CLOSE,
        }:
            self.running = False
        return str(result.get("message", request.action.value))

    def run(self) -> None:
        write_runtime_state(
            account_id=self.account.account_id,
            status="RUNNING",
            phase="MT4_BRIDGE_CONTROL",
            execution_mode=self.account.environment.value,
        )
        try:
            while self.running:
                self.commands.process_available(
                    self.account.account_id,
                    self.handle,
                )
                time.sleep(1)
        finally:
            write_runtime_state(
                account_id=self.account.account_id,
                status="STOPPED",
                phase="MT4_BRIDGE_SHUTDOWN",
                execution_mode=self.account.environment.value,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", required=True)
    args = parser.parse_args()
    runtime_dir = Path(os.getenv("AAQTS_RUNTIME_DIR", "runtime"))
    worker = MT4BridgeWorker(
        args.account_id,
        registry=AccountRegistry(runtime_dir / "accounts_registry.json"),
        commands=ControlCommandStore(runtime_dir / "control"),
    )
    worker.run()


if __name__ == "__main__":
    main()
