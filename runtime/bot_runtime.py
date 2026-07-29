from data.market_data import MarketData
from indicators.technical import TechnicalIndicators
from strategy.signal_engine import SignalEngine
from execution.trade_manager import TradeManager
from risk.risk_manager import RiskManager
from bot_controller import BotController
from logs.logger import TradeLogger
from paper.paper_trader import PaperTrader
from risk.protection import PortfolioRiskManager
from config.settings import HIGHER_TIMEFRAME, TRADING_TIMEFRAME


class BotRuntime:

    def __init__(self):

        self.market = MarketData()

        self.indicator = TechnicalIndicators()

        self.signal_engine = SignalEngine.production(
            higher_timeframe=HIGHER_TIMEFRAME,
            lower_timeframe=TRADING_TIMEFRAME,
        )

        self.trade_manager = TradeManager()

        self.risk_manager = RiskManager()

        self.portfolio_risk_manager = PortfolioRiskManager()

        self.bot = BotController()

        self.logger = TradeLogger()

        self.paper_trader = PaperTrader()

        self.latest_signals = {}
        self.latest_prices = {}


runtime = BotRuntime()

