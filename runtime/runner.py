from config.instruments import get_instrument_spec
from config.settings import TRADING_TIMEFRAME
from data.timeframes import frame_decision_time
from risk.protection import (
    PortfolioRiskManager,
    RiskContext,
    TradeRiskRequest,
)
from runtime.bot_runtime import runtime


market = runtime.market
indicator = runtime.indicator
signal_engine = runtime.signal_engine
trade_manager = runtime.trade_manager
risk_manager = runtime.risk_manager
portfolio_risk_manager = runtime.portfolio_risk_manager
bot = runtime.bot
logger = runtime.logger
paper_trader = runtime.paper_trader


def run_bot():

    print("=" * 60)
    print("AI MULTI-ASSET TRADING PLATFORM")
    print("=" * 60)

    all_data = market.download_all_data(
        interval=TRADING_TIMEFRAME
    )

    higher_tf_data = market.download_all_data(
        interval=TRADING_TIMEFRAME
    )

    current_prices = {}

    for symbol, data in all_data.items():

        if bot.status() != "RUNNING":
            break

        try:

            analyzed_data = indicator.add_indicators(data)

            signal = signal_engine.generate_signal(
                analyzed_data,
                symbol,
                higher_tf_data.get(symbol)
            )

            logger.log_signal(
                symbol,
                signal["signal"],
                signal["confidence"]
            )

            runtime.latest_signals[symbol] = signal

            trade = trade_manager.calculate_trade(
                analyzed_data,
                signal
            )

            current_prices[symbol] = trade["current_price"]
            runtime.latest_prices[symbol] = trade["current_price"]

            paper_trader.check_trade(
                symbol,
                trade["current_price"]
            )

        except Exception as e:
            print(symbol, "ERROR:", e)


    paper_trader.update_equity(current_prices)
