"""Persistent, read-only paper evaluation for meme-coin research candidates.

This module records WATCH candidates at their observed USD price, then samples
prices after fixed horizons. It never creates a wallet, swap, or live order.
Forward returns are only as good as the sampled provider prices; they are not
historical candle backtests or evidence of executable fills.
"""
import json
import math
import sqlite3
import time
import urllib.parse
from pathlib import Path

from meme_research import BASE_URL, _fetch_json, _positive

HORIZONS_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "24h": 86400}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


class MemePaperTracker:
    """Store WATCH snapshots and estimate forward returns with explicit costs."""

    def __init__(self, db_path="meme-paper.sqlite", fetch_json=None, clock=None,
                 slippage_bps=50.0, fee_bps=30.0):
        self.db_path = str(db_path)
        self.fetch_json = fetch_json or _fetch_json
        self.clock = clock or time.time
        self.slippage_bps = float(slippage_bps)
        self.fee_bps = float(fee_bps)
        if not math.isfinite(self.slippage_bps) or self.slippage_bps < 0:
            raise ValueError("slippage_bps must be a finite non-negative number")
        if not math.isfinite(self.fee_bps) or self.fee_bps < 0:
            raise ValueError("fee_bps must be a finite non-negative number")
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS meme_paper_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_address TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    score REAL NOT NULL,
                    entry_price_usd REAL NOT NULL,
                    observed_at REAL NOT NULL,
                    outcomes_json TEXT NOT NULL DEFAULT '{}'
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_meme_paper_pending ON meme_paper_entries(observed_at)")

    def record_scan(self, candidates):
        """Record valid WATCH candidates only; each scan is a separate sample."""
        now = float(self.clock())
        recorded = 0
        with self._connect() as db:
            for candidate in candidates if isinstance(candidates, list) else []:
                if not isinstance(candidate, dict) or candidate.get("decision") != "WATCH":
                    continue
                price = _finite(candidate.get("price_usd"))
                address = str(candidate.get("token_address") or "").strip()
                if not address or price is None:
                    continue
                db.execute(
                    """INSERT INTO meme_paper_entries
                       (token_address, symbol, decision, score, entry_price_usd, observed_at)
                       VALUES (?, ?, 'WATCH', ?, ?, ?)""",
                    (address, str(candidate.get("symbol") or "UNKNOWN")[:80],
                     float(candidate.get("score") or 0), price, now),
                )
                recorded += 1
        return {"recorded": recorded, "execution_enabled": False}

    def _current_prices(self, addresses):
        prices = {}
        for address in addresses:
            safe = urllib.parse.quote(address, safe="")
            try:
                pairs = self.fetch_json(f"{BASE_URL}/token-pairs/v1/solana/{safe}")
                if not isinstance(pairs, list):
                    continue
                matching = [
                    pair for pair in pairs
                    if isinstance(pair, dict)
                    and str(pair.get("chainId") or "").lower() == "solana"
                    and str((pair.get("baseToken") or {}).get("address") or "").lower() == address.lower()
                ]
                if matching:
                    best = max(matching, key=lambda pair: _positive((pair.get("liquidity") or {}).get("usd")))
                    price = _finite(best.get("priceUsd"))
                    if price is not None:
                        prices[address.lower()] = price
            except Exception:
                # Provider failure leaves the outcome pending; it is never scored as zero.
                continue
        return prices

    def update_due(self):
        """Sample current prices for snapshots whose horizon has elapsed."""
        now = float(self.clock())
        with self._connect() as db:
            rows = db.execute("SELECT * FROM meme_paper_entries ORDER BY observed_at ASC").fetchall()
        pending_by_address = {}
        for row in rows:
            outcomes = json.loads(row["outcomes_json"] or "{}")
            due = [name for name, seconds in HORIZONS_SECONDS.items()
                   if name not in outcomes and now >= row["observed_at"] + seconds]
            if due:
                pending_by_address.setdefault(row["token_address"], []).append((row, outcomes, due))
        prices = self._current_prices(list(pending_by_address))
        updated = 0
        round_trip_cost_pct = 2.0 * (self.slippage_bps + self.fee_bps) / 100.0
        with self._connect() as db:
            for address, items in pending_by_address.items():
                current = prices.get(address.lower())
                if current is None:
                    continue
                for row, outcomes, due in items:
                    entry = float(row["entry_price_usd"])
                    gross = (current / entry - 1.0) * 100.0
                    net = gross - round_trip_cost_pct
                    for horizon in due:
                        outcomes[horizon] = {
                            "sampled_at": now,
                            "sample_delay_seconds": max(0.0, now - row["observed_at"] - HORIZONS_SECONDS[horizon]),
                            "price_usd": current,
                            "gross_return_pct": round(gross, 6),
                            "net_return_pct": round(net, 6),
                            "modeled_round_trip_cost_pct": round(round_trip_cost_pct, 6),
                        }
                    db.execute("UPDATE meme_paper_entries SET outcomes_json=? WHERE id=?",
                               (json.dumps(outcomes, separators=(",", ":"), allow_nan=False), row["id"]))
                    updated += len(due)
        return {"outcomes_updated": updated, "snapshots_checked": len(rows),
                "modeled_round_trip_cost_pct": round(round_trip_cost_pct, 6),
                "execution_enabled": False}

    def status(self):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM meme_paper_entries ORDER BY observed_at DESC").fetchall()
        by_horizon = {}
        for horizon in HORIZONS_SECONDS:
            returns = []
            for row in rows:
                outcome = json.loads(row["outcomes_json"] or "{}").get(horizon)
                if outcome and isinstance(outcome.get("net_return_pct"), (int, float)):
                    returns.append(float(outcome["net_return_pct"]))
            by_horizon[horizon] = {
                "samples": len(returns),
                "average_net_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
                "win_rate_pct": round(100.0 * sum(value > 0 for value in returns) / len(returns), 2) if returns else None,
                "execution_enabled": False,
            }
        pending = 0
        for row in rows:
            outcomes = json.loads(row["outcomes_json"] or "{}")
            pending += sum(h not in outcomes for h in HORIZONS_SECONDS)
        return {
            "mode": "paper_evaluation",
            "snapshots": len(rows),
            "pending_horizon_observations": pending,
            "cost_assumptions": {
                "slippage_bps_per_side": self.slippage_bps,
                "fee_bps_per_side": self.fee_bps,
                "modeled_round_trip_cost_pct": round(2.0 * (self.slippage_bps + self.fee_bps) / 100.0, 6),
            },
            "horizons": by_horizon,
            "limitations": [
                "Prices are sampled when the tracker next runs after a horizon, not at an exact historical candle.",
                "Modeled costs are assumptions, not measured execution costs; real meme-coin slippage can be much higher.",
                "Only WATCH candidates with valid observed prices are recorded; missing provider prices remain pending.",
                "This is paper evaluation only; it cannot connect a wallet or submit transactions.",
            ],
            "execution_enabled": False,
        }
