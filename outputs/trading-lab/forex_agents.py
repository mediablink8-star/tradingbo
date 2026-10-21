"""Transparent, bounded multi-stage FX paper-agent pipeline.

No LLM or broker credentials are used. The research and strategy agents only
consume observed quotes; deterministic risk controls remain the final authority.
"""
import json
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

MAX_HISTORY = 5
MIN_OBSERVATIONS = 3
MOMENTUM_THRESHOLD = 0.0003
PAPER_NOTIONAL = 250.0

# Deterministic pipeline stages that an operator may enable or disable.
# "risk" is deliberately absent from the toggleable set: the Risk critic is
# the safety interlock and stays on. "macro" has no deterministic execution
# path (it exists only as an AI advisory stage), so there is nothing to gate.
AGENT_KEYS = ("market", "macro", "strategy", "risk", "portfolio")
TOGGLEABLE_AGENTS = ("market", "strategy", "portfolio")


class ForexAgentRuntime:
    def __init__(self, path, lab, auto_run=False, interval=60.0):
        self.path = str(path)
        self.lab = lab
        self.auto_run = bool(auto_run)
        self.interval = max(15.0, float(interval))
        self.last_cycle = 0.0
        # The web button and background scheduler can fire at the same time.
        # A single-flight guard prevents overlapping cycles from duplicating entries.
        self._cycle_lock = threading.Lock()
        self._init_db()

    def _db(self):
        return sqlite3.connect(self.path, timeout=15)

    @contextmanager
    def _transaction(self):
        """Context manager that commits/rolls back and closes the SQLite connection.

        Unlike the raw Connection context manager (which only commits/rolls back),
        this ensures the connection is closed, preventing file locks on Windows.
        """
        conn = self._db()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fx_agent_samples(
                pair TEXT NOT NULL, observed REAL NOT NULL, price REAL NOT NULL,
                provider_date TEXT NOT NULL, stored REAL NOT NULL,
                PRIMARY KEY(pair, observed))""")
            db.execute("""CREATE TABLE IF NOT EXISTS fx_agent_events(
                id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, timestamp REAL NOT NULL,
                agent TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                approve_json TEXT NOT NULL, concerns_json TEXT NOT NULL,
                kind TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS fx_agent_config(
                agent_key TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
                updated REAL NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS fx_agent_cycle_audits(
                cycle_id TEXT PRIMARY KEY, timestamp REAL NOT NULL,
                quote_snapshot_json TEXT NOT NULL,
                deliberation_json TEXT NOT NULL,
                risk_gate_json TEXT NOT NULL,
                paper_json TEXT NOT NULL,
                account_json TEXT NOT NULL)""")

    def get_config(self):
        """Per-agent enable flags. Missing rows default to enabled."""
        with self._transaction() as db:
            rows = db.execute(
                "SELECT agent_key,enabled FROM fx_agent_config"
            ).fetchall()
        config = {key: True for key in AGENT_KEYS}
        for key, enabled in rows:
            if key in config:
                config[key] = bool(enabled)
        config["risk"] = True
        return config

    def set_config(self, agent_key, enabled):
        """Persist one agent's enable flag. Returns the full config.

        The Risk critic is the safety interlock and cannot be disabled.
        The Macro analyst has no deterministic execution path, so toggling
        it would be a dead switch and is rejected with an explanation.
        """
        key = str(agent_key or "").strip().lower()
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() not in ("", "0", "false", "no", "off")
        if key not in AGENT_KEYS:
            raise ValueError(
                "Unknown agent '%s'. Expected one of: %s."
                % (agent_key, ", ".join(AGENT_KEYS)))
        if key == "risk":
            raise ValueError(
                "Risk critic is the safety interlock and stays enabled.")
        if key == "macro":
            raise ValueError(
                "Macro analyst has no deterministic execution path; "
                "it reports through AI advisory only, so there is nothing "
                "to disable.")
        with self._transaction() as db:
            db.execute(
                "INSERT INTO fx_agent_config(agent_key,enabled,updated)"
                " VALUES(?,?,?) ON CONFLICT(agent_key) DO UPDATE SET"
                " enabled=excluded.enabled, updated=excluded.updated",
                (key, 1 if enabled else 0, time.time()),
            )
        return self.get_config()

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
        """Run at most one paper action cycle at a time.

        A manual dashboard action can coincide with the automatic scheduler.
        The second caller abstains instead of racing through the same signal
        and potentially submitting a duplicate paper entry.
        """
        if not self._cycle_lock.acquire(blocking=False):
            return {
                "ok": True,
                "skipped": True,
                "reason": "cycle_in_progress",
                "executed": [],
                "auto_run_enabled": self.auto_run,
            }
        try:
            return self._run_cycle_locked()
        finally:
            self._cycle_lock.release()

    def _run_cycle_locked(self):
        """Run one complete research→strategy→risk→paper-execution→audit cycle."""
        cycle_id = uuid.uuid4().hex[:12]
        data = self.lab.tick()
        market = data.get("market", {})
        pairs = market.get("pairs", {}) if isinstance(market, dict) else {}
        account = data.get("account", {})
        now = time.time()
        events = []
        proposals = []
        cfg = self.get_config()
        with self._transaction() as db:
            if not cfg["market"]:
                fresh_rows = {}
                events.append(self._event(
                    db, cycle_id, "Market researcher",
                    "Skipped (disabled by operator)",
                    "Market researcher is disabled, so no quotes were sampled this cycle. "
                    "Enable the station to resume observation.",
                    concerns=["Station disabled by operator."],
                ))
            else:
                fresh_rows = {p: q for p, q in pairs.items() if self._fresh(q, now)}
                events.append(self._event(
                    db, cycle_id, "Market researcher",
                    "Evidence ready" if fresh_rows else "Blocked",
                    f"Observed {len(pairs)} instrument rows; {len(fresh_rows)} passed timestamp, date and price freshness checks.",
                    concerns=[] if fresh_rows else ["No fresh executable quote; no entry can be considered."],
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
            if not cfg["strategy"]:
                proposals = []
                events.append(self._event(
                    db, cycle_id, "Strategy analyst",
                    "Skipped (disabled by operator)",
                    "Strategy analyst is disabled, so no signals were evaluated this cycle. "
                    "Observations already recorded are kept for future cycles.",
                    concerns=["Station disabled by operator."],
                ))
            else:
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
            chosen = [] if not cfg["portfolio"] else risk_approved[:1]
            if not cfg["portfolio"] and risk_approved:
                concerns.append(
                    "Portfolio coordinator is disabled by operator; "
                    "approved entries were not submitted.")
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
                "Paper order recorded" if executed
                else ("Skipped (disabled by operator)" if not cfg["portfolio"] else "No order"),
                (f"Submitted {len(executed)} paper entry; broker risk checks remained enabled."
                 if executed
                 else ("Portfolio coordinator is disabled; approved entries were held, not submitted."
                       if not cfg["portfolio"]
                       else "No paper entry submitted. Abstention is a valid outcome.")),
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
                "events": events, "executed": executed,
                "account": self.lab.status().get("account", {}),
                "auto_run_enabled": self.auto_run,
                "ai_research": getattr(self, "research", None)}

    def attach_research(self, layer):
        """Attach the advisory AI research layer.

        The layer can only add recorded commentary. It cannot add proposals,
        approve an entry, resize one, or touch a risk limit; those decisions
        stay with the deterministic stages above.
        """
        self.research = layer

    def run_research(self):
        """Run advisory AI research for the current observed state."""
        layer = getattr(self, "research", None)
        if layer is None:
            return None
        data = self.lab.tick()
        result = layer.run(
            data.get("market", {}), data.get("account", {}),
            data.get("risk", {}), self.histories(),
            data.get("account", {}).get("positions", []),
        )
        cycle_id = uuid.uuid4().hex[:12]
        now = time.time()
        with self._transaction() as db:
            for stage in result.get("stages", []):
                status = "AI report" if stage.get("ok") else "AI unavailable"
                summary = (stage.get("text") or
                           "; ".join(stage.get("concerns") or []) or "No output.")[:2000]
                db.execute(
                    "INSERT OR REPLACE INTO fx_agent_events"
                    "(id,cycle_id,timestamp,agent,status,summary,approve_json,"
                    "concerns_json,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, cycle_id, now,
                     stage["agent"] + " (AI)", status, summary, "[]",
                     json.dumps(stage.get("concerns") or [])[:4000],
                     "ai_research_report"),
                )
        return result

    def histories(self):
        """Recent observed closes per pair, for AI context."""
        out = {}
        with self._transaction() as db:
            rows = db.execute(
                "SELECT pair,observed,price FROM fx_agent_samples"
                " ORDER BY observed ASC"
            ).fetchall()
        for pair, observed, price in rows:
            out.setdefault(pair, []).append((observed, price))
        return {p: v[-MAX_HISTORY:] for p, v in out.items()}

    def status(self):
        with self._transaction() as db:
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
            "agent_config": self.get_config(),
            "events": events,
            "samples": [{"pair": r[0], "observations": r[1], "latest_observed": r[2]} for r in samples],
            "policy": {"mode": "paper_only", "notional_per_entry": PAPER_NOTIONAL,
                       "min_distinct_observations": MIN_OBSERVATIONS,
                       "momentum_threshold": MOMENTUM_THRESHOLD,
                       "max_entries_per_cycle": 1},
            "execution_enabled": False,
            "ai_budget": self._ai_cycle_budget().get("budget"),
        }

    def get_cycle_audit(self, cycle_id):
        key = str(cycle_id or "").strip()[:80]
        if not key:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT cycle_id,timestamp,quote_snapshot_json,deliberation_json,"
                "risk_gate_json,paper_json,account_json FROM fx_agent_cycle_audits "
                "WHERE cycle_id=?", (key,),
            ).fetchone()
        if not row:
            return None
        return {
            "cycle_id": row[0], "timestamp": row[1],
            "quote_snapshot": json.loads(row[2]),
            "deliberation": json.loads(row[3]),
            "risk_gate": json.loads(row[4]),
            "paper": json.loads(row[5]), "account": json.loads(row[6]),
            "execution_enabled": False,
        }

    def run_deliberation(self, apply_paper: bool = False, requested_pair=None):
        """Run the six-agent committee and save its proposal without execution.

        Paper orders require approve_paper_cycle() with the saved cycle ID.
        In autonomous mode every specialist must respond, and the risk critic
        must not veto the recommendation. The model budget is reserved before
        the committee starts so it cannot stop halfway through its six calls.
        """
        if apply_paper:
            return {"ok": False, "reason": "AI proposals cannot execute directly; explicitly approve the saved plan.",
                    "paper": {"action": "hold", "executed": []}, "execution_enabled": False}
        if not self._cycle_lock.acquire(blocking=False):
            return {
                "ok": True, "skipped": True, "reason": "cycle_in_progress",
                "paper": {"action": "hold", "executed": []},
                "execution_enabled": False,
            }
        try:
            return self._run_deliberation_locked(apply_paper=apply_paper, requested_pair=requested_pair)
        finally:
            self._cycle_lock.release()

    def _ai_cycle_budget(self):
        layer = getattr(self, "research", None)
        store = getattr(layer, "store", None)
        remaining = getattr(store, "budget_remaining", None)
        if not callable(remaining):
            return {"ready": False, "reason": "AI model budget is unavailable."}
        budget = remaining()
        calls_left = int(budget.get("calls_left", 0))
        cost_per_call = float(budget.get("cost_per_call_usd", 0.0))
        spend_left = float(budget.get("spend_left_usd", 0.0))
        if calls_left < 6:
            return {"ready": False, "reason": "Six model calls are required; fewer than six remain today.", "budget": budget}
        if spend_left + 1e-12 < 6 * cost_per_call:
            return {"ready": False, "reason": "The remaining model-spend allowance cannot cover a six-agent cycle.", "budget": budget}
        return {"ready": True, "budget": budget}

    def run_ai_cycle(self):
        """Run a six-agent proposal cycle; paper execution requires approval."""
        return self.run_ai_proposal()

    def run_ai_proposal(self, pair=None):
        """Create an approval-gated AI plan without opening a paper position."""
        layer = getattr(self, "research", None)
        if layer is None or not callable(getattr(layer, "available", None)) or not layer.available():
            return {"ok": False, "reason": "Connect and verify an AI model before running an AI paper cycle.",
                    "paper": {"action": "hold", "executed": []}, "execution_enabled": False}
        if pair:
            from instrument_catalog import get_instrument
            try:
                pair = get_instrument(pair).symbol
            except ValueError as exc:
                return {"ok": False, "reason": str(exc), "paper": {"action": "hold", "executed": []},
                        "execution_enabled": False}
        budget = self._ai_cycle_budget()
        if not budget["ready"]:
            return {"ok": False, "reason": budget["reason"], "budget": budget.get("budget"),
                    "paper": {"action": "hold", "executed": []}, "execution_enabled": False}
        return self.run_deliberation(requested_pair=pair)

    def approve_paper_cycle(self, cycle_id):
        """Submit the exact saved proposal to the paper broker after explicit approval."""
        from instrument_catalog import SUPPORTED_SYMBOLS
        from multi_agent import apply_decision_to_paper

        if not self._cycle_lock.acquire(blocking=False):
            return {"ok": False, "reason": "Another Forex analysis or approval is in progress.",
                    "execution_enabled": False}
        try:
            key = str(cycle_id or "").strip()[:80]
            audit = self.get_cycle_audit(key)
            if not audit:
                return {"ok": False, "reason": "The Forex plan was not found.", "execution_enabled": False}
            gate = audit.get("risk_gate") or {}
            deliberation = audit.get("deliberation") or {}
            final = deliberation.get("final_decision") or {}
            pair = str(final.get("pair_or_token") or "").strip().upper()
            side = str(final.get("side") or "hold").strip().lower()
            if gate.get("proposal_state") != "awaiting_operator" or not gate.get("proposal_eligible"):
                paper = audit.get("paper") or {}
                if paper.get("executed"):
                    return {"ok": True, "already_approved": True, "cycle_id": key,
                            "paper": paper, "account": audit.get("account"), "execution_enabled": False}
                return {"ok": False, "cycle_id": key,
                        "reason": "; ".join(gate.get("blockers") or []) or "This plan is not eligible for paper approval.",
                        "execution_enabled": False}
            if pair not in SUPPORTED_SYMBOLS or side not in ("buy", "sell"):
                return {"ok": False, "cycle_id": key, "reason": "Unsupported or incomplete Forex plan.",
                        "execution_enabled": False}

            # Claim the proposal durably before touching the paper broker. If the
            # process stops mid-approval, a retry cannot create a duplicate entry.
            with self._transaction() as db:
                row = db.execute(
                    "SELECT risk_gate_json,paper_json FROM fx_agent_cycle_audits WHERE cycle_id=?", (key,)
                ).fetchone()
                if not row:
                    return {"ok": False, "reason": "The Forex plan was not found.", "execution_enabled": False}
                current_gate, current_paper = json.loads(row[0]), json.loads(row[1])
                if current_gate.get("proposal_state") != "awaiting_operator":
                    return {"ok": False, "cycle_id": key,
                            "reason": "This plan has already been actioned or is being processed.",
                            "paper": current_paper, "execution_enabled": False}
                current_gate["proposal_state"] = "approval_pending"
                db.execute(
                    "UPDATE fx_agent_cycle_audits SET risk_gate_json=?,paper_json=? WHERE cycle_id=?",
                    (json.dumps(current_gate), json.dumps({"action": "approval_pending", "executed": []}), key),
                )

            quote_snapshot = audit.get("quote_snapshot") or {}
            planned_quote = quote_snapshot.get(pair) or {}
            planned_entry = planned_quote.get("ask" if side == "buy" else "bid")
            try:
                planned_entry = float(planned_entry)
                current = self.lab.tick()
                row = (current.get("market") or {}).get("pairs", {}).get(pair) or {}
                current_entry = float(row.get("ask" if side == "buy" else "bid"))
                observed = float(row.get("observed"))
                provider_date = str(row.get("provider_date") or "")
                age = time.time() - observed
                if not math.isfinite(current_entry) or current_entry <= 0:
                    raise ValueError("Current Forex quote is invalid.")
                if age < -30 or age > 300 or not self.lab._provider_date_is_today(provider_date):
                    raise ValueError("Current quote is stale or not dated today; refresh the plan before approving.")
                drift_bps = abs(current_entry / planned_entry - 1.0) * 10000.0
                if not math.isfinite(drift_bps) or drift_bps > 10.0:
                    raise ValueError("Price moved more than 10 bps from the reviewed plan; create a new plan.")
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
                paper = {"action": "rejected", "executed": [], "reason": str(exc)[:300]}
                self._finish_paper_approval(key, paper, gate_state="rejected", account=self.lab.status().get("account", {}))
                return {"ok": False, "cycle_id": key, "reason": paper["reason"], "paper": paper,
                        "execution_enabled": False}

            try:
                paper = apply_decision_to_paper(
                    final,
                    lab_open=self.lab.open,
                    lab_close=self.lab.close,
                    account=self.lab.status().get("account", {}),
                    max_notional=PAPER_NOTIONAL,
                )
            except Exception as exc:
                paper = {"action": "rejected", "executed": [], "reason": str(exc)[:300]}
            account = self.lab.status().get("account", {})
            approved = bool(paper.get("executed"))
            self._finish_paper_approval(key, paper,
                                        gate_state="approved" if approved else "rejected",
                                        account=account)
            return {"ok": approved, "cycle_id": key, "paper": paper, "account": account,
                    "execution_enabled": False}
        finally:
            self._cycle_lock.release()

    def _finish_paper_approval(self, cycle_id, paper, *, gate_state, account):
        with self._transaction() as db:
            row = db.execute("SELECT risk_gate_json FROM fx_agent_cycle_audits WHERE cycle_id=?",
                             (cycle_id,)).fetchone()
            if not row:
                return
            gate = json.loads(row[0])
            gate["proposal_state"] = gate_state
            gate["paper_action"] = paper.get("action", "rejected")
            gate["entry_allowed"] = bool(paper.get("executed"))
            db.execute("UPDATE fx_agent_cycle_audits SET risk_gate_json=?,paper_json=?,account_json=? WHERE cycle_id=?",
                       (json.dumps(gate), json.dumps(paper, default=str),
                        json.dumps(account, default=str), cycle_id))
            self._event(db, cycle_id, "Operator-approved paper gate",
                        "APPROVED" if paper.get("executed") else "REJECTED",
                        paper.get("reason", "Paper entry passed deterministic risk checks.")[:500],
                        approve=[item.get("pair") for item in paper.get("executed", []) if item.get("pair")],
                        concerns=[] if paper.get("executed") else [paper.get("reason", "No paper entry created.")])

    def _run_deliberation_locked(self, apply_paper=True, requested_pair=None):
        from multi_agent import MultiAgentEngine, apply_decision_to_paper
        from instrument_catalog import SUPPORTED_SYMBOLS

        layer = getattr(self, "research", None)
        engine = MultiAgentEngine(layer, max_rounds=1)
        data = self.lab.tick()
        market = data.get("market", {})
        if requested_pair:
            pairs = market.get("pairs") or {}
            market["pairs"] = {requested_pair: pairs[requested_pair]} if requested_pair in pairs else {}
        account = data.get("account", {})
        risk = data.get("risk", {})
        positions = account.get("positions", []) if isinstance(account, dict) else []
        history = self.histories()

        deliberation = engine.deliberate(
            market, account, risk, history, positions
        )

        cycle_id = deliberation.get("cycle_id") or uuid.uuid4().hex[:12]
        now = time.time()
        events = []

        with self._transaction() as db:
            for agent_rec in deliberation.get("agents", []):
                report = agent_rec.get("report") or {}
                status = "Deliberation" if agent_rec.get("ok") else "Unavailable"
                parts = []
                for k, v in report.items():
                    if k == "concerns":
                        continue
                    if isinstance(v, list):
                        parts.append(f"{k}: " + "; ".join(str(x) for x in v[:3]))
                    else:
                        parts.append(f"{k}: {v}")
                summary = " | ".join(parts)[:500] or agent_rec.get("error", "No output")
                concerns = report.get("concerns") or report.get("veto_reasons") or []
                if agent_rec.get("error"):
                    concerns = list(concerns) + [agent_rec["error"]]
                events.append(self._event(
                    db, cycle_id, agent_rec.get("agent", "Agent"),
                    status, summary,
                    approve=[], concerns=concerns[:8],
                ))

            final = deliberation.get("final_decision") or {}
            events.append(self._event(
                db, cycle_id, "Portfolio Coordinator (final)",
                final.get("decision", "hold").upper(),
                (final.get("rationale") or "No rationale")[:500],
                approve=[final.get("pair_or_token")] if final.get("pair_or_token") else [],
                concerns=final.get("concerns") or [],
            ))

        expected_agents = {"market", "technical", "macro", "strategy", "risk", "coordinator"}
        agents_by_key = {a.get("key"): a for a in deliberation.get("agents", [])}
        blockers = []
        missing = sorted(expected_agents - set(agents_by_key))
        if missing:
            blockers.append("Missing committee response: " + ", ".join(missing))
        failed = sorted(k for k in expected_agents if k in agents_by_key and not agents_by_key[k].get("ok"))
        if failed:
            blockers.append("Committee response failed: " + ", ".join(failed))
        risk_report = (agents_by_key.get("risk", {}).get("report") or {})
        vetoes = risk_report.get("veto_reasons") or []
        if vetoes:
            blockers.append("Risk critic veto: " + "; ".join(str(x)[:120] for x in vetoes[:3]))
        final = deliberation.get("final_decision") or {}
        pair = str(final.get("pair_or_token") or "").strip().upper()
        if pair and pair not in SUPPORTED_SYMBOLS:
            blockers.append("Coordinator selected an unsupported instrument.")
        if requested_pair and pair != requested_pair:
            blockers.append("Coordinator did not follow the selected Forex pair.")
        side = str(final.get("side") or "hold").lower()
        if side not in ("buy", "sell"):
            blockers.append("Coordinator did not propose a buy or sell entry.")
        if pair:
            final["pair_or_token"] = pair

        paper_result = {"action": "hold", "executed": [], "reason": "apply_paper=False"}
        if apply_paper and not blockers and deliberation.get("ok"):
            paper_result = apply_decision_to_paper(
                final,
                lab_open=self.lab.open,
                lab_close=self.lab.close,
                account=self.lab.status().get("account", {}),
                max_notional=PAPER_NOTIONAL,
            )
            with self._transaction() as db:
                events.append(self._event(
                    db, cycle_id, "Paper execution gate",
                    paper_result.get("action", "hold").upper(),
                    paper_result.get("reason", "Deterministic risk gate evaluated the recommendation.")[:500],
                    approve=[paper_result.get("pair")] if paper_result.get("pair") else [],
                    concerns=[] if paper_result.get("executed") else [
                        paper_result.get("reason") or "No paper order submitted."
                    ],
                ))
        elif apply_paper:
            reason = "; ".join(blockers) if blockers else "The complete six-agent committee did not approve an action."
            paper_result = {"action": "hold", "executed": [], "reason": reason}
            with self._transaction() as db:
                events.append(self._event(
                    db, cycle_id, "AI paper execution gate", "Veto / abstain",
                    reason[:500], approve=[], concerns=blockers or [reason],
                ))

        self.last_cycle = now
        account_after = self.lab.status().get("account", {})
        quote_snapshot = {}
        for symbol, row in (market.get("pairs") or {}).items():
            symbol = str(symbol).strip().upper()
            if symbol not in SUPPORTED_SYMBOLS or not isinstance(row, dict):
                continue
            quote = {"symbol": symbol, "source": str(row.get("source") or "unknown")[:120],
                     "provider_date": str(row.get("provider_date") or "")[:40],
                     "instrument": "fx", "executable": False}
            for key in ("price", "bid", "ask", "observed"):
                try:
                    number = float(row[key])
                    quote[key] = number if math.isfinite(number) else None
                except (KeyError, TypeError, ValueError, OverflowError):
                    quote[key] = None
            quote_snapshot[symbol] = quote
        risk_gate = {
            "committee_complete": not blockers,
            "risk_vetoes": vetoes,
            "blockers": blockers,
            "proposal_eligible": bool(not blockers and deliberation.get("ok") and pair in SUPPORTED_SYMBOLS and side in ("buy", "sell")),
            "proposal_state": "awaiting_operator" if not blockers and deliberation.get("ok") and pair in SUPPORTED_SYMBOLS and side in ("buy", "sell") else "blocked",
            "paper_action": paper_result.get("action", "hold"),
            "entry_allowed": bool(paper_result.get("executed")),
            "live_execution_enabled": False,
        }
        with self._transaction() as db:
            db.execute(
                "INSERT INTO fx_agent_cycle_audits VALUES(?,?,?,?,?,?,?)",
                (cycle_id, now, json.dumps(quote_snapshot),
                 json.dumps(deliberation, default=str), json.dumps(risk_gate),
                 json.dumps(paper_result, default=str), json.dumps(account_after, default=str)),
            )
        return {
            "ok": True,
            "cycle_id": cycle_id,
            "timestamp": now,
            "deliberation": deliberation,
            "quote_snapshot": quote_snapshot,
            "paper": paper_result,
            "proposal": {"eligible": bool(risk_gate["proposal_eligible"]), "state": risk_gate["proposal_state"],
                         "pair": pair, "side": side, "blockers": blockers},
            "ai_gate": {"entry_allowed": bool(paper_result.get("executed")), "blockers": blockers},
            "budget": self._ai_cycle_budget().get("budget"),
            "events": events,
            "account": account_after,
            "auto_run_enabled": self.auto_run,
            "mode": "six_agent_deliberation",
            "execution_enabled": False,
        }
