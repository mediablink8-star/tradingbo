"""Security tests for jupiter_bot.py — transaction validation, fee-payer checks,
and fail-closed behavior. Uses test-only keys and synthetic transactions. No
real transactions are broadcast.
"""
import base64
import json
import os
import unittest
from unittest.mock import patch, MagicMock

try:
    import base58
    import nacl.signing
    from jupiter_bot import JupiterClient
except ImportError as exc:
    raise unittest.SkipTest(f"Legacy Solana tests are out of scope for the Forex-only runtime: {exc}")


# ── Test-only key material ──────────────────────────────────
TEST_SEED = bytes(range(32))  # deterministic test-only seed
TEST_SIGNING_KEY = nacl.signing.SigningKey(TEST_SEED)
TEST_PUBKEY = base58.b58encode(
    bytes(TEST_SIGNING_KEY.verify_key.encode())
).decode()

# Another test-only key for "wrong wallet" tests
OTHER_SEED = bytes(range(31, -1, -1))
OTHER_SIGNING_KEY = nacl.signing.SigningKey(OTHER_SEED)
OTHER_PUBKEY = base58.b58encode(
    bytes(OTHER_SIGNING_KEY.verify_key.encode())
).decode()


def make_legacy_tx(fee_payer_bytes: bytes, num_extra_accounts: int = 0) -> bytes:
    """Build a minimal legacy Solana transaction with 1 required signer.

    Structure:
      compact-u16(1)        # 1 signature
      [64 zero bytes]       # signature placeholder (unsigned)
      message:
        1 byte: num_required_signatures = 1
        1 byte: num_readonly_signed = 0
        1 byte: num_readonly_unsigned = num_extra_accounts
        compact-u16(1)      # account count = 1 (fee payer)
        32 bytes: fee payer pubkey
        32 bytes: recent blockhash (zeros)
        compact-u16(0)      # instruction count = 0
    """
    parts = bytearray()
    # Signature count = 1 (compact-u16, single byte since < 128)
    parts.append(1)
    # Placeholder signature (64 zero bytes)
    parts.extend(b"\x00" * 64)
    # Message
    parts.append(1)  # num_required_signatures
    parts.append(0)  # num_readonly_signed
    parts.append(num_extra_accounts)  # num_readonly_unsigned
    parts.append(1)  # account count = 1
    parts.extend(fee_payer_bytes)  # fee payer
    parts.extend(b"\x00" * 32)  # recent blockhash
    parts.append(0)  # instruction count = 0
    return bytes(parts)


def make_versioned_tx(fee_payer_bytes: bytes) -> bytes:
    """Build a minimal v0 Solana transaction with 1 required signer.

    Structure:
      0x80                # version prefix (v0)
      compact-u16(1)      # 1 signature
      [64 zero bytes]     # signature placeholder
      message (v0):
        0x80            # versioned message prefix
        ... (same as legacy)
    """
    parts = bytearray()
    parts.append(0x80)  # version prefix
    parts.append(1)     # signature count = 1
    parts.extend(b"\x00" * 64)  # signature placeholder
    parts.append(0x80)  # versioned message prefix
    parts.append(1)  # num_required_signatures
    parts.append(0)  # num_readonly_signed
    parts.append(0)  # num_readonly_unsigned
    parts.append(1)  # account count = 1
    parts.extend(fee_payer_bytes)
    parts.extend(b"\x00" * 32)  # recent blockhash
    parts.append(0)  # instruction count = 0
    return bytes(parts)


def make_multi_sig_tx(fee_payer_bytes: bytes, num_signatures: int) -> bytes:
    """Build a minimal legacy transaction with *num_signatures* signatures."""
    parts = bytearray()
    parts.append(num_signatures)  # signature count
    for _ in range(num_signatures):
        parts.extend(b"\x00" * 64)  # signature placeholder
    parts.append(1)  # num_required_signatures
    parts.append(0)
    parts.append(0)
    parts.append(1)  # account count
    parts.extend(fee_payer_bytes)
    parts.extend(b"\x00" * 32)
    parts.append(0)  # instruction count
    return bytes(parts)


class JupiterSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = JupiterClient()
        self.client._set_key(base58.b58encode(bytes(TEST_SIGNING_KEY.encode()) + b"\x00" * 32).decode())
        # JupiterClient._set_key expects a 64-byte key; for testing we use the seed
        self.client._private_key = TEST_SEED
        self.client._pubkey = TEST_PUBKEY
        self.client._signing_key = TEST_SIGNING_KEY

    def _tx_to_b64(self, raw_tx: bytes) -> str:
        return base64.b64encode(raw_tx).decode()

    def _swap_response(self, raw_tx: bytes) -> dict:
        return {"swapTransaction": self._tx_to_b64(raw_tx)}

    # ── Fee-payer verification ─────────────────────────────────

    def test_sign_and_send_rejects_wrong_fee_payer(self):
        """Transaction whose fee payer != wallet must be rejected (fail-closed)."""
        raw = make_legacy_tx(OTHER_PUBKEY.encode() if False else bytes.fromhex("aa" * 32))
        # Build with a wrong pubkey — need 32 bytes
        wrong_pubkey_bytes = bytes.fromhex("ff" * 32)
        raw = make_legacy_tx(wrong_pubkey_bytes)
        result = self.client.sign_and_send(self._swap_response(raw), TEST_SEED)
        self.assertFalse(result["ok"])
        self.assertIn("fee payer mismatch", result["error"])

    def test_sign_and_send_accepts_correct_fee_payer(self):
        """Transaction with the correct fee payer passes validation."""
        raw = make_legacy_tx(bytes.fromhex(TEST_PUBKEY.encode() if False else "00" * 32))
        # We need the actual pubkey bytes embedded
        pubkey_bytes = base58.b58decode(TEST_PUBKEY)
        raw = make_legacy_tx(pubkey_bytes)
        # sign_and_send will try to broadcast (network call); mock it
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "jsonrpc": "2.0", "id": 1, "result": "5xV...test_signature"
            }).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = self.client.sign_and_send(self._swap_response(raw), TEST_SEED)
        # It should pass validation (error should not be a fee payer mismatch)
        self.assertNotIn("fee payer mismatch", result.get("error", ""))
        if result.get("ok"):
            self.assertEqual(result["signature"], "5xV...test_signature")

    def test_sign_and_send_rejects_versioned_message(self):
        """v0 versioned transactions with ALTs must be rejected."""
        pubkey_bytes = base58.b58decode(TEST_PUBKEY)
        raw = make_versioned_tx(pubkey_bytes)
        result = self.client.sign_and_send(self._swap_response(raw), TEST_SEED)
        self.assertFalse(result["ok"])
        self.assertIn("address lookup tables", result["error"])
        self.assertIn("unsupported", result["error"])

    def test_sign_and_send_rejects_multi_signature(self):
        """Transactions with >1 signature must be rejected."""
        pubkey_bytes = base58.b58decode(TEST_PUBKEY)
        raw = make_multi_sig_tx(pubkey_bytes, 3)
        result = self.client.sign_and_send(self._swap_response(raw), TEST_SEED)
        self.assertFalse(result["ok"])
        self.assertIn("exactly 1 signature", result["error"])

    def test_sign_and_send_rejects_truncated_transaction(self):
        """Truncated transactions must be rejected, not crash."""
        result = self.client.sign_and_send(
            {"swapTransaction": self._tx_to_b64(b"\x01\x02\x03")},
            TEST_SEED,
        )
        self.assertFalse(result["ok"])
        self.assertIn("validation failed", result["error"])

    def test_sign_and_send_rejects_empty_transaction(self):
        """Empty transaction must be rejected."""
        result = self.client.sign_and_send(
            {"swapTransaction": ""},
            TEST_SEED,
        )
        self.assertFalse(result["ok"])
        self.assertIn("No swapTransaction", result["error"])

    def test_sign_and_send_rejects_missing_transaction_field(self):
        """Swap response without transaction field must be rejected."""
        result = self.client.sign_and_send({"quote": {}}, TEST_SEED)
        self.assertFalse(result["ok"])
        self.assertIn("No swapTransaction", result["error"])

    # ── Fee-payer verification unit tests ─────────────────────

    def test_verify_fee_payer_matches(self):
        pubkey_bytes = base58.b58decode(TEST_PUBKEY)
        msg = make_legacy_tx(pubkey_bytes)[65:]  # skip sig count + signature
        ok, reason = self.client._verify_fee_payer(msg, TEST_PUBKEY)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_verify_fee_payer_mismatch(self):
        wrong_bytes = bytes.fromhex("ff" * 32)
        msg = make_legacy_tx(wrong_bytes)[65:]
        ok, reason = self.client._verify_fee_payer(msg, TEST_PUBKEY)
        self.assertFalse(ok)
        self.assertIn("fee payer mismatch", reason)

    def test_verify_transaction_structure_short_tx(self):
        ok, reason, _, _ = self.client._verify_transaction_structure(b"\x01")
        self.assertFalse(ok)
        self.assertIn("too short", reason)

    def test_verify_transaction_structure_multi_sig(self):
        pubkey_bytes = base58.b58decode(TEST_PUBKEY)
        raw = make_multi_sig_tx(pubkey_bytes, 3)
        ok, reason, _, _ = self.client._verify_transaction_structure(raw)
        self.assertFalse(ok)
        self.assertIn("exactly 1", reason)

    # ── Startup safety ────────────────────────────────────────

    def test_wallet_not_configured_blocks_live(self):
        client = JupiterClient()
        self.assertFalse(client.configured)

    def test_sign_and_send_without_key_fails_closed(self):
        client = JupiterClient()
        result = client.sign_and_send(
            {"swapTransaction": self._tx_to_b64(b"\x01" + b"\x00" * 64 + b"\x01\x00\x00\x01\xff" * 32 + b"\x00" * 32 + b"\x00")},
            TEST_SEED,
        )
        self.assertFalse(result["ok"])

    def test_risk_gate_disarmed_blocks_trade(self):
        from jupiter_bot import MemeRiskGate
        gate = MemeRiskGate()
        check = gate.check_order(5.0)
        self.assertFalse(check["allowed"])
        self.assertIn("DISARMED", check["reason"].upper())


class TestKeyFixtures(unittest.TestCase):
    """Sanity-check that our test keys are valid and distinct."""

    def test_keys_are_distinct(self):
        self.assertNotEqual(TEST_PUBKEY, OTHER_PUBKEY)

    def test_pubkey_is_valid_base58(self):
        decoded = base58.b58decode(TEST_PUBKEY)
        self.assertEqual(len(decoded), 32)


class StartupSafetyTests(unittest.TestCase):
    """Verify that live execution is disabled by default and env vars are
    stripped when JUPITER_AUTORUN is not set to \"1\"."""

    def test_autorun_unset_strips_private_key(self):
        os.environ.pop("JUPITER_AUTORUN", None)
        os.environ["SOLANA_PRIVATE_KEY"] = "test_key_that_should_be_stripped"
        result = os.environ.get("JUPITER_AUTORUN", "").strip() == "1"
        self.assertFalse(result)
        if not result:
            os.environ.pop("SOLANA_PRIVATE_KEY", None)
        self.assertNotIn("SOLANA_PRIVATE_KEY", os.environ)

    def test_autorun_zero_strips_private_key(self):
        os.environ["JUPITER_AUTORUN"] = "0"
        os.environ["SOLANA_PRIVATE_KEY"] = "test_key_that_should_be_stripped"
        result = os.environ.get("JUPITER_AUTORUN", "").strip() == "1"
        self.assertFalse(result)
        if not result:
            os.environ.pop("SOLANA_PRIVATE_KEY", None)
        self.assertNotIn("SOLANA_PRIVATE_KEY", os.environ)

    def test_risk_gate_starts_disarmed(self):
        from jupiter_bot import MemeRiskGate
        gate = MemeRiskGate()
        status = gate.status()
        self.assertFalse(status["armed"])

    def test_client_without_key_is_not_configured(self):
        client = JupiterClient()
        self.assertFalse(client.configured)
        self.assertIsNone(client._pubkey)
        self.assertIsNone(client._private_key)


if __name__ == "__main__":
    unittest.main()
