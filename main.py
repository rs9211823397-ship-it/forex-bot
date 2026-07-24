from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager

print("=" * 50)
print("AI MULTI-ASSET TRADING PLATFORM")
print("=" * 50)


market = MarketData()
indicator = TechnicalIndicators()
signal_engine = SignalEngine()
trade_manager = TradeManager()

all_data = market.download_all_data()


print("\nMarket Signals:\n")


for symbol, data in all_data.items():

    try:
        analyzed_data = indicator.add_indicators(data)
        signal = signal_engine.generate_signal(analyzed_data)
        trade = trade_manager.calculate_trade(analyzed_data, signal)

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