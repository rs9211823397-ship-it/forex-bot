from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators
from config.instruments import get_instrument_spec


symbol = "ETH-USD"

market = MarketData()
engine = SignalEngine()
indicators = TechnicalIndicators()


print("Loading cached market data...")


data = market.download_data(
    symbol,
    interval="15m"
)

higher_tf = market.download_data(
    symbol,
    interval="1h"
)


print("Preparing indicators...")


data = indicators.add_indicators(data)

data = data.dropna()


# limit history for fast iteration
MAX_CANDLES = 500

if len(data) > MAX_CANDLES:
    data = data.tail(MAX_CANDLES)


print(
    f"Testing candles: {len(data)}"
)


signals = []


print("Generating signals...")


for i in range(len(data)):

    if i % 500 == 0:
        print(
            f"Signals {i}/{len(data)}"
        )

    window = data.iloc[
        max(0,i-250):i+1
    ]


    result = engine.generate_signal(
        window,
        symbol,
        higher_tf
    )


    signals.append(
        result["signal"]
    )


print(
    "Signals generated:",
    len(signals)
)


def strategy(index):
    return signals[index]


print("Running execution simulation...")


backtest = BacktestEngine(
    data,
    strategy,
    instrument=get_instrument_spec(symbol),
)


trades = backtest.run()


report = PerformanceReport(
    trades,
    initial_equity=backtest.initial_equity,
    equity_curve=backtest.equity_history
)


print("\n===================")
print("FAST BACKTEST REPORT")
print("===================")

print(report.summary())


