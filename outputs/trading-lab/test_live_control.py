import os,tempfile,unittest
from live_control import LiveControl

class LiveControlTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            c=LiveControl(d+"/x.sqlite")
            self.assertFalse(c.status()["enabled"])
            self.assertFalse(c.status()["autonomous_signing"])
    def test_arm_requires_environment_flag(self):
        with tempfile.TemporaryDirectory() as d:
            c=LiveControl(d+"/x.sqlite")
            old=os.environ.pop("LIVE_TRADING_ENABLE",None)
            try:
                with self.assertRaises(ValueError): c.arm()
            finally:
                if old is not None: os.environ["LIVE_TRADING_ENABLE"]=old
    def test_limits_and_kill_switch(self):
        with tempfile.TemporaryDirectory() as d:
            c=LiveControl(d+"/x.sqlite");old=os.environ.get("LIVE_TRADING_ENABLE");os.environ["LIVE_TRADING_ENABLE"]="1"
            try:
                c.arm();c.reserve_intent(10)
                with self.assertRaises(ValueError): c.reserve_intent(10)
                c.kill("test")
                self.assertFalse(c.status()["enabled"]);self.assertTrue(c.status()["halted"])
                with self.assertRaises(ValueError): c.arm()
            finally:
                if old is None: os.environ.pop("LIVE_TRADING_ENABLE",None)
                else: os.environ["LIVE_TRADING_ENABLE"]=old
if __name__=="__main__":unittest.main()
