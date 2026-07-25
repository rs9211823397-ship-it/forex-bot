from structure.market_structure import MarketStructure
from price_action.candles import CandlePatterns
from data.market_data import MarketData


market = MarketData()
data = market.download_data("BTC-USD")


ms = MarketStructure()

print("STRUCTURE TEST")
print("Trend:", ms.detect_trend(data))
print("BOS:", ms.detect_bos(data))
print("CHoCH:", ms.detect_choch(data))


print("\nCANDLE TEST")

c = CandlePatterns()

print(c.check_patterns(data))
