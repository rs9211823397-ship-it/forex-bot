"""Manual, no-order MT5 connectivity diagnostic."""

from config.settings import MT5_TERMINAL_PATH


def main() -> None:
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError(
            "MetaTrader5 is optional and available only on the Windows MT5 host."
        ) from exc

    print("=" * 60)
    print("AAQTS MT5 CONNECTION TEST")
    print("=" * 60)

    if not mt5.initialize(path=MT5_TERMINAL_PATH):
        raise RuntimeError(f"Initialize failed: {mt5.last_error()}")

    try:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        print("Terminal:", terminal)
        print("Account :", account)
        if account:
            print("=" * 60)
            print("CONNECTED SUCCESSFULLY")
            print("Login   :", account.login)
            print("Server  :", account.server)
            print("Balance :", account.balance)
            print("Equity  :", account.equity)
            print("Profit  :", account.profit)
            print("=" * 60)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
