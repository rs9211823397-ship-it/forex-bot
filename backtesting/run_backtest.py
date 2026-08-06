from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from strategy.regime_router import RegimeStrategyRouter
from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators
from config.instruments import get_instrument_spec


LOWER_TIMEFRAME = "15m"
HIGHER_TIMEFRAME = "1h"

market = MarketData()
trend_engine = SignalEngine.production(
    higher_timeframe=HIGHER_TIMEFRAME,
    lower_timeframe=LOWER_TIMEFRAME,
)
engine = RegimeStrategyRouter(
    trend_engine,
    higher_timeframe=HIGHER_TIMEFRAME,
    lower_timeframe=LOWER_TIMEFRAME,
)
indicators = TechnicalIndicators()

symbol = "ETH-USD"

data = market.download_data(symbol, interval=LOWER_TIMEFRAME)
higher_tf = market.download_data(symbol, interval=HIGHER_TIMEFRAME)
data = indicators.add_indicators(data).dropna()

print("Calculating causal production signals...")

signals = []
for i in range(len(data)):
    if i % 500 == 0:
        print(f"Processed {i}/{len(data)} candles")

    # Only lower-timeframe candles available at this historical decision point
    # are supplied. The production MTF/context stack causally truncates higher_tf
    # to the same decision time, so research cannot see future HTF candles.
    df = data.iloc[max(0, i - 250) : i + 1].copy()
    result = engine.generate_signal(df, symbol, higher_tf)
    signals.append(result)

print("Signals calculated:", len(signals))


def run_strategy(index):
    # Preserve regime/strategy/risk_multiplier metadata instead of reducing the
    # production decision to a bare BUY/SELL/HOLD string.
    return signals[index]


backtest = BacktestEngine(
    data,
    run_strategy,
    instrument=get_instrument_spec(symbol),
)

trades = backtest.run()
report = PerformanceReport(
    trades,
    initial_equity=backtest.initial_equity,
    equity_curve=backtest.equity_history,
)

print("==============================")
print("BACKTEST REPORT")
print("==============================")
print(report.summary())
print("\nTRADE DETAILS")
print("================")

for trade in trades:
    if trade["type"] == "EXIT":
        print(
            trade["side"],
            "|",
            trade["result"],
            "| P/L:",
            round(trade["profit"], 2),
        )

print("\nWIN/LOSS SUMMARY")
print("================")
wins = 0
losses = 0
for trade in trades:
    if trade["type"] == "EXIT":
        if trade["result"] == "TAKE PROFIT":
            wins += 1
        else:
            losses += 1

print("Take Profits:", wins)
print("Stop Losses:", losses)
