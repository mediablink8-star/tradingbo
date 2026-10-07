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

class StatisticalEvaluator:
    @staticmethod
    def compare(baseline, challenger):
        if len(baseline) != len(challenger) or not baseline:
            raise ValueError("matched samples required")
        import math
        diffs = [float(b) - float(a) for a, b in zip(baseline, challenger)]
        mean = sum(diffs) / len(diffs)
        if len(diffs) == 1:
            return {"n": 1, "mean_delta": mean, "std_error": 0.0, "interval": [mean, mean]}
        variance = sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1)
        se = math.sqrt(variance / len(diffs))
        margin = 1.96 * se
        return {"n": len(diffs), "mean_delta": mean, "std_error": se,
                "interval": [mean - margin, mean + margin]}

class CompanyScheduler:
    def __init__(self, company, interval=60.0):
        self.company = company
        self.interval = max(10.0, float(interval))
        self.last_run = 0.0
        self.failures = 0

    def tick(self, state, operations=None, context=None):
        now = time.time()
        if now - self.last_run < self.interval:
            return {"status": "throttled", "next_in": self.interval - (now - self.last_run)}
        try:
            result = self.company.autonomous_cycle(state, operations, context)
            result["status"] = "ok"
            self.last_run, self.failures = now, 0
            return result
        except Exception as exc:
            self.failures += 1
            self.company.memory.put("incident", f"company-cycle-{self.failures}",
                                    {"error": str(exc), "failures": self.failures})
            return {"status": "degraded", "error": str(exc), "failures": self.failures}

class CompanyOS:
    DEPARTMENTS = ("research","risk","data","operations","performance","audit")
    def __init__(self, db_path=":memory:", budget=None):
        self.memory = CompanyMemory(db_path)
        self.budget = budget or ResourceBudget()
        self.work, self.hypotheses, self.experiments, self.findings = {}, {}, {}, {}
        self.cycle_count = 0
        self.last_cycle_at = 0.0

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

    def department_gate(self, hypothesis_id, evidence_quality="sufficient", uncertainty="medium"):
        """Independent risk/governance gate before an experiment can advance."""
        h = self.hypotheses[hypothesis_id]
        if evidence_quality not in ("insufficient", "limited", "sufficient"):
            raise ValueError("invalid evidence quality")
        if uncertainty not in ("low", "medium", "high"):
            raise ValueError("invalid uncertainty")
        if evidence_quality == "insufficient" or uncertainty == "high":
            decision = "blocked"
            h.status = "gate_blocked"
            rationale = "Insufficient evidence or excessive uncertainty."
        else:
            decision = "approved"
            h.status = "gate_approved"
            rationale = "Governance gate passed; frozen evaluation may proceed."
        d = DepartmentDecision("risk", hypothesis_id, decision, rationale)
        self.memory.put("department_decision", f"gate:{h.title}", asdict(d))
        return asdict(d)

    def handoff(self, hypothesis_id, experiment_id=None):
        """Move a research item through bounded organizational stages."""
        gate = self.department_gate(
            hypothesis_id,
            "sufficient" if self.hypotheses[hypothesis_id].evidence else "limited")
        if gate["decision"] != "approved":
            return {"stage": "risk", "gate": gate}
        if experiment_id is None:
            self.create_work(
                f"Evaluate: {self.hypotheses[hypothesis_id].title}", "performance",
                "Run the frozen evaluation and record immutable metrics.",
                85, "Performance lead")
            return {"stage": "performance", "gate": gate}
        if experiment_id not in self.experiments:
            raise KeyError("unknown experiment")
        e = self.experiments[experiment_id]
        if e.status != "completed":
            return {"stage": "performance", "gate": gate, "next": "complete_experiment"}
        self.create_work(
            f"Audit: {e.name}", "audit",
            "Verify evidence boundaries, accounting and reproducibility.",
            90, "Audit lead")
        return {"stage": "audit", "gate": gate}

    def complete_experiment(self, experiment_id, metrics):
        e = self.experiments[experiment_id]
        result = IndependentEvaluator.evaluate(e, metrics)
        self.memory.put("experiment_result", e.name, result)
        return result

    def add_audit_finding(self, category, severity, description, evidence):
        if severity not in ("info","low","medium","high","critical"): raise ValueError("invalid severity")
        f = AuditFinding(category, severity, description, evidence)
        self.findings[f.id] = f; self.memory.put("audit", category, asdict(f)); return f

    def research_feedback_loop(self):
        """Turn completed experiment outcomes into bounded future research work."""
        created = []
        for e in self.experiments.values():
            if e.status != "completed" or not e.result:
                continue
            key = f"feedback:{e.id}"
            if self.memory.search(key):
                continue
            supported = bool(e.result.get("supported"))
            title = ("Replicate: " if supported else "Challenge: ") + e.name
            objective = ("Attempt an independent replication with fresh evidence."
                         if supported else
                         "Investigate why the hypothesis failed and define a falsifiable challenger.")
            created.append(self.create_work(title, "research", objective, 55).id)
            self.memory.put("research_feedback", key, {
                "experiment_id": e.id, "supported": supported, "work_id": created[-1]})
        return created

    def department_performance_review(self):
        review = {}
        for dept in self.DEPARTMENTS:
            active = [w for w in self.work.values() if w.department == dept and w.status != "done"]
            completed = [w for w in self.work.values() if w.department == dept and w.status == "done"]
            review[dept] = {"active_work": len(active), "completed_work": len(completed),
                            "open_audits": sum(1 for f in self.findings.values() if f.status == "open" and dept == "audit"),
                            "score": min(100, len(completed) * 10 + len(active) * 3)}
        self.memory.put("department_performance", f"cycle-{self.cycle_count}", review)
        return review

    def ceo_replan(self, context=None):
        """Rebalance organizational attention from the latest performance review."""
        review = self.department_performance_review()
        ranked = sorted(review.items(), key=lambda x: x[1]["score"])
        weakest = [d for d, _ in ranked[:2]]
        strongest = [d for d, _ in ranked[-2:]]
        plan = {"focus_departments": weakest, "maintain_departments": strongest}
        self.memory.put("ceo_replan", f"cycle-{self.cycle_count}", plan)
        return plan

    def autonomous_cycle(self, state=None, operations=None, context=None):
        """Run one bounded organizational loop; never grants execution authority."""
        state = state or {}
        context = context or {}
        cycle = self.cycle_from_state(state, operations, force=True)
        feedback = self.research_feedback_loop()
        review = self.department_performance_review()
        replan = self.ceo_replan(context)
        priority = self.ceo_prioritize(context)
        resource_plan = self.ceo_resource_plan(context)
        self.memory.put("autonomous_cycle", f"cycle-{self.cycle_count}", {
            "cycle": self.cycle_count,
            "priority": priority[:5],
            "resource_plan": resource_plan,
            "execution_authority": "deterministic_controller_only",
        })
        return {
            "cycle": cycle,
            "priority": priority,
            "resource_plan": resource_plan,
            "execution_authority": "deterministic_controller_only",
        }

    def ceo_prioritize(self, context=None):
        """Score bounded company work from history and current evidence."""
        context = context or {}
        scores = {}
        for w in self.work.values():
            if w.status == "done":
                continue
            score = float(w.priority)
            if w.department == "risk" and context.get("uncertainty_high"):
                score += 15
            if w.department == "data" and context.get("data_quality_bad"):
                score += 20
            if w.department == "audit" and context.get("open_audits"):
                score += 20
            if w.department == "performance" and context.get("evaluation_due"):
                score += 15
            if w.department == "research" and context.get("research_capacity"):
                score += 5
            scores[w.id] = min(100.0, score)
        ranked = sorted(
            ((scores[i], self.work[i]) for i in scores),
            key=lambda pair: (-pair[0], pair[1].created_at))
        ranked = [{"work_id": w.id, "department": w.department,
                   "title": w.title, "score": score} for score, w in ranked]
        self.memory.put("ceo_priority_review", f"priority-cycle-{self.cycle_count}", {
            "context": context, "ranked_work": ranked[:10]})
        return ranked[:10]

    def ceo_resource_plan(self, context=None):
        """Allocate only bounded research resources; never trading capital."""
        ranked = self.ceo_prioritize(context)
        plan = []
        slots = self.budget.research_slots
        for item in ranked:
            if slots <= 0:
                break
            if item["department"] in ("research", "performance"):
                plan.append({"work_id": item["work_id"], "resource": "research_slot"})
                slots -= 1
        self.memory.put("ceo_resource_plan", f"resource-cycle-{self.cycle_count}", plan)
        return plan

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

    def cycle_from_state(self, state, operations=None, force=False, min_interval=60.0):
        """Translate observed system health into bounded executive signals."""
        now = time.time()
        if not force and now - self.last_cycle_at < min_interval:
            return {"signals": {}, "created_work": [], "skipped": "cycle_throttled"}
        self.last_cycle_at = now
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
