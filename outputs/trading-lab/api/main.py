"""TradingLab FastAPI — Phase 1 foundation.

Run:
  cd outputs/trading-lab/api && uvicorn main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from risk.gate import GATE
from routers import books, health, risk

settings = get_settings()
GATE.max_per_trade_usd = settings.max_per_trade_usd
GATE.max_daily_loss_usd = settings.max_daily_loss_usd
GATE.max_open_positions = settings.max_open_positions
GATE.max_exposure_usd = settings.max_exposure_usd
GATE.arm_ttl_hours = settings.arm_ttl_hours

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(risk.router)
app.include_router(books.router)


@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "phase": 1,
        "env": settings.env,
        "docs": "/docs",
        "health": "/healthz",
        "books": "/api/books/summary",
        "live": "/api/live/status",
        "brokers": {
            "stocks": "Alpaca paper (set ALPACA_API_KEY + ALPACA_SECRET_KEY)",
            "forex": "simulation until OANDA keys",
            "solana": "Jupiter status only until wallet key + ARM",
        },
    }


_static = Path(__file__).resolve().parent.parent
if (_static / "desk-unify.js").exists():
    try:
        app.mount("/static", StaticFiles(directory=str(_static)), name="static")
    except Exception:
        pass
