
from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators


market = MarketData()
engine = SignalEngine()
indicators = TechnicalIndicators()


data = market.download_data("ETH-USD")


if hasattr(data.columns, "levels"):
    data.columns = data.columns.get_level_values(0)


data.columns = [
    str(col).lower()
    for col in data.columns
]


data = indicators.add_indicators(data)

data = data.dropna()



print("Calculating signals...")


signals = []


for i in range(len(data)):

    df = data.iloc[:i+1]

    result = engine.generate_signal(
        df,
        "ETH-USD"
    )

    signals.append(
        result["signal"]
    )


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
