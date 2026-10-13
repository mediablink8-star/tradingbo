"""Unified books: stocks (Alpaca), FX (sim), Solana status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from brokers.alpaca import AlpacaPaper
from brokers.fx_sim import FX_BOOK
from brokers.jupiter import JupiterClient
from config import get_settings
from risk.gate import GATE

router = APIRouter(prefix="/api", tags=["books"])


@router.get("/books/summary")
async def books_summary():
    settings = get_settings()
    alpaca = AlpacaPaper(settings)
    jup = JupiterClient(settings)
    stocks = await alpaca.account()
    positions = await alpaca.positions() if alpaca.configured else []
    fx = FX_BOOK.snapshot()
    return {
        "mode": settings.env,
        "risk": GATE.status(),
        "stocks": {**stocks, "positions": positions},
        "forex": fx,
        "solana": jup.status(),
    }


class StockOrder(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    notional_usd: float = Field(gt=0, le=50_000)
    side: str = Field(default="buy", pattern="^(buy|sell)$")


@router.post("/stocks/order")
async def stock_order(body: StockOrder):
    settings = get_settings()
    decision = GATE.check_order(body.notional_usd, body.side)
    if not decision.allowed:
        raise HTTPException(
            status_code=403, detail={"reason": decision.reason, "risk": GATE.status()}
        )
    alpaca = AlpacaPaper(settings)
    if not alpaca.configured:
        raise HTTPException(
            status_code=400,
            detail="Alpaca keys not set (ALPACA_API_KEY / ALPACA_SECRET_KEY)",
        )
    result = await alpaca.submit_market_order(body.symbol, decision.sized_usd, body.side)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    GATE.record_fill(body.side, decision.sized_usd)
    return {"risk": decision.__dict__, "broker": result}
