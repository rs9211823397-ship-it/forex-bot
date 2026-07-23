from data.market_data import MarketData

print("=" * 50)
print("FOREX BOT STARTING...")
print("=" * 50)

market = MarketData()

data = market.download_data()

print(data.tail())