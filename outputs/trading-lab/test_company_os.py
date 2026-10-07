import unittest
from company_os import CompanyOS, ResourceBudget

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
    def test_audit_memory(self):
        f = self.c.add_audit_finding("lookahead","high","Future data reached signal path","prefix test")
        self.assertIn(f.id,self.c.findings)
        self.assertEqual(len(self.c.memory.search("audit")),1)

if __name__ == "__main__": unittest.main()
