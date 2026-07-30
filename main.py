from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager
from execution.execution_router import ExecutionRouter
from risk.risk_manager import RiskManager
from bot_controller import BotController
from logs.logger import TradeLogger
from config.settings import ACCOUNT_BALANCE, EXECUTION_MODE
from paper.paper_trader import PaperTrader


market = MarketData()
indicator = TechnicalIndicators()
signal_engine = SignalEngine()
trade_manager = TradeManager()
risk_manager = RiskManager()
bot = BotController()
logger = TradeLogger()
paper_trader = PaperTrader()
execution = ExecutionRouter(paper_trader=paper_trader)


def run_bot():

    print("=" * 60)
    print("AI MULTI-ASSET TRADING PLATFORM")
    print(f"EXECUTION MODE: {EXECUTION_MODE}")
    print("=" * 60)

    all_data = market.download_all_data()

    higher_tf_data = market.download_all_data(
        interval="1h"
    )

    # Current prices for paper-equity calculation
    current_prices = {}

    print("\nMarket Signals:\n")

    for symbol, data in all_data.items():

        if bot.status() != "RUNNING":
            break

        try:

            analyzed_data = indicator.add_indicators(data)

            signal = signal_engine.generate_signal(
                analyzed_data,
                symbol,
                higher_tf_data.get(symbol)
            )

            logger.log_signal(
                symbol,
                signal["signal"],
                signal["confidence"]
            )

            trade = trade_manager.calculate_trade(
                analyzed_data,
                signal
            )

            current_prices[symbol] = trade["current_price"]

            risk_plan = None
            position = None

            if signal["signal"] != "HOLD":

                risk_plan = risk_manager.calculate_trade_levels(
                    signal["signal"],
                    trade["current_price"],
                    trade["atr"]
                )

                if risk_plan:

                    position = risk_manager.position_size(
                        ACCOUNT_BALANCE,
                        risk_plan["entry"],
                        risk_plan["stop_loss"]
                    )

                    logger.log_trade(
                        symbol,
                        risk_plan,
                        position
                    )

                    execution_result = execution.execute(
                        source_symbol=symbol,
                        signal=signal["signal"],
                        risk_plan=risk_plan,
                        paper_position_size=position,
                    )

                    if execution_result:
                        print(f"\n{EXECUTION_MODE} Trade Result:")
                        print(execution_result)

            print("\n" + "=" * 60)
            print(f"Asset      : {symbol}")
            print(f"Signal     : {signal['signal']}")
            print(f"Confidence : {signal['confidence']}%")
            print(f"Score      : {signal['score']}")
            print(f"Price      : {trade['current_price']:.4f}")
            print(f"ATR        : {trade['atr']:.4f}")

            # Paper positions need local price checks. MT5 positions use
            # broker-side SL/TP and are recovered/managed through MT5.
            if EXECUTION_MODE == "PAPER":
                paper_trader.check_trade(
                    symbol,
                    trade["current_price"]
                )

            if risk_plan:

                print("\nTrade Plan")
                print(f"Entry         : {risk_plan['entry']}")
                print(f"Stop Loss     : {risk_plan['stop_loss']}")
                print(f"Take Profit   : {risk_plan['take_profit']}")
                print(f"Risk Reward   : 1:{risk_plan['risk_reward']}")
                print(f"Position Size : {position}")

            print("\nReasons:")

            for reason in signal["reasons"]:
                print(f"  ✓ {reason}")

        except Exception as e:
            print(symbol, "ERROR:", e)

    if EXECUTION_MODE == "PAPER":
        # -------- PAPER ACCOUNT SUMMARY --------
        paper_trader.update_equity(current_prices)
        stats = paper_trader.get_stats()

        print("\n" + "=" * 60)
        print("PAPER ACCOUNT")
        print("=" * 60)

        print(f"Starting Balance : ${stats['starting_balance']:.2f}")
        print(f"Balance          : ${stats['balance']:.2f}")
        print(f"Floating P/L     : ${stats['floating_pnl']:.2f}")
        print(f"Equity           : ${stats['equity']:.2f}")

        print("\nTrading Statistics")
        print(f"Open Trades      : {len(paper_trader.open_trades)}")
        print(f"Closed Trades    : {stats['total_trades']}")
        print(f"Wins             : {stats['wins']}")
        print(f"Win Rate         : {stats['win_rate']}%")
        print(f"Net P/L          : {stats['total_pnl']:.2f}")

        if paper_trader.open_trades:

            print("\nOpen Positions")

            for open_trade in paper_trader.open_trades:

                current = current_prices.get(
                    open_trade["symbol"],
                    open_trade["entry"]
                )

                if open_trade["signal"] == "BUY":
                    floating = (
                        current - open_trade["entry"]
                    ) * open_trade["position"]
                else:
                    floating = (
                        open_trade["entry"] - current
                    ) * open_trade["position"]

                print(
                    f"{open_trade['symbol']} | "
                    f"{open_trade['signal']} | "
                    f"Entry: {open_trade['entry']} | "
                    f"Current: {current:.4f} | "
                    f"Position: {open_trade['position']} | "
                    f"Floating P/L: {floating:.4f} | "
                    f"SL: {open_trade['stop_loss']} | "
                    f"TP: {open_trade['take_profit']}"
                )
    else:
        print("\n" + "=" * 60)
        print(f"AAQTS MT5 Positions: {len(execution.positions())}")

    print("=" * 60)


if __name__ == "__main__":
    from bot_loop import BotLoop

    recovered = execution.start()
    print(f"\nExecution Mode: {EXECUTION_MODE}")
    if recovered:
        print(f"Recovered AAQTS MT5 positions: {len(recovered)}")

    print("Bot Status:", bot.start_bot())
    loop = BotLoop(interval=10)
    loop.start(run_bot)
