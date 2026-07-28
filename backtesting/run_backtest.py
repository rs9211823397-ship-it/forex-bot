from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from backtesting.backtest_engine import BacktestCosts, BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators


market = MarketData()
engine = SignalEngine()
indicators = TechnicalIndicators()

symbol = "ETH-USD"
initial_balance = 10_000.0

data = market.download_data(symbol, interval="15m")
higher_tf = market.download_data(symbol, interval="1h")

data = indicators.add_indicators(data).dropna()

print("Calculating signals...")
signals = []

for i in range(len(data)):
    if i % 500 == 0:
        print(f"Processed {i}/{len(data)} candles")

    result = engine.generate_signal(
        data.iloc[: i + 1],
        symbol,
        higher_tf,
    )
    signals.append(result["signal"])

print("Signals calculated:", len(signals))

backtest = BacktestEngine(
    data=data,
    strategy=lambda index: signals[index],
    initial_balance=initial_balance,
    position_size=1.0,
    costs=BacktestCosts(
        spread=0.10,
        slippage=0.02,
        commission_per_unit=0.01,
    ),
)

trades = backtest.run()
report = PerformanceReport(trades, initial_balance=initial_balance)

print("==============================")
print("BACKTEST REPORT")
print("==============================")
print(report.summary())
