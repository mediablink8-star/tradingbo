import unittest
from company_os import CompanyOS, ResourceBudget, StatisticalEvaluator, CompanyScheduler

class CompanyOSTest(unittest.TestCase):
    def setUp(self):
        self.c = CompanyOS(budget=ResourceBudget(research_slots=2))
    def tearDown(self): self.c.close()
    def test_executive_cycle_is_bounded(self):
        work = self.c.executive_cycle({"data_quality_alert":True,"unresolved_audit_findings":True,"loss_review_due":True,"research_backlog_low":True})
        self.assertEqual(len(work), 4)
        self.assertEqual(self.c.company_snapshot()["execution_authority"], "deterministic_controller_only")
    def test_independent_evaluation(self):
        h = self.c.propose_hypothesis("Example","Test a measurable change","metric improves","fixed baseline","research")
        e = self.c.plan_experiment(h.id,"Example","frozen dev","frozen eval")
        r = self.c.complete_experiment(e.id,{"baseline":1.0,"challenger":1.5})
        self.assertTrue(r["supported"])
        self.assertEqual(r["evaluated_by"],"independent_evaluator")
    def test_research_budget(self):
        h = self.c.propose_hypothesis("A","A","A","baseline","research")
        self.c.plan_experiment(h.id,"one","dev","eval")
        h2 = self.c.propose_hypothesis("B","B","B","baseline","research")
        self.c.plan_experiment(h2.id,"two","dev","eval")
        h3 = self.c.propose_hypothesis("C","C","C","baseline","research")
        with self.assertRaises(RuntimeError): self.c.plan_experiment(h3.id,"three","dev","eval")
    def test_state_cycle_is_idempotent_and_throttled(self):
        state = {"strategy": {"pnl": -1.0}}
        ops = {"checklist": [{"key": "fresh", "ok": False}]}
        first = self.c.cycle_from_state(state, ops, force=True)
        second = self.c.cycle_from_state(state, ops)
        self.assertGreaterEqual(len(first["created_work"]), 1)
        self.assertEqual(second["skipped"], "cycle_throttled")
        self.assertEqual(len(self.c.work), len({w.title for w in self.c.work.values()}))

    def test_research_feedback_creates_bounded_followup(self):
        h = self.c.propose_hypothesis("H", "test statement", "metric", "baseline", "agent")
        e = self.c.plan_experiment(h.id, "E", "policy", "evaluation")
        self.c.complete_experiment(e.id, {"baseline": 1.0, "challenger": 2.0})
        created = self.c.research_feedback_loop()
        self.assertEqual(len(created), 1)
        self.assertTrue(self.c.research_feedback_loop() == [])

    def test_department_review_and_replan(self):
        self.c.create_work("Research", "research", "x", 20)
        self.c.create_work("Audit", "audit", "x", 50)
        review = self.c.department_performance_review()
        self.assertIn("research", review)
        plan = self.c.ceo_replan()
        self.assertIn("focus_departments", plan)
        self.assertIn("maintain_departments", plan)

    def test_autonomous_cycle_stays_bounded(self):
        result = self.c.autonomous_cycle(
            {"data_quality": "ok"},
            operations={"paper": "healthy"},
            context={"research_capacity": True})
        self.assertIn("priority", result)
        self.assertIn("resource_plan", result)
        self.assertEqual(result["execution_authority"], "deterministic_controller_only")

    def test_ceo_prioritizes_departments_and_budgets_research(self):
        data = self.c.create_work("Fix feed", "data", "Improve evidence quality", 60)
        research = self.c.create_work("Research next", "research", "Test a hypothesis", 50)
        self.c.create_work("Audit issue", "audit", "Verify evidence", 70)
        ranked = self.c.ceo_prioritize({"data_quality_bad": True, "open_audits": True})
        self.assertEqual(ranked[0]["work_id"], data.id)
        plan = self.c.ceo_resource_plan({"research_capacity": True})
        self.assertTrue(all(x["resource"] == "research_slot" for x in plan))
        self.assertLessEqual(len(plan), 2)

    def test_department_handoff(self):
        h = self.c.propose_hypothesis(
            "Handoff", "Test a bounded change", "metric", "baseline", "research",
            evidence=["recorded evidence"])
        review = self.c.department_gate(h.id, "sufficient", "low")
        self.assertEqual(review["decision"], "approved")
        next_stage = self.c.handoff(h.id)
        self.assertEqual(next_stage["stage"], "performance")
        self.assertEqual(self.c.work[next(w.id for w in self.c.work.values())].department, "performance")

    def test_statistical_evaluator(self):
        result = StatisticalEvaluator.compare([1.0, 2.0, 3.0], [2.0, 3.0, 5.0])
        self.assertEqual(result["n"], 3)
        self.assertAlmostEqual(result["mean_delta"], 4.0 / 3.0)
        self.assertEqual(len(result["interval"]), 2)

    def test_scheduler_throttles_and_runs(self):
        scheduler = CompanyScheduler(self.c, interval=10)
        first = scheduler.tick({"strategy": {"pnl": 0}}, {})
        second = scheduler.tick({"strategy": {"pnl": 0}}, {})
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "throttled")

    def test_audit_memory(self):
        f = self.c.add_audit_finding("lookahead","high","Future data reached signal path","prefix test")
        self.assertIn(f.id,self.c.findings)
        self.assertEqual(len(self.c.memory.search("audit")),1)

if __name__ == "__main__": unittest.main()
