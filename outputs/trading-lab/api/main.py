"""TradingLab FastAPI — Phase 1 foundation.

Run:
  cd outputs/trading-lab/api && uvicorn main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Also add parent directory for shared modules (forex_market, etc.)
_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from risk.gate import GATE
from routers import agents, books, health, risk
from autonomous_loop import get_trader, AutonomousTrader

settings = get_settings()
GATE.max_per_trade_usd = settings.max_per_trade_usd
GATE.max_daily_loss_usd = settings.max_daily_loss_usd
GATE.max_open_positions = settings.max_open_positions
GATE.max_exposure_usd = settings.max_exposure_usd
GATE.arm_ttl_hours = settings.arm_ttl_hours

# Initialize autonomous trader
_autonomous_trader: AutonomousTrader | None = None

app = FastAPI(title=settings.app_name, version="0.2.0")
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
app.include_router(agents.router)


@app.get("/")
async def root():
    trader = get_trader()
    return {
        "service": settings.app_name,
        "phase": 2,
        "version": "0.2.0",
        "env": settings.env,
        "docs": "/docs",
        "health": "/healthz",
        "books": "/api/books/summary",
        "live": "/api/live/status",
        "agents": "/api/agents/cycle",
        "autonomous": {
            "status": "/api/autonomous/status",
            "start": "/api/autonomous/start",
            "stop": "/api/autonomous/stop",
            "run_once": "/api/autonomous/run_once",
        },
        "brokers": {
            "stocks": "Alpaca paper (set ALPACA_API_KEY + ALPACA_SECRET_KEY)",
            "forex": "simulation until OANDA keys",
            "solana": "Jupiter status only until wallet key + ARM",
        },
        "risk_limits": {
            "max_per_trade_usd": settings.max_per_trade_usd,
            "max_daily_loss_usd": settings.max_daily_loss_usd,
            "max_open_positions": settings.max_open_positions,
            "max_exposure_usd": settings.max_exposure_usd,
        },
        "llm": {
            "provider": "OpenRouter",
            "model": settings.llm_model,
            "available": get_trader().research.available() if get_trader().research else False,
        },
    }


@app.get("/api/autonomous/status")
async def autonomous_status():
    """Get status of the autonomous six-agent trader."""
    return get_trader().status()


@app.post("/api/autonomous/arm")
async def autonomous_arm(hours: float = 24.0):
    """Arm the autonomous trader (risk gate enabled)."""
    trader = get_trader()
    return {
        "risk": trader.arm(hours),
        "trader": {"running": False, "message": "Armed. Use /start to begin autonomous trading."}
    }


@app.post("/api/autonomous/start")
async def autonomous_start():
    """Start the autonomous trading loop."""
    trader = get_trader()
    result = trader.start()
    return {
        "ok": result["ok"],
        "message": result["message"],
        "interval_seconds": trader.interval,
    }


@app.post("/api/autonomous/stop")
async def autonomous_stop():
    """Stop the autonomous trading loop."""
    trader = get_trader()
    result = trader.stop()
    return result


@app.post("/api/autonomous/run_once")
@app.get("/api/autonomous/run_once")
async def autonomous_run_once():
    """Run a single autonomous trading cycle manually."""
    trader = get_trader()
    result = trader.run_once()
    return result


@app.on_event("shutdown")
def shutdown_event():
    """Clean up the autonomous trader on shutdown."""
    global _autonomous_trader
    if _autonomous_trader:
        _autonomous_trader.stop()


_static = Path(__file__).resolve().parent.parent
if (_static / "desk-unify.js").exists():
    try:
        app.mount("/static", StaticFiles(directory=str(_static)), name="static")
    except Exception:
        pass
