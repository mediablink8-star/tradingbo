import os, tempfile, unittest
from autonomous_execution import AutonomousExecutor
from autonomous_signer import SignerClient

class AutonomousBoundaryTests(unittest.TestCase):
    def test_disabled_by_default(self):
        old=os.environ.pop("AUTONOMOUS_LIVE_ENABLE",None)
        try:
            with tempfile.NamedTemporaryFile() as f:
                result=AutonomousExecutor(f.name,SignerClient()).status()
                self.assertFalse(result["enabled"])
                self.assertFalse(result["private_key_in_process"])
        finally:
            if old is not None: os.environ["AUTONOMOUS_LIVE_ENABLE"]=old

    def test_signer_requires_credentials(self):
        self.assertFalse(SignerClient(endpoint="",api_token="").configured())

if __name__=="__main__":
    unittest.main()
