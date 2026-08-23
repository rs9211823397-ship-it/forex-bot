from accounts.registry import AccountRegistry, TradingAccount
from scripts.register_winprofx_live_account import register_winprofx_live_account


def test_register_winprofx_replaces_old_single_account_metadata(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts_registry.json")
    registry.add(
        TradingAccount(
            account_id="exness_demo",
            label="Exness Demo",
            broker="Exness",
            platform="MT5",
            environment="DEMO",
            login="123456",
            server="Exness-Demo",
            terminal_path=r"C:\Exness\terminal64.exe",
        )
    )

    registered = register_winprofx_live_account(
        runtime_dir=tmp_path,
        account_id="winprofx_live",
        login="237361",
        server="Winprofx-Live",
        terminal_path=r"C:\Winprofx\terminal64.exe",
    )

    records = AccountRegistry(tmp_path / "accounts_registry.json").list_accounts()
    assert records == (registered,)
    assert registered.environment.value == "LIVE"
    assert registered.platform.value == "MT5"
    assert registered.enabled is True


def test_register_winprofx_is_idempotent(tmp_path):
    kwargs = {
        "runtime_dir": tmp_path,
        "account_id": "winprofx_live",
        "login": "237361",
        "server": "Winprofx-Live",
        "terminal_path": r"C:\Winprofx\terminal64.exe",
    }

    first = register_winprofx_live_account(**kwargs)
    second = register_winprofx_live_account(**kwargs)

    assert first == second
    assert AccountRegistry(tmp_path / "accounts_registry.json").list_accounts() == (
        second,
    )
