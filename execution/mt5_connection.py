
import MetaTrader5 as mt5

TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

print("="*60)
print("AAQTS MT5 CONNECTION TEST")
print("="*60)

if not mt5.initialize(path=TERMINAL_PATH):
    print("Initialize failed:", mt5.last_error())
    raise SystemExit

terminal = mt5.terminal_info()
account = mt5.account_info()

print("Terminal:", terminal)
print("Account :", account)

if account:
    print("="*60)
    print("CONNECTED SUCCESSFULLY")
    print("Login   :", account.login)
    print("Server  :", account.server)
    print("Balance :", account.balance)
    print("Equity  :", account.equity)
    print("Profit  :", account.profit)
    print("="*60)

mt5.shutdown()
