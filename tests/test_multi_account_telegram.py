import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from account_supervisor import AccountSupervisor
from accounts.credentials import (
    EnvironmentCredentialProvider,
    account_env_prefix,
)
from accounts.registry import (
    AccountEnvironment,
    AccountPlatform,
    AccountRegistry,
    TradingAccount,
    select_accounts_for_mode,
)
from accounts.snapshots import MultiAccountSnapshotReader, aggregate_views
from control_plane import ControlAction, ControlCommandStore
from execution.mt5_executor import ExecutionConfig, MT5Executor
from telegram_bot.menus import (
    account_keyboard,
    accounts_keyboard,
    home_keyboard,
    safety_keyboard,
    single_account_home_keyboard,
)
from telegram_bot.security import TelegramAccessPolicy, TelegramRole
from telegram_bot.totp import TotpVerifier


def mt5_account(account_id="demo_01", *, terminal_path="C:/MT5/terminal64.exe"):
    return TradingAccount(
        account_id=account_id,
        label=account_id.upper(),
        broker="Exness",
        platform="MT5",
        environment="DEMO",
        login="12345678",
        server="Exness-MT5Trial",
        terminal_path=terminal_path,
    )


def paper_account(account_id="paper_demo"):
    return TradingAccount(
        account_id=account_id,
        label="AAQTS Paper Demo",
        broker="AAQTS",
        platform="PAPER",
        environment="PAPER",
        login=account_id,
    )


def test_registry_persists_only_public_multi_account_metadata(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts.json", max_accounts=2)
    first = registry.add(mt5_account())
    second = registry.add(
        TradingAccount(
            account_id="mt4_01",
            label="MT4-01",
            broker="Exness",
            platform=AccountPlatform.MT4,
            environment=AccountEnvironment.DEMO,
            login="87654321",
            server="Exness-Trial",
            bridge_url="http://127.0.0.1:9001",
        )
    )

    restored = AccountRegistry(tmp_path / "accounts.json", max_accounts=2)
    assert restored.list_accounts() == (first, second)
    assert restored.resolve_token(first.callback_token) == first
    payload = (tmp_path / "accounts.json").read_text(encoding="utf-8").lower()
    assert "password" not in payload
    assert "bridge_token" not in payload


def test_registry_rejects_secret_fields_and_duplicate_broker_account(tmp_path):
    with pytest.raises(ValueError, match="sensitive"):
        TradingAccount.from_dict(
            {**mt5_account().as_public_dict(), "password": "do-not-store"}
        )

    registry = AccountRegistry(tmp_path / "accounts.json")
    registry.add(mt5_account())
    with pytest.raises(ValueError, match="already registered"):
        registry.add(
            TradingAccount(
                **{
                    **mt5_account("another_alias").as_public_dict(),
                    "label": "Another alias",
                }
            )
        )

    with pytest.raises(ValueError, match="loopback"):
        TradingAccount(
            account_id="unsafe_bridge",
            label="Unsafe",
            broker="Broker",
            platform="MT4",
            environment="DEMO",
            login="123",
            server="Server",
            bridge_url="http://localhost.evil.example/bridge",
        )
    with pytest.raises(ValueError, match="credentials"):
        TradingAccount(
            account_id="embedded_secret",
            label="Unsafe",
            broker="Broker",
            platform="MT4",
            environment="DEMO",
            login="456",
            server="Server",
            bridge_url="https://user:password@example.com/bridge",
        )


def test_single_account_scope_never_guesses_between_existing_accounts():
    first = mt5_account("first", terminal_path="C:/MT5-01/terminal64.exe")
    second = TradingAccount(
        **{
            **mt5_account(
                "second", terminal_path="C:/MT5-02/terminal64.exe"
            ).as_public_dict(),
            "login": "22222222",
        }
    )

    assert select_accounts_for_mode(
        (first,), single_account_mode=True
    ) == (first,)
    with pytest.raises(RuntimeError, match="AAQTS_PRIMARY_ACCOUNT_ID"):
        select_accounts_for_mode((first, second), single_account_mode=True)
    assert select_accounts_for_mode(
        (first, second),
        single_account_mode=True,
        primary_account_id="second",
    ) == (second,)
    assert select_accounts_for_mode(
        (first, second), single_account_mode=False
    ) == (first, second)


def test_environment_credentials_are_per_account_and_never_returned_publicly():
    account = mt5_account("demo_one")
    prefix = account_env_prefix(account.account_id)
    provider = EnvironmentCredentialProvider(
        {
            f"{prefix}_PASSWORD": "trading-secret",
            f"{prefix}_TERMINAL_PATH": "D:/MT5-01/terminal64.exe",
        }
    )

    credentials = provider.credentials(account)
    assert credentials.password == "trading-secret"
    assert provider.readiness(account).ready is True
    assert provider.public_status(account) == {"ready": True, "missing": ()}
    assert "trading-secret" not in json.dumps(provider.public_status(account))


class FakeMT5:
    def __init__(self):
        self.initialize_kwargs = None
        self.shutdown_calls = 0

    def initialize(self, **kwargs):
        self.initialize_kwargs = kwargs
        return True

    def shutdown(self):
        self.shutdown_calls += 1

    def last_error(self):
        return (1, "ok")

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def account_info(self):
        return SimpleNamespace(
            login=12345678,
            trade_allowed=True,
            trade_expert=True,
            balance=1000.0,
            equity=1010.0,
            profit=10.0,
            margin=20.0,
            margin_free=990.0,
        )

    def positions_get(self):
        return (
            SimpleNamespace(magic=20260730),
            SimpleNamespace(magic=999),
        )


def test_mt5_snapshot_uses_exact_registered_login_server_and_managed_positions():
    account = mt5_account()
    prefix = account_env_prefix(account.account_id)
    provider = EnvironmentCredentialProvider({f"{prefix}_PASSWORD": "secret"})
    mt5 = FakeMT5()
    reader = MultiAccountSnapshotReader(provider, mt5_module=mt5)

    view = reader.read(account)

    assert view.status == "CONNECTED"
    assert view.balance == 1000.0
    assert view.open_positions == 1
    assert mt5.initialize_kwargs == {
        "path": "C:/MT5/terminal64.exe",
        "login": 12345678,
        "password": "secret",
        "server": "Exness-MT5Trial",
    }
    assert mt5.shutdown_calls == 1
    assert aggregate_views((view,))["equity"] == 1010.0


def test_paper_snapshot_reads_fresh_worker_metrics(tmp_path):
    account = paper_account()
    state = {
        "account_id": account.account_id,
        "execution_mode": "PAPER",
        "status": "RUNNING",
        "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
        "starting_balance": 100.0,
        "balance": 103.0,
        "equity": 104.5,
        "floating_pnl": 1.5,
        "open_positions": 2,
        "closed_trades": 5,
        "wins": 3,
        "win_rate": 60.0,
        "total_pnl": 3.0,
    }
    (tmp_path / "aaqts_status_paper_demo.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    view = MultiAccountSnapshotReader(runtime_dir=tmp_path).read(account)

    assert view.status == "CONNECTED"
    assert view.starting_balance == 100.0
    assert view.balance == 103.0
    assert view.equity == 104.5
    assert view.floating_pnl == 1.5
    assert view.open_positions == 2
    assert view.closed_trades == 5
    assert view.wins == 3
    assert view.win_rate == 60.0
    assert view.total_pnl == 3.0


def test_paper_snapshot_fails_closed_without_a_fresh_worker(tmp_path):
    account = paper_account()
    reader = MultiAccountSnapshotReader(runtime_dir=tmp_path)
    assert reader.read(account).status == "OFFLINE"

    stale = {
        "account_id": account.account_id,
        "execution_mode": "PAPER",
        "status": "RUNNING",
        "heartbeat_utc": (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat(),
        "balance": 100.0,
    }
    (tmp_path / "aaqts_status_paper_demo.json").write_text(
        json.dumps(stale), encoding="utf-8"
    )
    assert reader.read(account).status == "STALE"


def test_execution_connector_authenticates_and_validates_expected_login():
    mt5 = FakeMT5()
    executor = MT5Executor(
        ExecutionConfig(
            terminal_path="C:/MT5/terminal64.exe",
            login=12345678,
            password="secret",
            server="Exness-MT5Trial",
        ),
        adapter=mt5,
    )

    assert executor.connect() is True
    assert mt5.initialize_kwargs == {
        "path": "C:/MT5/terminal64.exe",
        "login": 12345678,
        "password": "secret",
        "server": "Exness-MT5Trial",
    }


def test_control_store_isolated_per_account_and_records_result(tmp_path):
    store = ControlCommandStore(tmp_path / "control")
    first = store.submit(
        "demo_01",
        ControlAction.PAUSE_ENTRIES,
        requested_by=1001,
        reason="operator request",
    )
    store.submit(
        "demo_02",
        ControlAction.RESUME_ENTRIES,
        requested_by=1001,
        reason="operator request",
    )

    claimed = store.claim_next("demo_01")
    assert claimed == first
    assert store.claim_next("demo_01") is None
    store.complete(claimed, result="BOT PAUSED")
    recent = store.recent("demo_01")
    assert recent[-1]["status"] == "COMPLETED"
    assert recent[-1]["result"] == "BOT PAUSED"
    assert store.claim_next("demo_02").action is ControlAction.RESUME_ENTRIES

    stop = store.submit(
        "demo_01",
        ControlAction.STOP_ENGINE,
        requested_by=1001,
        reason="owner stop",
    )
    assert store.claim_next("demo_01") == stop
    store.complete(stop, result="BOT STOPPED")
    assert store.restart_blocked("demo_01") is True
    assert store.clear_restart_block("demo_01") is True
    assert store.restart_blocked("demo_01") is False


def test_telegram_roles_are_fail_closed_and_monotonic():
    policy = TelegramAccessPolicy.from_env(
        {
            "TELEGRAM_OWNER_IDS": "1",
            "TELEGRAM_RISK_MANAGER_IDS": "2",
            "TELEGRAM_OPERATOR_IDS": "3",
            "TELEGRAM_VIEWER_IDS": "4",
        }
    )

    assert policy.role_for(1) is TelegramRole.OWNER
    assert policy.allows(1, TelegramRole.OPERATOR)
    assert not policy.allows(3, TelegramRole.OWNER)
    assert policy.role_for(999) is None


def test_totp_matches_rfc6238_vector_and_rejects_wrong_code():
    verifier = TotpVerifier(
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        digits=8,
        window=0,
    )
    assert verifier.verify("94287082", now=59)
    assert not verifier.verify("94287081", now=59)
    assert not TotpVerifier("invalid!").verify("000000", now=59)


def test_all_telegram_callback_payloads_fit_bot_api_limit():
    accounts = tuple(mt5_account(f"account_{index}") for index in range(8))
    keyboards = (
        home_keyboard(TelegramRole.OWNER),
        accounts_keyboard(accounts, 0, TelegramRole.OWNER),
        account_keyboard(accounts[0], TelegramRole.OWNER),
        safety_keyboard(TelegramRole.OWNER),
        single_account_home_keyboard(TelegramRole.OWNER, accounts[0]),
        account_keyboard(
            accounts[0], TelegramRole.OWNER, single_account_mode=True
        ),
        safety_keyboard(TelegramRole.OWNER, single_account_mode=True),
    )
    callback_data = [
        button.callback_data
        for keyboard in keyboards
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert callback_data
    assert max(len(value.encode("utf-8")) for value in callback_data) <= 64


def test_single_account_menu_hides_parent_and_account_switching_controls():
    account = mt5_account("mine")
    setup = single_account_home_keyboard(TelegramRole.OWNER, None)
    setup_labels = [
        button.text for row in setup.inline_keyboard for button in row
    ]
    assert "➕ Set Up My Account" in setup_labels

    home = single_account_home_keyboard(TelegramRole.OWNER, account)
    labels = [button.text for row in home.inline_keyboard for button in row]
    assert "📊 Dashboard" in labels
    assert "📈 Positions" in labels
    assert "📈 Performance" in labels
    assert "🏦 Accounts" not in labels
    assert "📊 Portfolio" not in labels
    assert "➕ Add Account" not in labels

    details = account_keyboard(
        account, TelegramRole.OWNER, single_account_mode=True
    )
    back = details.inline_keyboard[-1][0]
    assert back.text == "‹ Home"
    assert back.callback_data == "nav:h"


def test_supervisor_skips_duplicate_mt5_terminal_paths(tmp_path, caplog):
    registry = AccountRegistry(tmp_path / "accounts.json")
    one = registry.add(mt5_account("one"))
    registry.add(
        TradingAccount(
            **{
                **mt5_account("two").as_public_dict(),
                "login": "22222222",
            }
        )
    )
    prefixes = [
        account_env_prefix(item.account_id) for item in registry.list_accounts()
    ]
    provider = EnvironmentCredentialProvider(
        {
            f"{prefixes[0]}_PASSWORD": "one-secret",
            f"{prefixes[1]}_PASSWORD": "two-secret",
        }
    )
    supervisor = AccountSupervisor(
        registry, credentials=provider, project_root=tmp_path
    )

    eligible = supervisor.eligible_accounts()

    assert eligible == (one,)
    assert "already assigned" in caplog.text


def test_supervisor_single_account_mode_starts_only_explicit_primary(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts.json")
    first = registry.add(mt5_account("first", terminal_path="C:/MT5-01/terminal64.exe"))
    second = registry.add(
        TradingAccount(
            **{
                **mt5_account(
                    "second", terminal_path="C:/MT5-02/terminal64.exe"
                ).as_public_dict(),
                "login": "22222222",
            }
        )
    )
    env = {}
    for account in (first, second):
        env[f"{account_env_prefix(account.account_id)}_PASSWORD"] = "secret"
    supervisor = AccountSupervisor(
        registry,
        credentials=EnvironmentCredentialProvider(env),
        project_root=tmp_path,
        single_account_mode=True,
        primary_account_id="second",
    )

    assert supervisor.eligible_accounts() == (second,)
