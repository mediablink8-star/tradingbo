import unittest
from meme_safety import (
    SolanaMintSafetyChecker, LEGACY_TOKEN_PROGRAM, TOKEN_2022_PROGRAM,
)


MINT = "So11111111111111111111111111111111111111112"


def rpc_response(method, params):
    if method == "getAccountInfo":
        return {"result": {"value": {
            "owner": LEGACY_TOKEN_PROGRAM,
            "data": {"parsed": {"info": {
                "mintAuthority": None, "freezeAuthority": None,
            }}},
        }}}
    if method == "getTokenSupply":
        return {"result": {"value": {"amount": "1000000", "decimals": 6}}}
    if method == "getTokenLargestAccounts":
        return {"result": {"value": [
            {"address": "a", "amount": "300000"},
            {"address": "b", "amount": "250000"},
            {"address": "c", "amount": "100000"},
        ]}}
    raise AssertionError(method)


class SolanaMintSafetyTests(unittest.TestCase):
    def test_reports_revoked_authorities_and_account_concentration(self):
        checker = SolanaMintSafetyChecker(rpc_call=rpc_response)
        result = checker.check(MINT)
        self.assertEqual(result["status"], "CHECKS_COMPLETE")
        self.assertFalse(result["mint_authority_active"])
        self.assertFalse(result["freeze_authority_active"])
        self.assertEqual(result["top_20_token_accounts_supply_pct"], 65.0)
        self.assertIn("top_20_accounts_concentrated", [f["code"] for f in result["findings"]])
        self.assertFalse(result["execution_enabled"])

    def test_active_authorities_are_flagged(self):
        def rpc(method, params):
            response = rpc_response(method, params)
            if method == "getAccountInfo":
                response["result"]["value"]["data"]["parsed"]["info"].update({
                    "mintAuthority": "authority", "freezeAuthority": "authority2",
                })
            return response
        result = SolanaMintSafetyChecker(rpc_call=rpc).check(MINT)
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("mint_authority_active", codes)
        self.assertIn("freeze_authority_active", codes)

    def test_rpc_failure_is_incomplete_not_safe(self):
        def broken(method, params):
            raise TimeoutError("provider unavailable")
        result = SolanaMintSafetyChecker(rpc_call=broken).check(MINT)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertTrue(result["errors"])
        self.assertFalse(result["execution_enabled"])

    def test_unknown_owner_program_is_flagged(self):
        def unknown(method, params):
            response = rpc_response(method, params)
            if method == "getAccountInfo":
                response["result"]["value"]["owner"] = "unknown"
            return response
        result = SolanaMintSafetyChecker(rpc_call=unknown).check(MINT)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("unknown_token_program", [f["code"] for f in result["findings"]])

    def test_rejects_non_https_rpc_endpoint(self):
        with self.assertRaises(ValueError):
            SolanaMintSafetyChecker(rpc_url="http://example.com", rpc_call=rpc_response)

    def test_rejects_empty_mint(self):
        checker = SolanaMintSafetyChecker(rpc_call=rpc_response)
        with self.assertRaises(ValueError):
            checker.check(" ")

if __name__ == "__main__":
    unittest.main()
