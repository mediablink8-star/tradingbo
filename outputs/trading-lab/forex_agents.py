"""Transparent, bounded multi-stage FX paper-agent pipeline.

No LLM or broker credentials are used. The research and strategy agents only
consume observed quotes; deterministic risk controls remain the final authority.
"""
import json
import math
import sqlite3
import time
import uuid

MAX_HISTORY = 5
MIN_OBSERVATIONS = 3
MOMENTUM_THRESHOLD = 0.0003
PAPER_NOTIONAL = 250.0


class ForexAgentRuntime:
    def __init__(self, path, lab, auto_run=False, interval=60.0):
        self.path = str(path)
        self.lab = lab
        self.auto_run = bool(auto_run)
        self.interval = max(15.0, float(interval))
        self.last_cycle = 0.0
        self._init_db()

    def _db(self):
        return sqlite3.connect(self.path, timeout=15)

    def _init_db(self):
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fx_agent_samples(
                pair TEXT NOT NULL, observed REAL NOT NULL, price REAL NOT NULL,
                provider_date TEXT NOT NULL, stored REAL NOT NULL,
                PRIMARY KEY(pair, observed))""")
            db.execute("""CREATE TABLE IF NOT EXISTS fx_agent_events(
                id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, timestamp REAL NOT NULL,
                agent TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                approve_json TEXT NOT NULL, concerns_json TEXT NOT NULL,
                kind TEXT NOT NULL)""")

    def _event(self, db, cycle_id, agent, status, summary, approve=None, concerns=None):
        event = {
            "id": uuid.uuid4().hex, "cycle_id": cycle_id, "timestamp": time.time(),
            "agent": agent, "status": status, "summary": summary[:500],
            "approve": list(approve or []), "concerns": list(concerns or []),
            "kind": "live_agent_report",
        }
        db.execute(
            "INSERT INTO fx_agent_events VALUES(?,?,?,?,?,?,?,?,?)",
            (event["id"], cycle_id, event["timestamp"], agent, status,
             event["summary"], json.dumps(event["approve"]),
             json.dumps(event["concerns"]), event["kind"]),
        )
        return event

    @staticmethod
    def _fresh(row, now=None):
        now = time.time() if now is None else now
        if not isinstance(row, dict):
            return False
        try:
            observed = float(row["observed"])
            price = float(row["price"])
            age = now - observed
            provider_day = str(row.get("provider_date", ""))[:10]
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            quote_day = time.strftime("%Y-%m-%d", time.gmtime(observed))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return False
        return (math.isfinite(observed) and math.isfinite(price) and price > 0
                and -30 <= age <= 300 and provider_day == today and quote_day == today)

    def _history(self, db, pair, row):
        observed = float(row["observed"])
        db.execute(
            "INSERT OR IGNORE INTO fx_agent_samples(pair,observed,price,provider_date,stored) VALUES(?,?,?,?,?)",
            (pair, observed, float(row["price"]), str(row.get("provider_date", ""))[:10], time.time()),
        )
        rows = db.execute(
            "SELECT observed,price FROM fx_agent_samples WHERE pair=? ORDER BY observed DESC LIMIT ?",
            (pair, MAX_HISTORY),
        ).fetchall()
        return list(reversed(rows))

    def run_cycle(self):
        """Run one complete research→strategy→risk→paper-execution→audit cycle."""
        cycle_id = uuid.uuid4().hex[:12]
        data = self.lab.tick()
        market = data.get("market", {})
        pairs = market.get("pairs", {}) if isinstance(market, dict) else {}
        account = data.get("account", {})
        now = time.time()
        events = []
        proposals = []
        with self._db() as db:
            fresh_rows = {p: q for p, q in pairs.items() if self._fresh(q, now)}
            events.append(self._event(
                db, cycle_id, "Market researcher",
                "Evidence ready" if fresh_rows else "Blocked",
                f"Observed {len(pairs)} FX rows; {len(fresh_rows)} passed timestamp, date and price freshness checks.",
                concerns=[] if fresh_rows else ["No fresh executable FX quote; no entry can be considered."],
            ))

            histories = {}
            for pair, row in fresh_rows.items():
                histories[pair] = self._history(db, pair, row)
                hist = histories[pair]
                if len(hist) < MIN_OBSERVATIONS:
                    continue
                first, last = float(hist[0][1]), float(hist[-1][1])
                momentum = last / first - 1.0 if first > 0 else 0.0
                if momentum >= MOMENTUM_THRESHOLD:
                    proposals.append({"pair": pair, "side": "buy", "momentum": momentum})
                elif momentum <= -MOMENTUM_THRESHOLD:
                    proposals.append({"pair": pair, "side": "sell", "momentum": momentum})
            events.append(self._event(
                db, cycle_id, "Strategy analyst",
                "Signal proposed" if proposals else "No trade",
                ("Proposed " + ", ".join(f"{p['side']} {p['pair']} ({p['momentum']:+.3%} observed momentum)" for p in proposals[:5])
                 if proposals else "No pair has enough distinct fresh observations with momentum beyond the conservative threshold."),
                approve=[p["pair"] for p in proposals],
            ))

            positions = account.get("positions", []) if isinstance(account, dict) else []
            held = {p.get("pair") for p in positions if isinstance(p, dict)}
            halted = bool(account.get("daily_halted")) if isinstance(account, dict) else True
            daily_pnl = account.get("daily_pnl", 0.0) if isinstance(account, dict) else 0.0
            try:
                daily_pnl = float(daily_pnl)
            except (TypeError, ValueError):
                daily_pnl = float("-inf")
            loss_limit = self.lab.broker.risk.config.max_daily_loss
            if not math.isfinite(daily_pnl) or daily_pnl <= -loss_limit:
                halted = True
            risk_approved = []
            concerns = []
            if halted:
                concerns.append("Daily-loss circuit breaker is active or the daily PnL mark is invalid.")
            for proposal in proposals:
                pair = proposal["pair"]
                if pair in held:
                    concerns.append(f"{pair}: a position already exists.")
                elif pair not in fresh_rows:
                    concerns.append(f"{pair}: quote freshness failed at risk review.")
                elif len(positions) >= self.lab.broker.risk.config.max_positions:
                    concerns.append("Maximum open-position count reached.")
                elif halted:
                    continue
                else:
                    risk_approved.append(proposal)
            events.append(self._event(
                db, cycle_id, "Risk critic",
                "Approved" if risk_approved else "Veto / abstain",
                f"Independent deterministic risk gate approved {len(risk_approved)} of {len(proposals)} proposed entries.",
                approve=[p["pair"] for p in risk_approved], concerns=concerns,
            ))

            executed = []
            chosen = risk_approved[:1]
            for proposal in chosen:
                notional = min(PAPER_NOTIONAL, self.lab.broker.risk.config.max_trade_notional)
                try:
                    result = self.lab.open(proposal["pair"], proposal["side"], notional)
                    executed.append({"pair": proposal["pair"], "side": proposal["side"],
                                     "notional": notional, "position_id": result["position"]["id"]})
                except (ValueError, KeyError, TypeError) as exc:
                    concerns.append(f"Paper broker rejected {proposal['pair']}: {str(exc)[:160]}")
            events.append(self._event(
                db, cycle_id, "Portfolio coordinator",
                "Paper order recorded" if executed else "No order",
                (f"Submitted {len(executed)} paper entry; broker risk checks remained enabled."
                 if executed else "No paper entry submitted. Abstention is a valid outcome."),
                approve=[p["pair"] for p in executed], concerns=concerns,
            ))
            latest_account = self.lab.status().get("account", {})
            events.append(self._event(
                db, cycle_id, "Performance reviewer", "Audit recorded",
                f"Cycle {cycle_id}: {len(executed)} paper entries, {len(latest_account.get('positions', []))} open positions, equity {float(latest_account.get('equity', 0)):.2f}. This is paper accounting, not evidence of profitability.",
                approve=[p["pair"] for p in executed],
                concerns=["Live broker execution is disabled.", "Observed momentum is a baseline rule, not a validated profitable strategy."],
            ))
            self.last_cycle = now
        return {"ok": True, "cycle_id": cycle_id, "timestamp": now,
                "events": events, "executed": executed, "account": self.lab.status().get("account", {}),
                "auto_run_enabled": self.auto_run}

    def status(self):
        with self._db() as db:
            rows = db.execute(
                "SELECT id,cycle_id,timestamp,agent,status,summary,approve_json,concerns_json,kind "
                "FROM fx_agent_events ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()
            samples = db.execute(
                "SELECT pair,COUNT(*),MAX(observed) FROM fx_agent_samples GROUP BY pair ORDER BY pair"
            ).fetchall()
        events = [{
            "id": r[0], "cycle_id": r[1], "timestamp": r[2], "agent": r[3],
            "status": r[4], "summary": r[5], "approve": json.loads(r[6]),
            "concerns": json.loads(r[7]), "kind": r[8],
        } for r in rows]
        return {
            "available": True, "auto_run_enabled": self.auto_run,
            "interval_seconds": self.interval, "last_cycle": self.last_cycle,
            "events": events,
            "samples": [{"pair": r[0], "observations": r[1], "latest_observed": r[2]} for r in samples],
            "policy": {"mode": "paper_only", "notional_per_entry": PAPER_NOTIONAL,
                       "min_distinct_observations": MIN_OBSERVATIONS,
                       "momentum_threshold": MOMENTUM_THRESHOLD,
                       "max_entries_per_cycle": 1},
        }
