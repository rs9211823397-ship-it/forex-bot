from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager
from risk.risk_manager import RiskManager
from bot_controller import BotController
from logs.logger import TradeLogger

market = MarketData()
indicator = TechnicalIndicators()
signal_engine = SignalEngine()
trade_manager = TradeManager()
risk_manager = RiskManager()
bot = BotController()
logger = TradeLogger()

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


            print("\n" + "=" * 50)
            print(f"Asset: {symbol}")
            print(f"Signal: {signal['signal']}")
            print(f"Confidence: {signal['confidence']}%")
            print(f"Score: {signal['score']}")

            print(f"Current Price: {trade['current_price']:.4f}")
            print(f"ATR: {trade['atr']:.4f}")


            print("\nReasons:")

            for reason in signal["reasons"]:
                print(f"  ✓ {reason}")


        except Exception as e:
            print(symbol, "ERROR:", e)



if __name__ == "__main__":

    from bot_loop import BotLoop

    print("\nBot Status:", bot.start_bot())

    loop = BotLoop(interval=10)

    loop.start(run_bot)