"""Deterministic signing-policy contract for the external signer.

The trading process never signs. This module canonicalizes the exact economic
intent so an independent signer can enforce the same constraints before signing.
"""
import hashlib
import json
import time

POLICY_VERSION = "1"
MAX_EXPIRY_SECONDS = 60

def build(record):
    now = time.time()
    expiry = record.get("lastValidBlockHeight")
    if expiry is not None:
        expiry = int(expiry)
        if expiry <= 0:
            raise ValueError("Invalid block-height expiry.")
        expiry_obj = {"kind": "block_height", "value": expiry}
    else:
        expires = float(record.get("expireAt", 0))
        if expires <= now or expires - now > MAX_EXPIRY_SECONDS:
            raise ValueError("Signing policy expiry is missing, expired, or too far in the future.")
        expiry_obj = {"kind": "timestamp", "value": expires}

    policy = {
        "version": POLICY_VERSION,
        "wallet": record["wallet"],
        "mint": record["mint"],
        "side": record["side"],
        "input_base_units": str(record["input_base_units"]),
        "expected_output_base_units": str(record["expected_output_base_units"]),
        "minimum_output_base_units": str(record["minimum_output_base_units"]),
        "slippage_bps": int(record["slippage_bps"]),
        "expiry": expiry_obj,
        "router": record.get("router"),
        "request_id": record.get("requestId"),
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return policy, hashlib.sha256(encoded).hexdigest()
