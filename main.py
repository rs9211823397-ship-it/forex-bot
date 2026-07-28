from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager
from execution.execution_engine import ExecutionEngine
from risk.risk_manager import RiskManager
from bot_controller import BotController
from logs.logger import TradeLogger
from config.settings import ACCOUNT_BALANCE
from paper.paper_trader import PaperTrader
from broker.paper_broker import PaperBroker


market = MarketData()
indicator = TechnicalIndicators()
signal_engine = SignalEngine()
trade_manager = TradeManager()
risk_manager = RiskManager()
bot = BotController()
logger = TradeLogger()
paper_trader = PaperTrader()
paper_broker = PaperBroker(paper_trader)
execution_engine = ExecutionEngine(paper_broker, logger)


def run_bot():
    logger.log_event("bot_cycle_started")
    all_data = market.download_all_data()
    higher_tf_data = market.download_all_data(interval="1h")
    current_prices = {}

    for symbol, data in all_data.items():
        if not bot.should_run:
            break

        try:
            analyzed_data = indicator.add_indicators(data)
            signal = signal_engine.generate_signal(
                analyzed_data,
                symbol,
                higher_tf_data.get(symbol),
            )

            logger.log_signal(symbol, signal["signal"], signal["confidence"])
            trade = trade_manager.calculate_trade(analyzed_data, signal)
            current_prices[symbol] = trade["current_price"]

            risk_plan = None
            position = None
            order = None

            if signal["signal"] != "HOLD":
                risk_plan = risk_manager.calculate_trade_levels(
                    signal["signal"],
                    trade["current_price"],
                    trade["atr"],
                )

                if risk_plan:
                    position = risk_manager.position_size(
                        ACCOUNT_BALANCE,
                        risk_plan["entry"],
                        risk_plan["stop_loss"],
                        symbol,
                    )
                    logger.log_trade(symbol, risk_plan, position)
                    order = execution_engine.submit_market_order(
                        symbol=symbol,
                        side=signal["signal"],
                        quantity=position,
                        entry=risk_plan["entry"],
                        stop_loss=risk_plan["stop_loss"],
                        take_profit=risk_plan["take_profit"],
                        metadata={"confidence": signal["confidence"]},
                    )

            paper_trader.check_trade(symbol, trade["current_price"])

            print("\n" + "=" * 60)
            print(f"Asset      : {symbol}")
            print(f"Signal     : {signal['signal']}")
            print(f"Confidence : {signal['confidence']}%")
            print(f"Score      : {signal['score']}")
            print(f"Price      : {trade['current_price']:.4f}")
            print(f"ATR        : {trade['atr']:.4f}")

            if risk_plan:
                print("\nTrade Plan")
                print(f"Entry         : {risk_plan['entry']}")
                print(f"Stop Loss     : {risk_plan['stop_loss']}")
                print(f"Take Profit   : {risk_plan['take_profit']}")
                print(f"Risk Reward   : 1:{risk_plan['risk_reward']}")
                print(f"Position Size : {position}")
                if order:
                    print(f"Order ID      : {order.order_id}")
                    print(f"Order Status  : {order.status.value}")

            print("\nReasons:")
            for reason in signal["reasons"]:
                print(f"  ✓ {reason}")

        except Exception as exc:
            logger.log_exception("symbol_processing_failed", exc, symbol=symbol)
            print(symbol, "ERROR:", exc)

    paper_trader.update_equity(current_prices)
    stats = paper_trader.get_stats()
    logger.log_event(
        "bot_cycle_completed",
        balance=stats["balance"],
        equity=stats["equity"],
        open_trades=len(paper_trader.open_trades),
    )

    print("\n" + "=" * 60)
    print("PAPER ACCOUNT")
    print("=" * 60)
    print(f"Starting Balance : ${stats['starting_balance']:.2f}")
    print(f"Balance          : ${stats['balance']:.2f}")
    print(f"Floating P/L     : ${stats['floating_pnl']:.2f}")
    print(f"Equity           : ${stats['equity']:.2f}")
    print(f"Closed Trades    : {stats['total_trades']}")
    print(f"Win Rate         : {stats['win_rate']}%")
    print(f"Net P/L          : ${stats['total_pnl']:.2f}")
    print("=" * 60)


if __name__ == "__main__":
    from bot_loop import BotLoop

    print("\nBot Status:", bot.start_bot())
    loop = BotLoop(interval=10, controller=bot, logger=logger)
    loop.start(run_bot)
