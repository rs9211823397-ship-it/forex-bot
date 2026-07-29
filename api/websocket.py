from fastapi import WebSocket
import asyncio

from runtime.bot_runtime import runtime


async def market_stream(websocket: WebSocket):

    await websocket.accept()

    try:
        while True:

            data = {
                "signals": runtime.latest_signals,
                "prices": runtime.latest_prices,
                "account": runtime.paper_trader.get_account()
            }

            await websocket.send_json(data)

            await asyncio.sleep(2)

    except Exception:
        await websocket.close()
