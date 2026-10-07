import os, tempfile, unittest
from shadow_execution import ShadowLedger

class ShadowLedgerTests(unittest.TestCase):
    def setUp(self):
        self.fd,self.path=tempfile.mkstemp()
        os.close(self.fd)
        self.ledger=ShadowLedger(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_reserve_and_fill(self):
        intent=self.ledger.reserve("TOKEN","buy",10,{"agents":["a","b"]})
        self.assertEqual(intent["status"],"reserved")
        filled=self.ledger.fill(intent["id"],1000,0.01,{"base_units":1000},__import__("time").time())
        self.assertEqual(filled["status"],"filled")
        self.assertEqual(len(self.ledger.status()["positions"]),1)

    def test_daily_limit(self):
        self.ledger.reserve("A","buy",10,{})
        self.ledger.reserve("B","buy",10,{})
        self.ledger.reserve("C","buy",5,{})
        with self.assertRaises(ValueError):
            self.ledger.reserve("D","buy",1,{})

    def test_position_limit(self):
        for token in ("A","B","C"):
            self.ledger.reserve(token,"buy",5,{})
        with self.assertRaises(ValueError):
            self.ledger.reserve("D","buy",5,{})

    def test_reconciliation_flags_unexpected_balance(self):
        intent=self.ledger.reserve("TOKEN","buy",5,{})
        self.ledger.fill(intent["id"],100,0.05,{"base_units":100})
        result=self.ledger.reconcile({"TOKEN":100,"SURPRISE":10},{"TOKEN":0.05})
        self.assertFalse(result["ok"])
        self.assertTrue(any(x["kind"]=="unexpected_balance" for x in result["findings"]))

if __name__=="__main__":
    unittest.main()
