"""Ember Forex Trading Lab HTTP application."""
import argparse
import base64
import hmac
import json
import mimetypes
import os
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import forex_market
from forex_lab import ForexLab
from forex_agents import ForexAgentRuntime
from key_store import KeyStore, PROVIDER_SPECS
from llm_research import ResearchLayer, ModelError, verify_connection
from meme_research import MemeCoinResearchEngine
from meme_safety import SolanaMintSafetyChecker
from meme_paper import MemePaperTracker
from meme_paper_trader import MemePaperTrader

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TRADINGLAB_DATA_DIR", str(ROOT))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_REQUIRED = os.environ.get("TRADINGLAB_AUTH_REQUIRED", "").strip() == "1"
AUTH_USERNAME = os.environ.get("TRADINGLAB_USERNAME", "")
AUTH_PASSWORD = os.environ.get("TRADINGLAB_PASSWORD", "")
LAB = ForexLab(DATA_DIR / "lab.sqlite")
AGENTS = ForexAgentRuntime(
    DATA_DIR / "lab.sqlite", LAB,
    auto_run=os.environ.get("EMBER_FOREX_AUTORUN", "").strip() == "1",
)
AGENTS.attach_research(None)
KEYS = KeyStore(
    max_calls=int(os.environ.get("FX_MAX_MODEL_CALLS", "40")),
    max_spend=float(os.environ.get("FX_MAX_MODEL_SPEND", "5.0")),
    cost_per_call=float(os.environ.get("FX_MODEL_COST", "0.002")),
)
RESEARCH = ResearchLayer(KEYS)
AGENTS.attach_research(RESEARCH)
MEME_RESEARCH = MemeCoinResearchEngine()
MEME_SAFETY = SolanaMintSafetyChecker()
MEME_PAPER = MemePaperTracker(
    DATA_DIR / "meme-paper.sqlite",
    slippage_bps=float(os.environ.get("MEME_PAPER_SLIPPAGE_BPS", "50")),
    fee_bps=float(os.environ.get("MEME_PAPER_FEE_BPS", "30")),
)
MEME_TRADER = MemePaperTrader(
    DATA_DIR / "meme-trader.sqlite",
    position_usd=float(os.environ.get("MEME_PAPER_POSITION_USD", "50")),
    max_positions=int(os.environ.get("MEME_PAPER_MAX_POSITIONS", "3")),
    daily_loss_limit=float(os.environ.get("MEME_PAPER_DAILY_LOSS_LIMIT_USD", "50")),
    fee_bps=float(os.environ.get("MEME_PAPER_FEE_BPS", "30")),
    slippage_bps=float(os.environ.get("MEME_PAPER_SLIPPAGE_BPS", "50")),
    min_liquidity_usd=float(os.environ.get("MEME_PAPER_MIN_LIQUIDITY_USD", "10000")),
    min_volume_24h_usd=float(os.environ.get("MEME_PAPER_MIN_VOLUME_24H_USD", "25000")),
    min_score=float(os.environ.get("MEME_PAPER_MIN_SCORE", "65")),
    max_entry_change_1h_pct=float(os.environ.get("MEME_PAPER_MAX_ENTRY_CHANGE_1H_PCT", "80")),
)


def meme_current_price(token_address):
    safe = urllib.parse.quote(str(token_address or ""), safe="")
    if not safe:
        return None
    pairs = MEME_RESEARCH.fetch_json(
        f"https://api.dexscreener.com/token-pairs/v1/solana/{safe}"
    )
    if not isinstance(pairs, list):
        return None
    matching = [
        pair for pair in pairs
        if isinstance(pair, dict)
        and str(pair.get("chainId") or "").lower() == "solana"
        and str((pair.get("baseToken") or {}).get("address") or "").lower()
        == str(token_address).lower()
    ]
    if not matching:
        return None
    def liquidity(pair):
        try:
            value = float((pair.get("liquidity") or {}).get("usd") or 0)
            return value if value > 0 and value < float("inf") else 0
        except (TypeError, ValueError, OverflowError):
            return 0
    best = max(matching, key=liquidity)
    try:
        price = float(best.get("priceUsd"))
        return price if price > 0 and price < float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


def run_meme_paper_cycle(limit=30):
    scan = MEME_RESEARCH.run(limit)
    all_candidates = scan.get("candidates", [])
    paper_tracking = MEME_PAPER.record_scan(all_candidates)
    watchlist = sorted(
        (candidate for candidate in all_candidates
         if candidate.get("decision") == "WATCH"),
        key=lambda candidate: float(candidate.get("score") or 0),
        reverse=True,
    )
    candidates = watchlist[:5]
    market_rejection_counts = {}
    for candidate in all_candidates:
        for reason in candidate.get("rejection_reasons", []):
            market_rejection_counts[reason] = market_rejection_counts.get(reason, 0) + 1
    decisions = MEME_TRADER.run_cycle(
        candidates, MEME_SAFETY.check, meme_current_price
    )
    decision_counts = {}
    for decision in decisions.get("decisions", []):
        key = decision.get("reason") or decision.get("action", "unknown").lower()
        decision_counts[key] = decision_counts.get(key, 0) + 1
    return {
        "scan": {
            "generated_at": scan.get("generated_at"),
            "discovered_tokens": scan.get("discovered_tokens", 0),
            "scored_candidates": scan.get("scored_candidates", 0),
            "watchlist_count": scan.get("watchlist_count", 0),
            "watchlist_considered": len(candidates),
            "market_rejected_count": sum(
                1 for candidate in all_candidates if candidate.get("decision") != "WATCH"
            ),
            "market_rejection_reasons": market_rejection_counts,
            "market_rejection_examples": [
                {
                    "name": candidate.get("name", "Unknown"),
                    "symbol": candidate.get("symbol", "UNKNOWN"),
                    "liquidity_usd": candidate.get("liquidity_usd"),
                    "volume_24h_usd": candidate.get("volume_24h_usd"),
                    "price_change_1h_pct": candidate.get("price_change_1h_pct"),
                    "rejection_reasons": candidate.get("rejection_reasons", []),
                }
                for candidate in all_candidates
                if candidate.get("decision") != "WATCH"
            ][:3],
            "errors": scan.get("errors", []),
        },
        "cycle": {**decisions, "decision_counts": decision_counts},
        "status": MEME_TRADER.status(),
        "paper_tracking": paper_tracking,
        "paper_outcome_update": MEME_PAPER.update_due(),
        "paper_status": MEME_PAPER.status(),
        "execution_enabled": False,
    }
