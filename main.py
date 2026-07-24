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

    print("=" * 50)
    print("AI MULTI-ASSET TRADING PLATFORM")
    print("=" * 50)

    all_data = market.download_all_data()

    print("\nMarket Signals:\n")


    for symbol, data in all_data.items():

        if bot.status() != "RUNNING":
            break

        try:

            analyzed_data = indicator.add_indicators(data)

            signal = signal_engine.generate_signal(analyzed_data)

            logger.log_signal(
                symbol,
                signal["signal"],
                signal["confidence"]
            )


            trade = trade_manager.calculate_trade(
                analyzed_data,
                signal
            )


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
                        risk_plan["take_profit"]
                    )

                    print("\nPaper Trade Opened:")
                    print(paper_trade)

            print("\n" + "=" * 50)
            print(f"Asset: {symbol}")
            print(f"Signal: {signal['signal']}")
            print(f"Confidence: {signal['confidence']}%")
            print(f"Score: {signal['score']}")

            print(f"Current Price: {trade['current_price']:.4f}")
            print(f"ATR: {trade['atr']:.4f}")


            if risk_plan:

                print("\nTrade Plan:")
                print(f"Entry: {risk_plan['entry']}")
                print(f"Stop Loss: {risk_plan['stop_loss']}")
                print(f"Take Profit: {risk_plan['take_profit']}")
                print(f"Risk Reward: 1:{risk_plan['risk_reward']}")
                print(f"Position Size: {position}")


            print("\nReasons:")

            for reason in signal["reasons"]:
                print(f"  ✓ {reason}")

            if paper_trader.open_trades:

                print("\nOpen Paper Trades:")

                for trade in paper_trader.open_trades:
                    print(
                        f"{trade['symbol']} | "
                        f"{trade['signal']} | "
                        f"Entry: {trade['entry']} | "
                        f"SL: {trade['stop_loss']} | "
                        f"TP: {trade['take_profit']} | "
                        f"Status: {trade['status']}"
                    )


            stats = paper_trader.get_stats()

            print("\nPaper Trading Stats:")
            print(f"Total Trades: {stats['total_trades']}")
            print(f"Wins: {stats['wins']}")
            print(f"Win Rate: {stats['win_rate']}%")
            print(f"Total P/L: {stats['total_pnl']}")



        except Exception as e:
            print(symbol, "ERROR:", e)



if __name__ == "__main__":

    from bot_loop import BotLoop

    print("\nBot Status:", bot.start_bot())

    loop = BotLoop(interval=10)

    loop.start(run_bot)