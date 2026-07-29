from fastapi import FastAPI
from runtime.bot_runtime import runtime
from api.websocket import market_stream


app = FastAPI(
    title="AI Multi Asset Trading Platform API",
    version="1.0"
)


@app.get("/")
def home():
    return {
        "service": "AI Trading Platform",
        "status": "online"
    }


@app.get("/health")
def health():
    return {
        "api": "running",
        "runtime": "connected"
    }


# -----------------------
# BOT CONTROL
# -----------------------

@app.get("/bot/status")
def bot_status():
    return {
        "status": runtime.bot.status()
    }


@app.post("/bot/start")
def start_bot():
    return {
        "message": runtime.bot.start_bot()
    }


@app.post("/bot/stop")
def stop_bot():
    return {
        "message": runtime.bot.stop_bot()
    }


@app.post("/bot/pause")
def pause_bot():
    return {
        "message": runtime.bot.pause_bot()
    }


@app.post("/bot/resume")
def resume_bot():
    return {
        "message": runtime.bot.resume_bot()
    }


# -----------------------
# TRADING DATA
# -----------------------

@app.get("/account")
def account():
    return runtime.paper_trader.get_stats()


@app.get("/performance")
def performance():
    return runtime.paper_trader.get_stats()


@app.get("/positions")
def positions():
    return runtime.paper_trader.open_trades


@app.get("/signals")
def signals():
    return runtime.latest_signals


@app.get("/market")
def market():
    return runtime.latest_prices


@app.get("/risk")
def risk():
    return {
        "risk_percent": runtime.risk_manager.risk_percent
    }


@app.websocket("/ws/market")
async def websocket_market(websocket):
    await market_stream(websocket)
