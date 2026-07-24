from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager
from risk.risk_manager import RiskManager


print("=" * 50)
print("AI MULTI-ASSET TRADING PLATFORM")
print("=" * 50)


market = MarketData()
indicator = TechnicalIndicators()
signal_engine = SignalEngine()
trade_manager = TradeManager()
risk_manager = RiskManager()

all_data = market.download_all_data()


print("\nMarket Signals:\n")


for symbol, data in all_data.items():

    try:
        analyzed_data = indicator.add_indicators(data)
        signal = signal_engine.generate_signal(analyzed_data)
        trade = trade_manager.calculate_trade(analyzed_data, signal)

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
                    1000,
                    risk_plan["entry"],
                    risk_plan["stop_loss"]
                )

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

    except Exception as e:
        print(symbol, "ERROR:", e)