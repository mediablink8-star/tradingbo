"""Six-agent sequential deliberation. Scripted by default; LLM optional later.

Final authority is always RiskGate — agents only propose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Side = Literal["buy", "sell", "hold"]


@dataclass
class Proposal:
    action: Side
    symbol: str
    notional_usd: float
    confidence: float
    thesis: str
    book: str = "stocks"


@dataclass
class DeliberationResult:
    conversation: list[dict[str, Any]] = field(default_factory=list)
    proposal: Proposal | None = None
    vetoed: bool = False
    veto_reason: str = ""


ROLES = [
    ("Market Observer", "Summarize only supplied prices, liquidity and data quality."),
    ("Technical Analyst", "Read momentum/structure from supplied series; no invented levels."),
    ("Macro/Narrative Analyst", "Flag narrative risk; prefer abstention when story is thin."),
    ("Strategy Proposer", "Propose one concrete paper action or HOLD."),
    ("Risk Critic", "Attack the proposal; veto weak edges and size creep."),
    ("Portfolio Coordinator", "Final call must respect risk limits and open exposure."),
]


def run_scripted_deliberation(
    market_snapshot: dict[str, Any],
    book: str = "stocks",
    default_symbol: str = "SPY",
    default_notional: float = 10.0,
) -> DeliberationResult:
    result = DeliberationResult()
    pairs = market_snapshot.get("symbols") or [default_symbol]
    symbol = str(pairs[0])
    trend = str(market_snapshot.get("trend") or "unknown")
    quality = float(market_snapshot.get("data_quality") or 0.5)

    scripts = [
        f"Observed {symbol}; data_quality={quality:.2f}; trend={trend}.",
        f"Technical read on {symbol}: trend={trend}; no fabricated levels.",
        f"Narrative: thin context — favor caution unless quality > 0.7.",
        (
            f"Propose BUY {symbol} size ${default_notional:.2f}"
            if quality >= 0.65 and trend in ("up", "bullish")
            else f"Propose HOLD {symbol} — edge unclear."
        ),
        (
            "Risk critic: size within limits; veto if quality < 0.5."
            if quality >= 0.5
            else "Risk critic: VETO — data quality too low."
        ),
        "Coordinator synthesizes final action under risk gate.",
    ]

    for (role, _), line in zip(ROLES, scripts):
        result.conversation.append({"role": role, "summary": line})

    if quality < 0.5:
        result.vetoed = True
        result.veto_reason = "data quality below 0.5"
        result.proposal = Proposal("hold", symbol, 0.0, quality, result.veto_reason, book)
        return result

    if quality >= 0.65 and trend in ("up", "bullish"):
        result.proposal = Proposal(
            "buy", symbol, default_notional, quality, "scripted momentum buy", book
        )
    elif quality >= 0.65 and trend in ("down", "bearish"):
        result.proposal = Proposal(
            "sell", symbol, default_notional, quality, "scripted momentum exit/short", book
        )
    else:
        result.proposal = Proposal("hold", symbol, 0.0, quality, "no clear edge", book)
    return result
