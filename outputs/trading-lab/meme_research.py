"""Read-only Solana meme-coin discovery and market-quality screening.

This module deliberately does not connect a wallet, prepare swaps, or submit
transactions. Passing market filters is not a contract-security assessment.
"""
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


BASE_URL = "https://api.dexscreener.com"
USER_AGENT = "TradingBo-MemeResearch/0.1"


def _fetch_json(url, timeout=10):
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(2_000_000))


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _positive(value):
    result = _number(value, 0.0)
    return result if result > 0 else 0.0


class MemeResearchConfig:
    """Conservative market-data filters; these are not investment advice."""

    def __init__(
        self,
        min_liquidity_usd=10_000.0,
        min_volume_24h_usd=20_000.0,
        min_transactions_24h=100,
        min_pair_age_minutes=5,
        max_pair_age_hours=72,
        max_1h_pump_pct=80.0,
        min_score=65.0,
    ):
        self.min_liquidity_usd = float(min_liquidity_usd)
        self.min_volume_24h_usd = float(min_volume_24h_usd)
        self.min_transactions_24h = int(min_transactions_24h)
        self.min_pair_age_minutes = int(min_pair_age_minutes)
        self.max_pair_age_hours = float(max_pair_age_hours)
        self.max_1h_pump_pct = float(max_1h_pump_pct)
        self.min_score = float(min_score)


class MemeCoinResearchEngine:
    """Discover candidates from DexScreener and score market structure only."""

    def __init__(self, fetch_json=None, config=None, clock=None):
        self.fetch_json = fetch_json or _fetch_json
        self.config = config or MemeResearchConfig()
        self.clock = clock or time.time
        self.last_result = None

    def _discover(self):
        # Profile and boost lists are discovery sources, not quality signals.
        profiles = self.fetch_json(BASE_URL + "/token-profiles/latest/v1")
        boosts = self.fetch_json(BASE_URL + "/token-boosts/latest/v1")
        discovered = {}
        for source, rows in (("profile", profiles), ("boost", boosts)):
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                chain = str(row.get("chainId") or "").lower()
                address = str(row.get("tokenAddress") or "").strip()
                if chain != "solana" or not address:
                    continue
                key = address.lower()
                if key not in discovered:
                    discovered[key] = {
                        "chain_id": "solana",
                        "token_address": address,
                        "discovery_sources": [],
                    }
                if source not in discovered[key]["discovery_sources"]:
                    discovered[key]["discovery_sources"].append(source)
        return list(discovered.values())

    def _score_pair(self, pair, discovery):
        cfg = self.config
        base = pair.get("baseToken") or {}
        liquidity = _positive((pair.get("liquidity") or {}).get("usd"))
        volume = _positive((pair.get("volume") or {}).get("h24"))
        txns = pair.get("txns") or {}
        tx24 = txns.get("h24") or {}
        buys = max(0, int(_number(tx24.get("buys"), 0)))
        sells = max(0, int(_number(tx24.get("sells"), 0)))
        transactions = buys + sells
        price = _positive(pair.get("priceUsd"))
        created_ms = _number(pair.get("pairCreatedAt"), 0)
        age_minutes = max(0.0, (self.clock() * 1000 - created_ms) / 60_000) if created_ms else None
        changes = pair.get("priceChange") or {}
        change_1h = _number(changes.get("h1"), 0.0)
        change_24h = _number(changes.get("h24"), 0.0)
        reasons = []

        if liquidity < cfg.min_liquidity_usd:
            reasons.append("liquidity_below_minimum")
        if volume < cfg.min_volume_24h_usd:
            reasons.append("volume_below_minimum")
        if transactions < cfg.min_transactions_24h:
            reasons.append("too_few_24h_transactions")
        if not price:
            reasons.append("missing_or_invalid_usd_price")
        if age_minutes is None:
            reasons.append("missing_pair_creation_time")
        elif age_minutes < cfg.min_pair_age_minutes:
            reasons.append("pair_too_new_for_screening")
        elif age_minutes > cfg.max_pair_age_hours * 60:
            reasons.append("pair_older_than_screening_window")
        if change_1h > cfg.max_1h_pump_pct:
            reasons.append("one_hour_pump_chase_filter")

        # Bounded heuristic score: liquidity, turnover, activity, buy/sell
        # balance, and modest positive momentum. No paid-promotion bonus.
        liquidity_score = min(25.0, 25.0 * liquidity / (liquidity + 40_000.0)) if liquidity else 0.0
        turnover = volume / liquidity if liquidity else 0.0
        turnover_score = min(20.0, max(0.0, turnover) * 10.0)
        activity_score = min(20.0, transactions / 25.0)
        buy_ratio = buys / transactions if transactions else 0.0
        balance_score = 20.0 * min(1.0, buy_ratio / 0.60)
        momentum_score = min(15.0, max(0.0, change_1h) * 0.3)
        score = round(min(100.0, liquidity_score + turnover_score + activity_score + balance_score + momentum_score), 2)

        if reasons:
            decision = "REJECT"
        elif score >= cfg.min_score:
            decision = "WATCH"
        else:
            decision = "REJECT"

        return {
            **discovery,
            "name": str(base.get("name") or "Unknown"),
            "symbol": str(base.get("symbol") or "UNKNOWN"),
            "pair_address": str(pair.get("pairAddress") or ""),
            "dex_id": str(pair.get("dexId") or ""),
            "pair_url": str(pair.get("url") or ""),
            "price_usd": price or None,
            "liquidity_usd": round(liquidity, 2),
            "volume_24h_usd": round(volume, 2),
            "transactions_24h": transactions,
            "buys_24h": buys,
            "sells_24h": sells,
            "buy_ratio": round(buy_ratio, 4),
            "pair_age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
            "price_change_1h_pct": round(change_1h, 2),
            "price_change_24h_pct": round(change_24h, 2),
            "score": score,
            "decision": decision,
            "rejection_reasons": reasons,
            "security_checks": "not_checked",
            "execution_enabled": False,
        }

    def run(self, limit=20):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer from 1 to 30")
        if not 1 <= limit <= 30:
            raise ValueError("limit must be an integer from 1 to 30")

        discovered = self._discover()[:limit]
        candidates = []
        errors = []
        for token in discovered:
            address = urllib.parse.quote(token["token_address"], safe="")
            url = f"{BASE_URL}/token-pairs/v1/solana/{address}"
            try:
                pairs = self.fetch_json(url)
                if not isinstance(pairs, list):
                    errors.append({"token_address": token["token_address"], "error": "invalid_pair_response"})
                    continue
                matching = [
                    p for p in pairs
                    if isinstance(p, dict)
                    and str(p.get("chainId") or "").lower() == "solana"
                    and str((p.get("baseToken") or {}).get("address") or "").lower()
                    == token["token_address"].lower()
                ]
                if not matching:
                    errors.append({"token_address": token["token_address"], "error": "no_matching_solana_pairs"})
                    continue
                best = max(
                    matching,
                    key=lambda p: _positive((p.get("liquidity") or {}).get("usd")),
                )
                candidates.append(self._score_pair(best, token))
            except Exception as exc:
                # A single provider error must not erase the other candidates.
                errors.append({
                    "token_address": token["token_address"],
                    "error": type(exc).__name__,
                })

        candidates.sort(key=lambda item: (item["decision"] == "WATCH", item["score"]), reverse=True)
        result = {
            "generated_at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
            "provider": "DexScreener public API",
            "mode": "research_only",
            "chain": "solana",
            "discovered_tokens": len(discovered),
            "scored_candidates": len(candidates),
            "watchlist_count": sum(c["decision"] == "WATCH" for c in candidates),
            "candidates": candidates,
            "errors": errors,
            "limitations": [
                "Market-data filters are not a contract audit or rug-pull detector.",
                "Holder concentration, mint/freeze authority, and sellability are not checked.",
                "Paid profiles or boosts are discovery sources only and do not increase score.",
                "No wallet, swap preparation, or transaction submission is available.",
            ],
            "execution_enabled": False,
        }
        self.last_result = result
        return result
