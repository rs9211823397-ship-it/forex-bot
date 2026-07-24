from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators

market = MarketData()
engine = SignalEngine()
indicators = TechnicalIndicators()

def run_strategy(row):

    import pandas as pd

    df = pd.DataFrame([row])

    result = engine.generate_signal(df)

    return result["signal"]


data = market.download_data("ETH-USD")
# Fix Yahoo Finance multi-level columns
if hasattr(data.columns, "levels"):
    data.columns = data.columns.get_level_values(0)
print(data.head())
print(data.columns)
# Rename columns if needed
data = data.rename(columns={
    "Close": "Close"
})


indicator = TechnicalIndicators()

data = indicators.add_indicators(data)


data = data.dropna()


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
