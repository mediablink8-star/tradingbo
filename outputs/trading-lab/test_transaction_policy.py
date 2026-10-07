import time
import unittest

from transaction_policy import build

class TransactionPolicyTests(unittest.TestCase):
    def record(self):
        return {
            "wallet": "11111111111111111111111111111111",
            "mint": "So11111111111111111111111111111111111111112",
            "side": "buy",
            "input_base_units": "1000000",
            "expected_output_base_units": "900000",
            "minimum_output_base_units": "895500",
            "slippage_bps": 50,
            "lastValidBlockHeight": 123456,
            "router": "aggregator",
            "requestId": "req-1",
            "allowed_programs": ["JUP6"],
        }

    def test_policy_binds_exact_message_hash(self):
        policy, digest = build(self.record(), "a" * 64)
        self.assertEqual(policy["message_hash"], "a" * 64)
        self.assertEqual(len(digest), 64)

    def test_changed_message_hash_changes_policy(self):
        _, first = build(self.record(), "a" * 64)
        _, second = build(self.record(), "b" * 64)
        self.assertNotEqual(first, second)

    def test_rejects_bad_economic_bounds(self):
        record = self.record()
        record["minimum_output_base_units"] = "900001"
        with self.assertRaises(ValueError):
            build(record, "a" * 64)

    def test_timestamp_expiry_is_short_lived(self):
        record = self.record()
        record.pop("lastValidBlockHeight")
        record["expireAt"] = time.time() + 61
        with self.assertRaises(ValueError):
            build(record, "a" * 64)

if __name__ == "__main__":
    unittest.main()
