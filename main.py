from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager
from risk.risk_manager import RiskManager
from bot_controller import BotController
from logs.logger import TradeLogger
from config.settings import ACCOUNT_BALANCE
from paper.paper_trader import PaperTrader


market = MarketData()
indicator = TechnicalIndicators()
signal_engine = SignalEngine()
trade_manager = TradeManager()
risk_manager = RiskManager()
bot = BotController()
logger = TradeLogger()
paper_trader = PaperTrader()


def run_bot():

    print("=" * 60)
    print("AI MULTI-ASSET TRADING PLATFORM")
    print("=" * 60)

    all_data = market.download_all_data()

    # Current prices for equity calculation
    current_prices = {}

    print("\nMarket Signals:\n")

    for symbol, data in all_data.items():

        if bot.status() != "RUNNING":
            break

        try:

            analyzed_data = indicator.add_indicators(data)

            signal = signal_engine.generate_signal(
                analyzed_data,
                symbol
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

                    paper_trade = paper_trader.open_trade(
                        symbol,
                        signal["signal"],
                        risk_plan["entry"],
                        risk_plan["stop_loss"],
                        risk_plan["take_profit"],
                        position
                    )

                    if paper_trade:
                        print("\nPaper Trade Opened:")
                        print(paper_trade)

            print("\n" + "=" * 60)
            print(f"Asset      : {symbol}")
            print(f"Signal     : {signal['signal']}")
            print(f"Confidence : {signal['confidence']}%")
            print(f"Score      : {signal['score']}")
            print(f"Price      : {trade['current_price']:.4f}")
            print(f"ATR        : {trade['atr']:.4f}")

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

    # -------- ACCOUNT SUMMARY --------

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

        for trade in paper_trader.open_trades:

            current = current_prices.get(
                trade["symbol"],
                trade["entry"]
            )

            if trade["signal"] == "BUY":

                floating = (
                    current - trade["entry"]
                ) * trade["position"]

            else:

                floating = (
                    trade["entry"] - current
                ) * trade["position"]


            print(
                f"{trade['symbol']} | "
                f"{trade['signal']} | "
                f"Entry: {trade['entry']} | "
                f"Current: {current:.4f} | "
                f"Position: {trade['position']} | "
                f"Floating P/L: {floating:.4f} | "
                f"SL: {trade['stop_loss']} | "
                f"TP: {trade['take_profit']}"
            )

    print("=" * 60)


if __name__ == "__main__":

    from bot_loop import BotLoop

    print("\nBot Status:", bot.start_bot())

    loop = BotLoop(interval=10)

    loop.start(run_bot)