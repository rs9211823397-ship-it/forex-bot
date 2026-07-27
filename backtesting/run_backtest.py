from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators


market = MarketData()
engine = SignalEngine()
indicators = TechnicalIndicators()

symbol = "ETH-USD"

data = market.download_data(
    symbol,
    interval="15m"
)

higher_tf = market.download_data(
    symbol,
    interval="1h"
)

data = indicators.add_indicators(data)
data = data.dropna()

print("Calculating signals...")

signals = []

for i in range(len(data)):

    if i % 500 == 0:
        print(f"Processed {i}/{len(data)} candles")

    df = data.iloc[:i+1]

    result = engine.generate_signal(
        df,
        symbol,
        higher_tf
    )

    signals.append(result["signal"])

print("Signals calculated:", len(signals))


def run_strategy(index):
    return signals[index]


backtest = BacktestEngine(
    data,
    run_strategy
)

trades = backtest.run()

report = PerformanceReport(trades)

print("==============================")
print("BACKTEST REPORT")
print("==============================")
print(report.summary())
