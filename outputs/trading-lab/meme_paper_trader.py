"""Deterministic, persistent Solana meme-coin paper trader.

This module never creates a wallet or submits transactions. It deliberately
fails closed on incomplete token safety checks and records every decision.
"""
import json
import math
import sqlite3
import time
from pathlib import Path


class MemePaperTrader:
    def __init__(self, db_path="meme-trader.sqlite", clock=None, initial_cash=1000.0,
                 position_usd=50.0, max_positions=3, daily_loss_limit=50.0,
                 stop_loss_pct=0.12, take_profit_pct=0.20, max_hold_seconds=4 * 3600,
                 fee_bps=30.0, slippage_bps=50.0, min_score=75.0,
                 min_liquidity_usd=25000.0, min_volume_24h_usd=50000.0,
                 min_transactions_24h=150, min_buy_ratio=0.52, max_buy_ratio=0.80,
                 max_entry_change_1h_pct=25.0):
        self.db_path = str(db_path)
        self.clock = clock or time.time
        self.initial_cash = self._positive(initial_cash, "initial_cash")
        self.position_usd = self._positive(position_usd, "position_usd")
        self.max_positions = int(max_positions)
        self.daily_loss_limit = self._positive(daily_loss_limit, "daily_loss_limit")
        self.stop_loss_pct = self._fraction(stop_loss_pct, "stop_loss_pct")
        self.take_profit_pct = self._fraction(take_profit_pct, "take_profit_pct")
        self.max_hold_seconds = int(max_hold_seconds)
        self.fee_bps = self._nonnegative(fee_bps, "fee_bps")
        self.slippage_bps = self._nonnegative(slippage_bps, "slippage_bps")
        self.min_score = float(min_score)
        self.min_liquidity_usd = self._positive(min_liquidity_usd, "min_liquidity_usd")
        self.min_volume_24h_usd = self._positive(min_volume_24h_usd, "min_volume_24h_usd")
        self.min_transactions_24h = int(min_transactions_24h)
        self.min_buy_ratio = float(min_buy_ratio)
        self.max_buy_ratio = float(max_buy_ratio)
        self.max_entry_change_1h_pct = float(max_entry_change_1h_pct)
        if self.max_positions < 1 or self.max_hold_seconds < 1:
            raise ValueError("max_positions and max_hold_seconds must be positive")
        if not 0 <= self.min_buy_ratio <= self.max_buy_ratio <= 1:
            raise ValueError("buy-ratio limits must be between zero and one")
        self._init_db()

    @staticmethod
    def _positive(value, name):
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError(name + " must be finite and positive")
        return number

    @staticmethod
    def _nonnegative(value, name):
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(name + " must be finite and non-negative")
        return number

    @staticmethod
    def _fraction(value, name):
        number = float(value)
        if not math.isfinite(number) or not 0 < number < 1:
            raise ValueError(name + " must be between zero and one")
        return number

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS meme_trader_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS meme_trader_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, token_address TEXT NOT NULL,
                symbol TEXT NOT NULL, entry_price REAL NOT NULL, current_price REAL NOT NULL,
                notional REAL NOT NULL, quantity REAL NOT NULL, entry_cost REAL NOT NULL,
                opened_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN',
                closed_at REAL, exit_price REAL, exit_cost REAL, realized_pnl REAL,
                exit_reason TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS meme_trader_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
                event_type TEXT NOT NULL, token_address TEXT, symbol TEXT,
                details_json TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_meme_trader_positions_status ON meme_trader_positions(status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_meme_trader_events_created ON meme_trader_events(created_at)")
            db.execute("INSERT OR IGNORE INTO meme_trader_meta(key,value) VALUES('cash',?)",
                       (str(self.initial_cash),))
            db.execute("INSERT OR IGNORE INTO meme_trader_meta(key,value) VALUES('daily_date',?)",
                       (self._day(self.clock()),))
            db.execute("INSERT OR IGNORE INTO meme_trader_meta(key,value) VALUES('daily_realized_loss','0')")

    @staticmethod
    def _day(timestamp):
        return time.strftime("%Y-%m-%d", time.gmtime(timestamp))

    def _meta(self, db, key):
        row = db.execute("SELECT value FROM meme_trader_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, db, key, value):
        db.execute("INSERT INTO meme_trader_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (key, str(value)))

    def _event(self, db, event_type, candidate=None, **details):
        candidate = candidate or {}
        db.execute("INSERT INTO meme_trader_events(created_at,event_type,token_address,symbol,details_json) VALUES(?,?,?,?,?)",
                   (float(self.clock()), event_type, candidate.get("token_address"),
                    candidate.get("symbol"), json.dumps(details, separators=(",", ":"), allow_nan=False)))

    def _cost_rate(self):
        return (self.fee_bps + self.slippage_bps) / 10000.0

    def _daily_rollover(self, db):
        today = self._day(self.clock())
        if self._meta(db, "daily_date") != today:
            self._set_meta(db, "daily_date", today)
            self._set_meta(db, "daily_realized_loss", "0")

    def _open_positions(self, db):
        return db.execute("SELECT * FROM meme_trader_positions WHERE status='OPEN' ORDER BY opened_at,id").fetchall()

    def _update_positions(self, db, price_lookup):
        now = float(self.clock())
        actions = []
        for row in self._open_positions(db):
            try:
                price = price_lookup(row["token_address"])
                price = float(price) if price is not None else None
                if price is None or not math.isfinite(price) or price <= 0:
                    self._event(db, "PRICE_UNAVAILABLE", {"token_address": row["token_address"], "symbol": row["symbol"]})
                    continue
            except Exception:
                self._event(db, "PRICE_UNAVAILABLE", {"token_address": row["token_address"], "symbol": row["symbol"]})
                continue
            gross_return = price / row["entry_price"] - 1.0
            age = now - row["opened_at"]
            reason = None
            if gross_return <= -self.stop_loss_pct:
                reason = "STOP_LOSS"
            elif gross_return >= self.take_profit_pct:
                reason = "TAKE_PROFIT"
            elif age >= self.max_hold_seconds:
                reason = "MAX_HOLD_TIME"
            db.execute("UPDATE meme_trader_positions SET current_price=? WHERE id=?", (price, row["id"]))
            if reason:
                self._close(db, row, price, reason)
                actions.append({"action": "CLOSE", "position_id": row["id"], "symbol": row["symbol"],
                                "reason": reason, "price_usd": price})
        return actions

    def _close(self, db, row, price, reason):
        cash = float(self._meta(db, "cash"))
        exit_notional = row["quantity"] * price
        exit_cost = exit_notional * self._cost_rate()
        gross_pnl = (price - row["entry_price"]) * row["quantity"]
        realized = gross_pnl - row["entry_cost"] - exit_cost
        cash += exit_notional - exit_cost
        self._set_meta(db, "cash", cash)
        loss = max(0.0, -realized)
        daily_loss = float(self._meta(db, "daily_realized_loss") or 0)
        self._set_meta(db, "daily_realized_loss", daily_loss + loss)
        db.execute("""UPDATE meme_trader_positions SET status='CLOSED',closed_at=?,exit_price=?,
                      exit_cost=?,realized_pnl=?,exit_reason=?,current_price=? WHERE id=?""",
                   (float(self.clock()), price, exit_cost, realized, reason, price, row["id"]))
        self._event(db, "POSITION_CLOSED", {"token_address": row["token_address"], "symbol": row["symbol"]},
                    position_id=row["id"], reason=reason, entry_price=row["entry_price"],
                    exit_price=price, gross_pnl=round(gross_pnl, 8),
                    entry_cost=round(row["entry_cost"], 8), exit_cost=round(exit_cost, 8),
                    realized_pnl=round(realized, 8))

    def _rejection(self, db, candidate, reason, **details):
        self._event(db, "REJECTED", candidate, reason=reason, **details)
        return {"action": "REJECT", "symbol": candidate.get("symbol", "UNKNOWN"),
                "token_address": candidate.get("token_address"), "reason": reason}

    def _candidate_reason(self, candidate):
        if candidate.get("decision") != "WATCH":
            return "market_screen_rejected"
        try:
            score = float(candidate.get("score"))
            liquidity = float(candidate.get("liquidity_usd"))
            volume = float(candidate.get("volume_24h_usd"))
            txns = int(candidate.get("transactions_24h"))
            buy_ratio = float(candidate.get("buy_ratio"))
            change = float(candidate.get("price_change_1h_pct"))
            price = float(candidate.get("price_usd"))
        except (TypeError, ValueError, OverflowError):
            return "invalid_or_missing_market_data"
        values = (score, liquidity, volume, buy_ratio, change, price)
        if not all(math.isfinite(x) for x in values) or price <= 0:
            return "invalid_or_missing_market_data"
        if score < self.min_score:
            return "score_below_entry_threshold"
        if liquidity < self.min_liquidity_usd:
            return "liquidity_below_entry_threshold"
        if volume < self.min_volume_24h_usd:
            return "volume_below_entry_threshold"
        if txns < self.min_transactions_24h:
            return "activity_below_entry_threshold"
        if not self.min_buy_ratio <= buy_ratio <= self.max_buy_ratio:
            return "buy_ratio_outside_entry_band"
        if change > self.max_entry_change_1h_pct:
            return "momentum_chase_filter"
        if change < -10:
            return "negative_momentum_filter"
        return None

    def run_cycle(self, candidates, safety_check, price_lookup):
        """Refresh exits, then consider candidates. All buys are paper-only."""
        candidates = candidates if isinstance(candidates, list) else []
        decisions = []
        with self._connect() as db:
            self._daily_rollover(db)
            exit_actions = self._update_positions(db, price_lookup)
            decisions.extend(exit_actions)
            cash = float(self._meta(db, "cash"))
            daily_loss = float(self._meta(db, "daily_realized_loss") or 0)
            open_rows = self._open_positions(db)
            if daily_loss >= self.daily_loss_limit:
                for c in candidates:
                    if c.get("decision") == "WATCH":
                        decisions.append(self._rejection(db, c, "daily_loss_limit_reached"))
                self._event(db, "RISK_HALT", reason="daily_loss_limit_reached", daily_realized_loss=daily_loss)
                return {"decisions": decisions, "risk_halted": True, "execution_enabled": False}
            open_addresses = {r["token_address"].lower() for r in open_rows}
            for candidate in sorted(candidates, key=lambda c: float(c.get("score") or 0), reverse=True):
                reason = self._candidate_reason(candidate)
                if reason:
                    if candidate.get("decision") == "WATCH":
                        decisions.append(self._rejection(db, candidate, reason))
                    continue
                address = str(candidate.get("token_address") or "").strip()
                if not address:
                    decisions.append(self._rejection(db, candidate, "missing_token_address"))
                    continue
                if address.lower() in open_addresses:
                    decisions.append(self._rejection(db, candidate, "position_already_open"))
                    continue
                if len(open_addresses) >= self.max_positions:
                    decisions.append(self._rejection(db, candidate, "max_open_positions_reached"))
                    continue
                notional = min(self.position_usd, cash / (1 + self._cost_rate()))
                if notional < 1:
                    decisions.append(self._rejection(db, candidate, "insufficient_paper_cash"))
                    continue
                try:
                    safety = safety_check(address)
                except Exception as exc:
                    safety = {"status": "INCOMPLETE", "error": type(exc).__name__}
                if not isinstance(safety, dict) or safety.get("status") != "CHECKS_COMPLETE":
                    decisions.append(self._rejection(db, candidate, "security_check_incomplete"))
                    continue
                if safety.get("mint_authority_active") is not False or safety.get("freeze_authority_active") is not False:
                    decisions.append(self._rejection(db, candidate, "active_or_unknown_token_authority"))
                    continue
                if safety.get("highest_finding_severity") == "high":
                    decisions.append(self._rejection(db, candidate, "high_severity_security_finding"))
                    continue
                concentration = safety.get("top_20_token_accounts_supply_pct")
                if not isinstance(concentration, (int, float)) or not math.isfinite(concentration) or concentration >= 80:
                    decisions.append(self._rejection(db, candidate, "holder_concentration_unavailable_or_high"))
                    continue
                try:
                    price = float(price_lookup(address))
                except Exception:
                    price = 0
                if not math.isfinite(price) or price <= 0:
                    decisions.append(self._rejection(db, candidate, "current_price_unavailable"))
                    continue
                # Use the latest validated provider price rather than a stale scan price.
                entry_cost = notional * self._cost_rate()
                quantity = notional / price
                cash -= notional + entry_cost
                self._set_meta(db, "cash", cash)
                cursor = db.execute("""INSERT INTO meme_trader_positions
                    (token_address,symbol,entry_price,current_price,notional,quantity,entry_cost,opened_at,status)
                    VALUES(?,?,?,?,?,?,?,?, 'OPEN')""",
                    (address, str(candidate.get("symbol") or "UNKNOWN")[:80], price,
                     price, notional, quantity, entry_cost, float(self.clock())))
                position_id = cursor.lastrowid
                open_addresses.add(address.lower())
                open_rows = self._open_positions(db)
                details = {"position_id": position_id, "price_usd": price,
                           "notional_usd": round(notional, 2), "quantity": quantity,
                           "score": candidate.get("score"), "safety_status": safety["status"],
                           "modeled_entry_cost_usd": round(entry_cost, 6),
                           "stop_loss_price": price * (1 - self.stop_loss_pct),
                           "take_profit_price": price * (1 + self.take_profit_pct)}
                self._event(db, "POSITION_OPENED", candidate, **details)
                decisions.append({"action": "OPEN", "symbol": candidate.get("symbol"),
                                  "token_address": address, **details})
            return {"decisions": decisions, "risk_halted": False, "execution_enabled": False}

    def tick(self, price_lookup):
        with self._connect() as db:
            self._daily_rollover(db)
            actions = self._update_positions(db, price_lookup)
        return {"decisions": actions, "execution_enabled": False}

    def status(self):
        with self._connect() as db:
            cash = float(self._meta(db, "cash"))
            daily_loss = float(self._meta(db, "daily_realized_loss") or 0)
            positions = [dict(r) for r in db.execute(
                "SELECT * FROM meme_trader_positions ORDER BY id DESC LIMIT 200").fetchall()]
            events = [dict(r) for r in db.execute(
                "SELECT * FROM meme_trader_events ORDER BY id DESC LIMIT 100").fetchall()]
        open_positions = [p for p in positions if p["status"] == "OPEN"]
        gross_value = sum(p["quantity"] * p["current_price"] for p in open_positions)
        unrealized = sum((p["current_price"] - p["entry_price"]) * p["quantity"] - p["entry_cost"]
                         - p["quantity"] * p["current_price"] * self._cost_rate()
                         for p in open_positions)
        realized = sum(float(p["realized_pnl"] or 0) for p in positions if p["status"] == "CLOSED")
        equity = cash + gross_value - gross_value * self._cost_rate()
        return {
            "mode": "autonomous_paper_trading", "execution_enabled": False,
            "risk_halted": daily_loss >= self.daily_loss_limit,
            "cash_usd": round(cash, 4), "equity_usd": round(equity, 4),
            "initial_cash_usd": self.initial_cash,
            "realized_pnl_usd": round(realized, 4), "unrealized_pnl_usd": round(unrealized, 4),
            "daily_realized_loss_usd": round(daily_loss, 4),
            "open_positions_count": len(open_positions),
            "max_open_positions": self.max_positions,
            "cost_assumptions": {"fee_bps_per_side": self.fee_bps,
                                 "slippage_bps_per_side": self.slippage_bps,
                                 "modeled_cost_pct_per_side": round(self._cost_rate() * 100, 4)},
            "config": {"position_usd": self.position_usd, "stop_loss_pct": self.stop_loss_pct,
                       "take_profit_pct": self.take_profit_pct, "max_hold_seconds": self.max_hold_seconds,
                       "min_score": self.min_score, "min_liquidity_usd": self.min_liquidity_usd,
                       "min_volume_24h_usd": self.min_volume_24h_usd,
                       "daily_loss_limit_usd": self.daily_loss_limit},
            "positions": positions, "events": [
                {**{k: v for k, v in e.items() if k != "details_json"},
                 "details": json.loads(e["details_json"])} for e in events
            ],
            "limitations": ["Paper prices are provider quotes, not executable fills.",
                            "Public RPC safety checks are indicators, not a token audit.",
                            "A failed or incomplete safety check blocks entry.",
                            "No wallet, swap, or live transaction capability exists."],
        }
