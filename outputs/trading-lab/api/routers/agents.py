"""Agent cycle endpoints — propose only; RiskGate decides execution."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.deliberation import run_scripted_deliberation
from brokers.alpaca import AlpacaPaper
from config import get_settings
from risk.gate import GATE

router = APIRouter(prefix="/api/agents", tags=["agents"])


class CycleBody(BaseModel):
    book: str = Field(default="stocks", pattern="^(stocks|forex|solana)$")
    symbol: str = Field(default="SPY", min_length=1, max_length=16)
    notional_usd: float = Field(default=10.0, gt=0, le=100)
    trend: str = Field(default="unknown")
    data_quality: float = Field(default=0.7, ge=0, le=1)
    execute: bool = Field(
        default=False,
        description="If true and proposal is buy/sell, attempt broker order behind RiskGate",
    )


@router.post("/cycle")
async def agent_cycle(body: CycleBody):
    settings = get_settings()
    snap = {
        "symbols": [body.symbol],
        "trend": body.trend,
        "data_quality": body.data_quality,
    }
    deliberation = run_scripted_deliberation(
        snap, book=body.book, default_symbol=body.symbol, default_notional=body.notional_usd
    )
    proposal = deliberation.proposal
    out: dict = {
        "conversation": deliberation.conversation,
        "proposal": None
        if not proposal
        else {
            "action": proposal.action,
            "symbol": proposal.symbol,
            "notional_usd": proposal.notional_usd,
            "confidence": proposal.confidence,
            "thesis": proposal.thesis,
            "book": proposal.book,
        },
        "vetoed": deliberation.vetoed,
        "veto_reason": deliberation.veto_reason,
        "risk": GATE.status(),
        "execution": None,
    }

    if deliberation.vetoed or not proposal or proposal.action == "hold":
        return out

    if not body.execute:
        decision = GATE.check_order(proposal.notional_usd, proposal.action)
        out["execution"] = {
            "mode": "dry_run",
            "allowed": decision.allowed,
            "reason": decision.reason,
            "sized_usd": decision.sized_usd,
        }
        return out

    decision = GATE.check_order(proposal.notional_usd, proposal.action)
    if not decision.allowed:
        out["execution"] = {
            "mode": "blocked",
            "reason": decision.reason,
            "risk": GATE.status(),
        }
        return out

    if body.book != "stocks":
        out["execution"] = {
            "mode": "blocked",
            "reason": f"execute not enabled for book={body.book} in phase 1 (stocks/Alpaca only)",
        }
        return out

    alpaca = AlpacaPaper(settings)
    if not alpaca.configured:
        raise HTTPException(status_code=400, detail="Alpaca keys not configured")
    result = await alpaca.submit_market_order(
        proposal.symbol,
        decision.sized_usd,
        "buy" if proposal.action == "buy" else "sell",
    )
    if result.get("ok"):
        GATE.record_fill(proposal.action, decision.sized_usd)
    out["execution"] = {
        "mode": "live_paper",
        "sized_usd": decision.sized_usd,
        "broker": result,
    }
    out["risk"] = GATE.status()
    return out


@router.get("/roles")
async def agent_roles():
    from agents.deliberation import ROLES

    return {"roles": [{"name": n, "charter": c} for n, c in ROLES]}
