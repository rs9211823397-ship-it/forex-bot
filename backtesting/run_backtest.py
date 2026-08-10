import argparse
import json
from pathlib import Path

from data.market_data import MarketData
from strategy.signal_engine import SignalEngine
from strategy.regime_router import RegimeStrategyRouter
from strategy.setup_detector import SetupDetector
from backtesting.backtest_engine import BacktestEngine
from backtesting.performance import PerformanceReport
from indicators.technical import TechnicalIndicators
from config.instruments import get_instrument_spec
from validation.workflow import chronological_holdout_report, write_signal_ledger


LOWER_TIMEFRAME = "15m"
HIGHER_TIMEFRAME = "1h"

parser = argparse.ArgumentParser()
parser.add_argument("--symbol", default="ETH-USD")
parser.add_argument("--output-dir", default="outputs/validation")
args = parser.parse_args()
symbol = str(args.symbol).strip().upper()
if not symbol:
    raise ValueError("symbol cannot be empty")
output_dir = Path(args.output_dir)
safe_symbol = "".join(
    character.lower() if character.isalnum() else "_"
    for character in symbol
).strip("_")

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
primary_detector = SetupDetector()

data = market.download_data(symbol, interval=LOWER_TIMEFRAME)
higher_tf = market.download_data(symbol, interval=HIGHER_TIMEFRAME)
data = indicators.add_indicators(data).dropna()

print("Calculating causal production signals...")

signals = []
signal_ledger = []
for i in range(len(data)):
    if i % 500 == 0:
        print(f"Processed {i}/{len(data)} candles")

    # Only lower-timeframe candles available at this historical decision point
    # are supplied. The production MTF/context stack causally truncates higher_tf
    # to the same decision time, so research cannot see future HTF candles.
    df = data.iloc[max(0, i - 250) : i + 1].copy()
    result = engine.generate_signal(df, symbol, higher_tf)
    signals.append(result)
    decision_time = (
        data.iloc[i]["close_time"]
        if "close_time" in data.columns
        else data.index[i]
    )
    primary_setup = primary_detector.detect(data.iloc[i])
    signal_ledger.append({
        "timestamp": decision_time,
        "symbol": symbol,
        "signal": primary_setup.direction or "HOLD",
    })

print("Signals calculated:", len(signals))
ledger_path = write_signal_ledger(
    signal_ledger,
    output_dir / f"aaqts_primary_signals_{safe_symbol}.csv",
)
print("AAQTS signal ledger:", ledger_path)


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
full_summary = report.summary()

# A chronological 70/30 holdout is reported independently.  Parameters are
# never selected from this tail segment; promotion fails closed unless it has
# enough completed trades and independently meets PF/expectancy/drawdown gates.
holdout = chronological_holdout_report(
    trades,
    data,
    initial_equity=backtest.initial_equity,
)
out_of_sample_summary = holdout["out_of_sample"]
validation_metrics = {
    "full": full_summary,
    "out_of_sample": out_of_sample_summary,
    "split": holdout["split"],
}
metrics_path = output_dir / f"backtest_metrics_{safe_symbol}.json"
metrics_path.parent.mkdir(parents=True, exist_ok=True)
metrics_path.write_text(
    json.dumps(validation_metrics, indent=2, sort_keys=True),
    encoding="utf-8",
)

print("==============================")
print("BACKTEST REPORT")
print("==============================")
print(full_summary)
print("OUT-OF-SAMPLE REPORT")
print(out_of_sample_summary)
print("Validation metrics:", metrics_path)
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
