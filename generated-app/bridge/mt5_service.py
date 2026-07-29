# MT5 HTTP Bridge Service — PRODUCTION PATH for real Exness/MT5 execution.
#
# Run this on a Windows VPS (or local Windows machine with MT5 installed).
# The AAQTS backend (src/lib/mt5/bridge.ts, mode "http") talks to it.
#
# Setup (Windows):
#   pip install MetaTrader5 fastapi uvicorn
#   set MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe   (optional)
#   uvicorn mt5_service:app --host 0.0.0.0 --port 8080
#
# Then on the AAQTS server/container:
#   MT5_BRIDGE_MODE=http
#   MT5_BRIDGE_URL=http://<windows-vps-ip>:8080
#
# Endpoints mirror IMt5Bridge exactly.

from typing import Optional, List
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import MetaTrader5 as mt5
import time
import uuid

app = FastAPI(title="AAQTS MT5 Bridge", version="2.0")

SESSIONS = {}  # session_id -> {"login": int, "password": str, "server": str}


class LoginBody(BaseModel):
    login: str
    password: str
    server: str


class OrderBody(BaseModel):
    symbol: str
    direction: str  # "buy" | "sell"
    lots: float
    entryPrice: Optional[float] = None
    stopLoss: Optional[float] = None
    takeProfit: Optional[float] = None
    comment: Optional[str] = "aaqts"


class ModifyBody(BaseModel):
    ticket: str
    stopLoss: Optional[float] = None
    takeProfit: Optional[float] = None


class CloseBody(BaseModel):
    ticket: str
    percent: Optional[float] = 100


class HistoryBody(BaseModel):
    limit: Optional[int] = 50


def _auth(x_mt5_session: Optional[str]):
    if not x_mt5_session or x_mt5_session not in SESSIONS:
        raise HTTPException(status_code=401, detail="no mt5 session")
    return SESSIONS[x_mt5_session]


@app.post("/login")
def login(body: LoginBody):
    # Initialize terminal path if provided
    ok = mt5.initialize()
    if not ok:
        return {"connected": False, "message": f"mt5 initialize failed: {mt5.last_error()}"}
    # Connect to the broker server with credentials
    authorized = mt5.login(int(body.login), password=body.password, server=body.server)
    if not authorized:
        mt5.shutdown()
        return {"connected": False, "message": f"mt5 login failed: {mt5.last_error()}"}
    acc = mt5.account_info()
    session = uuid.uuid4().hex
    SESSIONS[session] = {"login": int(body.login), "password": body.password, "server": body.server}
    return {
        "connected": True,
        "session": session,
        "company": getattr(acc, "company", None),
        "balance": getattr(acc, "balance", None),
        "equity": getattr(acc, "equity", None),
    }


@app.post("/logout")
def logout(x_mt5_session: Optional[str] = Header(None)):
    _auth(x_mt5_session)
    SESSIONS.pop(x_mt5_session, None)
    mt5.shutdown()
    return {"ok": True}


def _order_request(symbol: str, direction: str, lots: float, entry: float, sl: Optional[float], tp: Optional[float], comment: str, position: Optional[int] = None):
    otype = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": otype,
        "price": entry,
        "deviation": 20,
        "magic": 20260101,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if sl is not None: req["sl"] = sl
    if tp is not None: req["tp"] = tp
    if position is not None: req["position"] = position
    return req


@app.post("/order", response_model_exclude_none=True)
def order(body: OrderBody, x_mt5_session: Optional[str] = Header(None)):
    _auth(x_mt5_session)
    tick = mt5.symbol_info_tick(body.symbol)
    if tick is None:
        raise HTTPException(status_code=400, detail="symbol tick unavailable")
    price = body.entryPrice or (tick.ask if body.direction == "buy" else tick.bid)
    result = mt5.order_send(_order_request(body.symbol, body.direction, body.lots, price, body.stopLoss, body.takeProfit, body.comment or "aaqts"))
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"success": False, "error": f"retcode {result.retcode}"}
    return {"success": True, "ticket": str(result.order), "fillPrice": result.price}


@app.post("/modify")
def modify(body: ModifyBody, x_mt5_session: Optional[str] = Header(None)):
    _auth(x_mt5_session)
    pos = mt5.positions_get(ticket=int(body.ticket))
    if not pos: return {"success": False, "error": "position not found"}
    p = pos[0]
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": p.symbol,
        "position": int(body.ticket),
        "sl": body.stopLoss if body.stopLoss is not None else p.sl,
        "tp": body.takeProfit if body.takeProfit is not None else p.tp,
    }
    result = mt5.order_send(req)
    return {"success": result.retcode == mt5.TRADE_RETCODE_DONE}


@app.post("/close")
def close(body: CloseBody, x_mt5_session: Optional[str] = Header(None)):
    _auth(x_mt5_session)
    pos = mt5.positions_get(ticket=int(body.ticket))
    if not pos: return {"success": False, "error": "position not found"}
    p = pos[0]
    tick = mt5.symbol_info_tick(p.symbol)
    direction = "sell" if p.type == mt5.POSITION_TYPE_BUY else "buy"
    price = tick.bid if direction == "sell" else tick.ask
    closed_volume = round(p.volume * (body.percent or 100) / 100.0, 2)
    if closed_volume < 0.01 or closed_volume >= p.volume:
        closed_volume = p.volume
    result = mt5.order_send(_order_request(p.symbol, direction, closed_volume, price, None, None, "aaqts-close", position=int(body.ticket)))
    return {
        "success": result.retcode == mt5.TRADE_RETCODE_DONE,
        "fillPrice": getattr(result, "price", price),
        "closedLots": closed_volume,
        "profit": getattr(result, "profit", None),
    }


@app.post("/positions")
def positions(x_mt5_session: Optional[str] = Header(None)):
    _auth(x_mt5_session)
    out = []
    for p in mt5.positions_get() or []:
        tick = mt5.symbol_info_tick(p.symbol)
        cur = (tick.ask if p.type == mt5.POSITION_TYPE_BUY else tick.bid) if tick else p.price_open
        out.append({
            "ticket": str(p.ticket),
            "symbol": p.symbol,
            "direction": "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
            "lots": p.volume,
            "entryPrice": p.price_open,
            "stopLoss": p.sl if p.sl else None,
            "takeProfit": p.tp if p.tp else None,
            "currentPrice": cur,
            "unrealizedPnl": p.profit,
            "openedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.time)),
        })
    return out


@app.post("/history")
def history(body: HistoryBody, x_mt5_session: Optional[str] = Header(None)):
    _auth(x_mt5_session)
    from datetime import datetime, timedelta
    deals = mt5.history_deals_get(datetime.utcnow() - timedelta(days=30), datetime.utcnow())
    out = []
    for d in (deals or [])[-(body.limit or 50):]:
        if d.profit == 0 and d.entry == 0:  # skip balance/credit ops keeping demo clean; adjust as needed
            continue
        out.append({
            "ticket": str(d.ticket),
            "symbol": d.symbol,
            "direction": "buy" if d.type == mt5.DEAL_TYPE_BUY else "sell",
            "lots": d.volume,
            "entryPrice": d.price,
            "currentPrice": d.price,
            "unrealizedPnl": d.profit,
            "openedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(d.time)),
        })
    return out


@app.get("/health")
def health():
    return {"ok": True, "mt5_initialized": mt5.terminal_info() is not None}
