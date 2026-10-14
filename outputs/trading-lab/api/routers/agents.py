"""Agent cycle endpoints — propose only; RiskGate decides execution."""
from __future__ import annotations

import os
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.deliberation import run_scripted_deliberation, Proposal
from brokers.alpaca import AlpacaPaper
from config import get_settings
from risk.gate import GATE
from llm_research import LLMResearchLayer
from forex_market import snapshot, STOCKS, DEFAULT_PAIRS

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
    use_llm: bool = Field(
        default=True,
        description="If true, use the six-agent LLM layer instead of scripted deliberation",
    )


@router.post("/cycle")
async def agent_cycle(body: CycleBody):
    settings = get_settings()

    # Fetch live market data for the symbol
    # forex_market uses pairs like "AAPL/USD", "EUR/USD", etc.
    if "/" in body.symbol:
        market_pairs = [body.symbol.upper()]
    elif body.symbol.upper() in [s.split("/")[0] for s in STOCKS]:
        market_pairs = [body.symbol.upper() + "/USD"]
    else:
        market_pairs = [body.symbol.upper().replace("USD", "/USD") if body.symbol.upper().endswith("USD") else body.symbol.upper()]
    try:
        market = snapshot(market_pairs)
        market_pairs_dict = market.get("pairs", {})
    except Exception:
        market_pairs_dict = {body.symbol: {"price": 0, "observed": 0, "source": "fallback"}}

    # Build context for LLM
    account = {"equity": 100000, "exposure": 0, "daily_halted": False, "positions": []}
    risk = {"max_trade_notional": body.notional_usd, "max_exposure": 100, "max_positions": 3, "max_daily_loss": 5}
    history = {}
    positions = []

    # Try LLM-powered deliberation first
    research = LLMResearchLayer(settings)
    if body.use_llm and research.available():
        llm_result = research.run(
            {"pairs": market_pairs_dict},
            account, risk, history, positions
        )

        # Build conversation from LLM stages
        conversation = []
        for stage in llm_result.get("stages", []):
            conversation.append({
                "role": stage["agent"],
                "summary": stage["text"],
                "concerns": stage.get("concerns", []),
            })

        # Extract final decision from coordinator
        final = llm_result.get("final_decision", {})
        decision = final.get("decision", "hold")

        # Build proposal from LLM decision
        if decision in ("buy", "sell") and final.get("pair_or_token"):
            symbol = final["pair_or_token"].replace("/", "")
            proposal = Proposal(
                action=decision,
                symbol=symbol,
                notional_usd=min(body.notional_usd, settings.max_per_trade_usd),
                confidence=0.7,
                thesis=final.get("rationale", "LLM six-agent recommendation"),
                book=body.book,
            )
        else:
            proposal = Proposal(
                action="hold",
                symbol=body.symbol,
                notional_usd=0.0,
                confidence=0.0,
                thesis=final.get("rationale", "LLM advised hold"),
                book=body.book,
            )

        # Build mock deliberation result
        from dataclasses import dataclass
        @dataclass
        class DeliberationResult:
            conversation: list
            proposal: Proposal | None
            vetoed: bool
            veto_reason: str

        deliberation = DeliberationResult(
            conversation=conversation,
            proposal=proposal,
            vetoed=False,
            veto_reason="",
        )
    else:
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
