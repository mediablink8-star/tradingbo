"""Hard live-trading risk controls for a capped Solana wallet.

Agents may advise. This module is the only authority that can allow a live order.
Default posture is DISARMED: no new live orders.
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULTS = {
    "wallet_cap_usd": 100.0,
    "max_per_trade_usd": 12.0,
    "max_daily_loss_usd": 25.0,
    "max_open_positions": 2,
    "max_exposure_usd": 30.0,
    "arm_ttl_seconds": 24 * 3600,
}


class LiveRiskEngine:
    def __init__(self, db_path: str | Path, clock=None):
        self.db_path = str(db_path)
        self.clock = clock or time.time
        self._init_db()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS live_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL)"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS live_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL)"""
            )
            for key, value in DEFAULTS.items():
                db.execute(
                    "INSERT OR IGNORE INTO live_meta(key,value) VALUES(?,?)",
                    (key, str(value)),
                )
            db.execute("INSERT OR IGNORE INTO live_meta(key,value) VALUES('armed','0')")
            db.execute("INSERT OR IGNORE INTO live_meta(key,value) VALUES('armed_until','0')")
            db.execute("INSERT OR IGNORE INTO live_meta(key,value) VALUES('daily_date','')")
            db.execute("INSERT OR IGNORE INTO live_meta(key,value) VALUES('daily_realized_loss_usd','0')")
            db.execute("INSERT OR IGNORE INTO live_meta(key,value) VALUES('session_realized_loss_usd','0')")
            db.execute("INSERT OR IGNORE INTO live_meta(key,value) VALUES('live_enabled','0')")

    def _get(self, db, key: str, default: str = "") -> str:
        row = db.execute("SELECT value FROM live_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def _set(self, db, key: str, value: Any) -> None:
        db.execute(
            """INSERT INTO live_meta(key,value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, str(value)),
        )

    def _event(self, db, event_type: str, **details: Any) -> None:
        db.execute(
            """INSERT INTO live_events(created_at,event_type,details_json)
               VALUES(?,?,?)""",
            (float(self.clock()), event_type, json.dumps(details, separators=(",", ":"), allow_nan=False)),
        )

    @staticmethod
    def _day(ts: float) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(ts))

    def _rollover(self, db) -> None:
        today = self._day(self.clock())
        if self._get(db, "daily_date") != today:
            self._set(db, "daily_date", today)
            self._set(db, "daily_realized_loss_usd", "0")

    def _f(self, db, key: str) -> float:
        try:
            return float(self._get(db, key, "0"))
        except (TypeError, ValueError):
            return 0.0

    def _i(self, db, key: str) -> int:
        try:
            return int(float(self._get(db, key, "0")))
        except (TypeError, ValueError):
            return 0

    def is_armed(self) -> bool:
        with self._connect() as db:
            self._rollover(db)
            if self._get(db, "armed") != "1":
                return False
            until = self._f(db, "armed_until")
            now = float(self.clock())
            if until <= now:
                self._set(db, "armed", "0")
                self._event(db, "AUTO_DISARM", reason="arm_ttl_expired")
                return False
            return True

    def arm(self, actor: str = "operator") -> Dict[str, Any]:
        with self._connect() as db:
            self._rollover(db)
            ttl = self._f(db, "arm_ttl_seconds") or DEFAULTS["arm_ttl_seconds"]
            until = float(self.clock()) + ttl
            self._set(db, "armed", "1")
            self._set(db, "armed_until", str(until))
            self._event(db, "ARMED", actor=actor, armed_until=until, ttl_seconds=ttl)
            return self.status()

    def disarm(self, actor: str = "operator", reason: str = "manual") -> Dict[str, Any]:
        with self._connect() as db:
            self._set(db, "armed", "0")
            self._set(db, "armed_until", "0")
            self._event(db, "DISARMED", actor=actor, reason=reason)
            return self.status()

    def record_realized_loss(self, loss_usd: float) -> Dict[str, Any]:
        loss_usd = max(0.0, float(loss_usd))
        with self._connect() as db:
            self._rollover(db)
            daily = self._f(db, "daily_realized_loss_usd") + loss_usd
            session = self._f(db, "session_realized_loss_usd") + loss_usd
            self._set(db, "daily_realized_loss_usd", daily)
            self._set(db, "session_realized_loss_usd", session)
            self._event(db, "LOSS_RECORDED", loss_usd=loss_usd, daily=daily, session=session)
            limit = self._f(db, "max_daily_loss_usd")
            if daily >= limit:
                self._set(db, "armed", "0")
                self._set(db, "armed_until", "0")
                self._event(db, "AUTO_DISARM", reason="daily_loss_limit", daily_realized_loss_usd=daily, max_daily_loss_usd=limit)
            return self.status()

    def can_open(self, notional_usd: float, open_positions: int, current_exposure_usd: float) -> Dict[str, Any]:
        reasons = []
        with self._connect() as db:
            self._rollover(db)
            armed = self._get(db, "armed") == "1"
            until = self._f(db, "armed_until")
            now = float(self.clock())
            if not armed or until <= now:
                if armed and until <= now:
                    self._set(db, "armed", "0")
                    self._event(db, "AUTO_DISARM", reason="arm_ttl_expired")
                reasons.append("disarmed")
            max_trade = self._f(db, "max_per_trade_usd")
            max_daily = self._f(db, "max_daily_loss_usd")
            max_pos = self._i(db, "max_open_positions")
            max_exp = self._f(db, "max_exposure_usd")
            daily_loss = self._f(db, "daily_realized_loss_usd")
            try:
                notional = float(notional_usd)
            except (TypeError, ValueError):
                notional = 0.0
            if not math.isfinite(notional) or notional <= 0:
                reasons.append("invalid_notional")
            elif notional > max_trade + 1e-9:
                reasons.append("above_max_per_trade")
            if open_positions >= max_pos:
                reasons.append("max_open_positions")
            if current_exposure_usd + max(0.0, notional) > max_exp + 1e-9:
                reasons.append("above_max_exposure")
            if daily_loss >= max_daily:
                reasons.append("daily_loss_limit")
            allowed = not reasons
            result = {
                "allowed": allowed,
                "reasons": reasons,
                "notional_usd": notional,
                "limits": {
                    "max_per_trade_usd": max_trade,
                    "max_daily_loss_usd": max_daily,
                    "max_open_positions": max_pos,
                    "max_exposure_usd": max_exp,
                },
                "daily_realized_loss_usd": daily_loss,
                "armed": armed and until > now,
            }
            self._event(db, "GATE_CHECK", **result)
            return result

    def status(self) -> Dict[str, Any]:
        with self._connect() as db:
            self._rollover(db)
            armed = self._get(db, "armed") == "1"
            until = self._f(db, "armed_until")
            now = float(self.clock())
            if armed and until <= now:
                self._set(db, "armed", "0")
                armed = False
                until = 0.0
            events = [
                dict(r)
                for r in db.execute(
                    """SELECT id, created_at, event_type, details_json
                       FROM live_events ORDER BY id DESC LIMIT 30"""
                ).fetchall()
            ]
            for e in events:
                try:
                    e["details"] = json.loads(e.pop("details_json"))
                except Exception:
                    e["details"] = {}
            return {
                "mode": "live_risk_gate",
                "armed": bool(armed),
                "armed_until": until if armed else None,
                "seconds_remaining": max(0, int(until - now)) if armed else 0,
                "wallet_cap_usd": self._f(db, "wallet_cap_usd"),
                "max_per_trade_usd": self._f(db, "max_per_trade_usd"),
                "max_daily_loss_usd": self._f(db, "max_daily_loss_usd"),
                "max_open_positions": self._i(db, "max_open_positions"),
                "max_exposure_usd": self._f(db, "max_exposure_usd"),
                "daily_realized_loss_usd": self._f(db, "daily_realized_loss_usd"),
                "session_realized_loss_usd": self._f(db, "session_realized_loss_usd"),
                "live_execution_enabled": False,
                "note": (
                    "DISARMED by default. ARM from the phone to allow gated live "
                    "orders for up to 24h. Agents cannot arm or raise limits. "
                    "On-chain signing is not enabled until a separate live "
                    "execution key is configured and tested."
                ),
                "events": events,
            }
