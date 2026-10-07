import os, tempfile, unittest, base64
import swaps
from autonomous_execution import AutonomousExecutor
from autonomous_signer import SignerClient

class AutonomousBoundaryTests(unittest.TestCase):
    def test_disabled_by_default(self):
        old_enable=os.environ.pop("AUTONOMOUS_LIVE_ENABLE",None)
        old_wallet=os.environ.pop("AUTONOMOUS_WALLET",None)
        try:
            with tempfile.NamedTemporaryFile() as f:
                result=AutonomousExecutor(f.name,SignerClient()).status()
                self.assertFalse(result["enabled"])
                self.assertFalse(result["private_key_in_process"])
        finally:
            if old_enable is not None: os.environ["AUTONOMOUS_LIVE_ENABLE"]=old_enable
            if old_wallet is not None: os.environ["AUTONOMOUS_WALLET"]=old_wallet

    def test_transaction_parser_rejects_wrong_signer(self):
        wallet='11111111111111111111111111111111'
        other='2'*32
        with self.assertRaises(ValueError):
            swaps.message(base64.b64encode(bytes([1])+bytes(64)+bytes([1,0,0,2])+bytes(32)+bytes(32)+bytes(32)+bytes([1,1,0,0])).decode(),other)

    def test_signer_requires_credentials(self):
        self.assertFalse(SignerClient(endpoint="",api_token="").configured())

    def test_autonomous_requires_operator_gate(self):
        old_enable=os.environ.get("AUTONOMOUS_LIVE_ENABLE")
        old_wallet=os.environ.get("AUTONOMOUS_WALLET")
        os.environ["AUTONOMOUS_LIVE_ENABLE"]="1"
        os.environ["AUTONOMOUS_WALLET"]="11111111111111111111111111111111"
        try:
            with tempfile.NamedTemporaryFile() as f:
                executor=AutonomousExecutor(
                    f.name,
                    SignerClient(endpoint="http://signer.invalid",api_token="test"),
                )
                with self.assertRaisesRegex(ValueError,"operator live gate"):
                    executor.execute_buy(
                        wallet=os.environ["AUTONOMOUS_WALLET"],
                        mint="So11111111111111111111111111111111111111112",
                        usd=1,
                    )
        finally:
            if old_enable is None: os.environ.pop("AUTONOMOUS_LIVE_ENABLE",None)
            else: os.environ["AUTONOMOUS_LIVE_ENABLE"]=old_enable
            if old_wallet is None: os.environ.pop("AUTONOMOUS_WALLET",None)
            else: os.environ["AUTONOMOUS_WALLET"]=old_wallet

if __name__=="__main__":
    unittest.main()
