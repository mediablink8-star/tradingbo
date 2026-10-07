import time
import unittest

from signing_policy import build


class SigningPolicyTests(unittest.TestCase):
    def base(self):
        return {
            "wallet": "11111111111111111111111111111111",
            "mint": "22222222222222222222222222222222",
            "side": "buy",
            "input_base_units": "1000000",
            "expected_output_base_units": "500000",
            "minimum_output_base_units": "490000",
            "slippage_bps": 50,
            "lastValidBlockHeight": 123456,
            "router": "aggregator",
            "requestId": "req-1",
        }

    def test_block_height_policy_is_deterministic(self):
        record=self.base()
        a,ha=build(record)
        b,hb=build(record)
        self.assertEqual(a,b)
        self.assertEqual(ha,hb)
        self.assertEqual(a["expiry"]["kind"],"block_height")

    def test_timestamp_expiry_is_supported(self):
        record=self.base()
        record.pop("lastValidBlockHeight")
        record["expireAt"]=time.time()+10
        policy,_=build(record)
        self.assertEqual(policy["expiry"]["kind"],"timestamp")

    def test_expired_timestamp_is_rejected(self):
        record=self.base()
        record.pop("lastValidBlockHeight")
        record["expireAt"]=time.time()-1
        with self.assertRaises(ValueError):
            build(record)

    def test_long_timestamp_expiry_is_rejected(self):
        record=self.base()
        record.pop("lastValidBlockHeight")
        record["expireAt"]=time.time()+61
        with self.assertRaises(ValueError):
            build(record)


if __name__=="__main__":
    unittest.main()
