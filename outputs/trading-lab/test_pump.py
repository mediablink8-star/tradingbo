import unittest, tempfile, json
from pathlib import Path
from pump_feed import normalize, PumpStore

MINT='So11111111111111111111111111111111111111112'

class PumpTests(unittest.TestCase):
    def test_normalization_and_provenance(self):
        event=normalize({'mint':MINT,'txType':'create','marketCapSol':31.1,'name':'<script>untrusted</script>'},123)
        self.assertEqual(event['kind'],'creation');self.assertEqual(event['received_at'],123)
        self.assertFalse(event['synthetic']);self.assertFalse(event['tradable']);self.assertIsNone(event['source_timestamp'])
        self.assertEqual(event['name'],'<script>untrusted</script>')
    def test_unknown_numbers_not_fabricated(self):
        event=normalize({'mint':MINT,'marketCapSol':'nan','vSolInBondingCurve':-1,'vTokensInBondingCurve':True})
        self.assertIsNone(event['market_cap_sol']);self.assertIsNone(event['virtual_sol_reserve']);self.assertIsNone(event['virtual_token_reserve'])
    def test_bad_mints_and_payloads(self):
        for payload in ([],{}, {'mint':'../../etc/passwd'},{'mint':'0'*44}):
            with self.assertRaises(ValueError):normalize(payload)
    def test_migration(self):
        self.assertEqual(normalize({'mint':MINT,'txType':'migrate'})['kind'],'migration')
    def test_persistence_dedupe_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lab.sqlite';store=PumpStore(path)
            payload={'mint':MINT,'txType':'create','signature':'test','marketCapSol':30}
            self.assertTrue(store.event(payload));self.assertFalse(store.event(payload));store.status('reconnecting','gap');store.db.close()
            store=PumpStore(path);self.assertEqual(store.count(),1);self.assertEqual(store.export()[0]['raw'],payload)
            self.assertEqual(store.recent()[0]['kind'],'creation');store.db.close()

if __name__=='__main__':unittest.main()
