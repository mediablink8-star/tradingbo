import io
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch
import meme_safety
from meme_safety import SolanaMintSafetyChecker, LEGACY_TOKEN_PROGRAM

MINT = "So11111111111111111111111111111111111111112"


def response_for(method, params):
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


def rpc_adapter(method_handler=response_for):
    def call(url, payload):
        return method_handler(payload["method"], payload["params"])
    return call


class SolanaMintSafetyTests(unittest.TestCase):
    def test_http_error_label_includes_status_code(self):
        error = urllib.error.HTTPError(
            "https://example.test/rpc", 429, "Too Many Requests", Message(), None
        )
        self.assertEqual(meme_safety._error_label(error), "http_429")

    def test_http_429_is_retried_with_retry_after(self):
        headers = Message()
        headers["Retry-After"] = "0"
        rate_limited = urllib.error.HTTPError(
            "https://example.test/rpc", 429, "Too Many Requests", headers, None
        )

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        with patch.object(
            meme_safety.urllib.request, "urlopen",
            side_effect=[rate_limited, Response(b'{"result": {"ok": true}}')],
        ) as fetch, patch.object(meme_safety.time, "sleep") as sleep:
            result = meme_safety._fetch_json("https://example.test/rpc", {"method": "test"})

        self.assertEqual(result, {"result": {"ok": True}})
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_transient_rpc_retry_count_is_bounded(self):
        headers = Message()
        error = urllib.error.HTTPError(
            "https://example.test/rpc", 429, "Too Many Requests", headers, None
        )
        with patch.object(
            meme_safety.urllib.request, "urlopen", side_effect=[error, error]
        ) as fetch, patch.object(meme_safety.time, "sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                meme_safety._fetch_json("https://example.test/rpc", {"method": "test"})
        self.assertEqual(fetch.call_count, 2)

    def test_primary_rpc_throttle_uses_read_only_fallback(self):
        primary = "https://primary.example/rpc"
        fallback = "https://fallback.example/rpc"
        calls = []

        def call(url, payload):
            calls.append(url)
            if url == primary:
                raise urllib.error.HTTPError(
                    url, 429, "Too Many Requests", Message(), None
                )
            return {"result": {"value": {"ok": True}}}

        checker = SolanaMintSafetyChecker(rpc_url=primary, rpc_call=call)
        checker._using_default_rpc = True
        checker.fallback_rpc_url = fallback
        result = checker._rpc("getTokenSupply", [MINT, {"commitment": "confirmed"}])

        self.assertEqual(result, {"value": {"ok": True}})
        self.assertEqual(calls, [primary, fallback])

    def test_reports_revoked_authorities_and_account_concentration(self):
        result = SolanaMintSafetyChecker(rpc_call=rpc_adapter()).check(MINT)
        self.assertEqual(result["status"], "CHECKS_COMPLETE")
        self.assertFalse(result["mint_authority_active"])
        self.assertFalse(result["freeze_authority_active"])
        self.assertEqual(result["top_20_token_accounts_supply_pct"], 65.0)
        self.assertIn("top_20_accounts_concentrated", [f["code"] for f in result["findings"]])
        self.assertFalse(result["execution_enabled"])

    def test_active_authorities_are_flagged(self):
        def handler(method, params):
            response = response_for(method, params)
            if method == "getAccountInfo":
                response["result"]["value"]["data"]["parsed"]["info"].update({
                    "mintAuthority": "authority", "freezeAuthority": "authority2",
                })
            return response
        result = SolanaMintSafetyChecker(rpc_call=rpc_adapter(handler)).check(MINT)
        codes = {f["code"] for f in result["findings"]}
        self.assertIn("mint_authority_active", codes)
        self.assertIn("freeze_authority_active", codes)

    def test_rpc_failure_is_incomplete_not_safe(self):
        def broken(url, payload):
            raise TimeoutError("provider unavailable")
        result = SolanaMintSafetyChecker(rpc_call=broken).check(MINT)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertTrue(result["errors"])
        self.assertFalse(result["execution_enabled"])

    def test_unknown_owner_program_is_flagged(self):
        def handler(method, params):
            response = response_for(method, params)
            if method == "getAccountInfo":
                response["result"]["value"]["owner"] = "unknown"
            return response
        result = SolanaMintSafetyChecker(rpc_call=rpc_adapter(handler)).check(MINT)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertIn("unknown_token_program", [f["code"] for f in result["findings"]])

    def test_rejects_non_https_rpc_endpoint(self):
        with self.assertRaises(ValueError):
            SolanaMintSafetyChecker(rpc_url="http://example.com", rpc_call=rpc_adapter())

    def test_rejects_empty_mint(self):
        checker = SolanaMintSafetyChecker(rpc_call=rpc_adapter())
        with self.assertRaises(ValueError):
            checker.check(" ")

if __name__ == "__main__":
    unittest.main()
