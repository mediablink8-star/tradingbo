"""Bounded autonomous virtual-company operating system for Ember.

This module adds organizational autonomy without giving LLMs trading authority.
It has no wallet, broker, exchange, signer, or risk-controller override API.
"""
from __future__ import annotations
import json, sqlite3, time, uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

@dataclass
class ResourceBudget:
    inference_credits: float = 10.0
    research_slots: int = 3
    observation_budget: int = 1000
    def reserve(self, inference=0.0, research_slots=0, observations=0):
        if min(inference, research_slots, observations) < 0:
            raise ValueError("resource requests cannot be negative")
        if inference > self.inference_credits or research_slots > self.research_slots or observations > self.observation_budget:
            return False
        self.inference_credits -= inference
        self.research_slots -= research_slots
        self.observation_budget -= observations
        return True

@dataclass
class WorkOrder:
    title: str
    department: str
    objective: str
    priority: int = 50
    owner: str = "CEO"
    status: str = "queued"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

@dataclass
class Hypothesis:
    title: str
    statement: str
    success_metric: str
    baseline: str
    proposed_by: str
    evidence: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "proposed"

@dataclass
class Experiment:
    hypothesis_id: str
    name: str
    development_policy: str
    evaluation_policy: str
    embargo: str = "lookback + max holding + latency"
    status: str = "planned"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    result: Optional[dict[str, Any]] = None

@dataclass
class AuditFinding:
    category: str
    severity: str
    description: str
    evidence: str
    status: str = "open"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

class CompanyMemory:
    def __init__(self, db_path=":memory:"):
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS company_memory(
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
            payload TEXT NOT NULL, created_at REAL NOT NULL)""")
        self.db.commit()
    def put(self, kind, title, payload):
        i = uuid.uuid4().hex[:12]
        self.db.execute("INSERT INTO company_memory VALUES(?,?,?,?,?)",
                        (i, kind, title, json.dumps(payload, sort_keys=True), time.time()))
        self.db.commit()
        return i
    def search(self, kind=None, limit=20):
        if not 1 <= limit <= 500: raise ValueError("limit must be 1..500")
        q = ("SELECT id,kind,title,payload,created_at FROM company_memory "
             + ("WHERE kind=? " if kind else "")
             + "ORDER BY created_at DESC LIMIT ?")
        rows = self.db.execute(q, ((kind, limit) if kind else (limit,))).fetchall()
        return [{"id":r[0],"kind":r[1],"title":r[2],"payload":json.loads(r[3]),"created_at":r[4]} for r in rows]
    def close(self): self.db.close()

class IndependentEvaluator:
    @staticmethod
    def evaluate(experiment, metrics):
        if not {"baseline","challenger"} <= set(metrics):
            raise ValueError("evaluation requires baseline and challenger metrics")
        delta = float(metrics["challenger"]) - float(metrics["baseline"])
        result = {"baseline":float(metrics["baseline"]), "challenger":float(metrics["challenger"]),
                  "delta":delta, "supported":delta > 0,
                  "decision":"supported" if delta > 0 else "not_supported",
                  "evaluated_by":"independent_evaluator"}
        experiment.result, experiment.status = result, "completed"
        return result

class CompanyOS:
    DEPARTMENTS = ("research","risk","data","operations","performance","audit")
    def __init__(self, db_path=":memory:", budget=None):
        self.memory = CompanyMemory(db_path)
        self.budget = budget or ResourceBudget()
        self.work, self.hypotheses, self.experiments, self.findings = {}, {}, {}, {}
        self.cycle_count = 0

    def create_work(self, title, department, objective, priority=50, owner="CEO"):
        if department not in self.DEPARTMENTS: raise ValueError("unknown department")
        if not 0 <= priority <= 100: raise ValueError("priority must be 0..100")
        for existing in self.work.values():
            if existing.status != "done" and existing.title == title:
                return existing
        w = WorkOrder(title, department, objective, priority, owner)
        self.work[w.id] = w; self.memory.put("work_order", title, asdict(w)); return w

    def propose_hypothesis(self, title, statement, success_metric, baseline, proposed_by, evidence=None):
        h = Hypothesis(title, statement, success_metric, baseline, proposed_by, list(evidence or []))
        self.hypotheses[h.id] = h; self.memory.put("hypothesis", title, asdict(h)); return h

    def plan_experiment(self, hypothesis_id, name, development_policy, evaluation_policy, embargo="lookback + max holding + latency"):
        if hypothesis_id not in self.hypotheses: raise KeyError("unknown hypothesis")
        if not self.budget.reserve(research_slots=1): raise RuntimeError("no research slot available")
        e = Experiment(hypothesis_id, name, development_policy, evaluation_policy, embargo)
        self.experiments[e.id] = e
        self.hypotheses[hypothesis_id].status = "scheduled"
        self.memory.put("experiment", name, asdict(e)); return e

    def complete_experiment(self, experiment_id, metrics):
        e = self.experiments[experiment_id]
        result = IndependentEvaluator.evaluate(e, metrics)
        self.memory.put("experiment_result", e.name, result)
        return result

    def add_audit_finding(self, category, severity, description, evidence):
        if severity not in ("info","low","medium","high","critical"): raise ValueError("invalid severity")
        f = AuditFinding(category, severity, description, evidence)
        self.findings[f.id] = f; self.memory.put("audit", category, asdict(f)); return f

    def executive_cycle(self, signals):
        self.cycle_count += 1; created = []
        if signals.get("data_quality_alert"):
            created.append(self.create_work("Investigate data-quality alert","data",
                "Identify missing, stale or contradictory observations.",90,"Data lead"))
        if signals.get("unresolved_audit_findings"):
            created.append(self.create_work("Resolve open audit findings","audit",
                "Reproduce and close the highest-severity evidence-quality findings.",95,"Audit lead"))
        if signals.get("loss_review_due"):
            created.append(self.create_work("Review recorded outcomes","performance",
                "Attribute outcomes from immutable accounting records and propose a testable hypothesis.",80,"Performance lead"))
        if signals.get("research_backlog_low") and self.budget.research_slots:
            created.append(self.create_work("Generate next research question","research",
                "Search company memory and formulate one preregistered experiment.",60,"Research lead"))
        self.memory.put("executive_cycle", f"cycle-{self.cycle_count}",
                         {"signals":signals,"created_work":[w.id for w in created]})
        return created

    def company_snapshot(self):
        return {"cycle":self.cycle_count, "budget":asdict(self.budget),
                "work":[asdict(w) for w in sorted(self.work.values(), key=lambda x:(-x.priority,x.created_at))],
                "experiments":[asdict(e) for e in self.experiments.values()],
                "open_audits":[asdict(f) for f in self.findings.values() if f.status=="open"],
                "memory_items":len(self.memory.search(limit=500)),
                "execution_authority":"deterministic_controller_only"}

    def cycle_from_state(self, state, operations=None):
        """Translate observed system health into bounded executive signals."""
        operations = operations or {}
        checklist = operations.get("checklist", [])
        failed = {item.get("key") for item in checklist if not item.get("ok")}
        strategy = state.get("strategy", {})
        pnl = strategy.get("pnl")
        signals = {
            "data_quality_alert": bool({"fresh", "feed", "pricing"} & failed),
            "unresolved_audit_findings": any(f.status == "open" for f in self.findings.values()),
            "loss_review_due": isinstance(pnl, (int, float)) and pnl < 0,
            "research_backlog_low": not any(w.department == "research" and w.status != "done" for w in self.work.values()),
        }
        created = self.executive_cycle(signals)
        return {"signals": signals, "created_work": [asdict(w) for w in created]}

    def close(self): self.memory.close()
