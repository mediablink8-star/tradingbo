"""Deterministic transaction policy shared with the external signer.

This module deliberately does not pretend to decode arbitrary Jupiter route
instructions. It binds the signer decision to the exact prepared message,
wallet, economic intent, expiry, and permitted top-level programs. The
external signer must independently perform this validation before signing.
"""
import hashlib
import json
import time

POLICY_VERSION = "2"

def build(record, message_hash):
    if not isinstance(message_hash, str) or len(message_hash) != 64:
        raise ValueError("Invalid prepared message hash.")
    if record.get("side") not in ("buy", "sell"):
        raise ValueError("Invalid trade side.")
    wallet = record.get("wallet")
    mint = record.get("mint")
    if not isinstance(wallet, str) or not wallet:
        raise ValueError("Missing signer wallet.")
    if not isinstance(mint, str) or not mint:
        raise ValueError("Missing token mint.")

    input_units = int(record["input_base_units"])
    expected = int(record["expected_output_base_units"])
    minimum = int(record["minimum_output_base_units"])
    if input_units <= 0 or expected <= 0 or minimum <= 0 or minimum > expected:
        raise ValueError("Invalid economic bounds.")

    expiry = record.get("lastValidBlockHeight")
    if expiry is not None:
        expiry = int(expiry)
        if expiry <= 0:
            raise ValueError("Invalid block-height expiry.")
        expiry_obj = {"kind": "block_height", "value": expiry}
    else:
        expires = float(record.get("expireAt", 0))
        if not time.time() < expires <= time.time() + 60:
            raise ValueError("Transaction timestamp expiry is missing or unsafe.")
        expiry_obj = {"kind": "timestamp", "value": expires}

    policy = {
        "version": POLICY_VERSION,
        "message_hash": message_hash,
        "wallet": wallet,
        "mint": mint,
        "side": record["side"],
        "input_base_units": str(input_units),
        "expected_output_base_units": str(expected),
        "minimum_output_base_units": str(minimum),
        "slippage_bps": int(record["slippage_bps"]),
        "expiry": expiry_obj,
        "router": record.get("router"),
        "request_id": record.get("requestId"),
        "allowed_programs": sorted(record.get("allowed_programs", [])),
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return policy, hashlib.sha256(encoded).hexdigest()
