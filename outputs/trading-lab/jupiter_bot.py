"""Jupiter swap client + bot trading route installer.

Provides live Solana memecoin execution through the Jupiter Swap API.
Uses Swap V2 /order (requires JUPITER_API_KEY) when available, falling
back to Swap V1 /quote. The private key is held only in server memory.

Install into app.py like live_routes:
    import jupiter_bot
    jupiter_bot.install(Handler, globals())
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

import base58
import nacl.signing
import nacl.exceptions

JUPITER_BASE = "https://api.jup.ag/swap/v1"
JUPITER_BASE_V2 = "https://api.jup.ag/swap/v2"  # requires JUPITER_API_KEY
SOLANA_RPC = "https://api.mainnet-beta.solana.com"
WRAPPED_SOL_MINT = "So11111111111111111111111111111111111111112"
USER_AGENT = "TradingBo-JupiterBot/0.1"

# Risk defaults sized for a small wallet
DEFAULT_MAX_TRADE_USD = 5.0
DEFAULT_MAX_EXPOSURE_USD = 10.0
DEFAULT_MAX_DAILY_LOSS_USD = 15.0
DEFAULT_SLIPPAGE_BPS = 50  # 0.5%
DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS = 5000


class JupiterClient:
    """Live Solana swap client via Jupiter DEX aggregator."""

    def __init__(
        self,
        private_key_b58: Optional[str] = None,
        rpc_url: str = SOLANA_RPC,
        jupiter_base: str = JUPITER_BASE,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
        api_key: Optional[str] = None,
    ):
        self._lock = threading.RLock()
        self._private_key: Optional[bytes] = None
        self._pubkey: Optional[str] = None
        self.rpc_url = rpc_url
        self.jupiter_base = jupiter_base
        self.jupiter_base_v2 = JUPITER_BASE_V2
        self.slippage_bps = slippage_bps
        self._api_key: Optional[str] = (
            api_key or os.environ.get("JUPITER_API_KEY", "").strip() or None
        )
        if private_key_b58:
            self._set_key(private_key_b58)

    @property
    def configured(self) -> bool:
        return self._private_key is not None

    def _set_key(self, private_key_b58: str) -> dict:
        """Store the 64-byte base58 secret key in memory only."""
        decoded = base58.b58decode(private_key_b58.strip())
        if len(decoded) != 64:
            raise ValueError(
                f"Expected 64-byte Solana secret key, got {len(decoded)} bytes"
            )
        seed = decoded[:32]
        signing_key = nacl.signing.SigningKey(seed)
        pubkey = base58.b58encode(bytes(signing_key.verify_key.encode())).decode()
        with self._lock:
            self._private_key = seed
            self._pubkey = pubkey
            self._signing_key = signing_key
        return {"pubkey": pubkey, "wallet_configured": True}

    def forget_key(self) -> dict:
        with self._lock:
            self._private_key = None
            self._pubkey = None
            self._signing_key = None
        return {"wallet_configured": False}

    def status(self) -> dict:
        with self._lock:
            return {
                "broker": "jupiter_swap_v2" if self._api_key else "jupiter_swap_v1",
                "rpc": self.rpc_url,
                "jupiter_api": self.jupiter_base,
                "jupiter_api_v2": self.jupiter_base_v2,
                "wallet_configured": self._private_key is not None,
                "wallet_address": self._pubkey,
                "slippage_bps": self.slippage_bps,
                "api_key_configured": self._api_key is not None,
            }

    # ── On-chain queries ────────────────────────────────────

    def _rpc(self, method: str, params: list) -> Any:
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        req = urllib.request.Request(
            self.rpc_url,
            data=payload.encode(),
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read(1_000_000))
                if result.get("error"):
                    raise RuntimeError(f"RPC {method}: {result['error']}")
                return result.get("result")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                if attempt >= 2:
                    raise
                time.sleep(0.5 * (2 ** attempt))

    def sol_balance(self, address: str = None) -> float:
        """Return SOL balance for _pubkey or a given address (as float SOL)."""
        with self._lock:
            pubkey = address or self._pubkey
        if not pubkey:
            return 0.0
        result = self._rpc("getBalance", [pubkey, {"commitment": "confirmed"}])
        lamports = int(result["value"])
        return lamports / 1_000_000_000

    def token_balance(self, mint: str) -> float:
        """Return token balance (UI amount) for the wallet's ATA."""
        with self._lock:
            if not self._pubkey:
                return 0.0
        # getAccountInfo on the associated token account
        # Derive ATA: pubkey + "Account" seed
        import hashlib
        # Simplified: use getTokenAccountsByOwner instead
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [self._pubkey, {"mint": mint}, "jsonParsed"],
        })
        req = urllib.request.Request(
            self.rpc_url, data=payload.encode(),
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        accounts = result.get("result", {}).get("value", [])
        if not accounts:
            return 0.0
        info = accounts[0].get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        return float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)

    # ── Jupiter API ─────────────────────────────────────────

    def _jup_headers(self) -> dict:
        """Build headers, including API key if present."""
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
            headers["Jupiter-API-Key"] = self._api_key
        return headers

    def _jup_get(self, path: str, params: dict) -> dict:
        """GET request to Jupiter Swap V1 API with error handling and retries.
        Always returns a dict — on HTTP error, returns the decoded error body
        so callers can inspect the 'error' field instead of crashing.
        """
        query = urllib.parse.urlencode(params)
        url = f"{self.jupiter_base}{path}?{query}"
        for attempt in range(3):
            req = urllib.request.Request(url, headers=self._jup_headers())
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read(2_000_000))
            except urllib.error.HTTPError as exc:
                # API returned 4xx/5xx — parse the error body
                body = exc.read(2_000_000)
                try:
                    error_data = json.loads(body)
                except json.JSONDecodeError:
                    error_data = {
                        "error": f"HTTP {exc.code}",
                        "detail": body.decode("utf-8", errors="replace")[:300],
                    }
                return error_data
            except (urllib.error.URLError, TimeoutError):
                if attempt >= 2:
                    return {"error": "Network error after retries"}
                time.sleep(0.5 * (2 ** attempt))
        return {"error": "Max retries exceeded"}

    def _jup_post(self, path: str, body: dict) -> dict:
        """POST request to Jupiter Swap V1 API with error handling and retries."""
        for attempt in range(3):
            req = urllib.request.Request(
                f"{self.jupiter_base}{path}",
                data=json.dumps(body).encode(),
                headers={**self._jup_headers(), "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read(2_000_000))
            except urllib.error.HTTPError as exc:
                raw = exc.read(2_000_000)
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {
                        "error": f"HTTP {exc.code}",
                        "detail": raw.decode("utf-8", errors="replace")[:300],
                    }
            except (urllib.error.URLError, TimeoutError):
                if attempt >= 2:
                    return {"error": "Network error after retries"}
                time.sleep(0.5 * (2 ** attempt))
        return {"error": "Max retries exceeded"}

    def _jup_get_v2(self, path: str, params: dict) -> dict:
        """GET request to Jupiter Swap V2 API (requires JUPITER_API_KEY).
        Always returns a dict — on HTTP error, returns the decoded error body.
        """
        query = urllib.parse.urlencode(params)
        url = f"{self.jupiter_base_v2}{path}?{query}"
        for attempt in range(3):
            req = urllib.request.Request(url, headers=self._jup_headers())
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read(2_000_000))
            except urllib.error.HTTPError as exc:
                body = exc.read(2_000_000)
                try:
                    error_data = json.loads(body)
                except json.JSONDecodeError:
                    error_data = {
                        "error": f"HTTP {exc.code}",
                        "detail": body.decode("utf-8", errors="replace")[:300],
                    }
                return error_data
            except (urllib.error.URLError, TimeoutError):
                if attempt >= 2:
                    return {"error": "Network error after retries"}
                time.sleep(0.5 * (2 ** attempt))
        return {"error": "Max retries exceeded"}

    def quote(self, input_mint: str, output_mint: str, amount: int,
              slippage_bps: Optional[int] = None, restrict_intermediate_tokens: bool = True) -> dict:
        """Get a swap quote from Jupiter Swap V1. `amount` is in input token raw units.
        Returns a dict — on API error, returns {'error': '...', 'detail': ...}.
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps if slippage_bps is not None else int(self.slippage_bps)),
        }
        if restrict_intermediate_tokens:
            params["restrictIntermediateTokens"] = "true"
        result = self._jup_get("/quote", params)
        if "error" in result and "data" not in result:
            # Jupiter API error response
            return {"error": result.get("error", "Unknown error"), **result}
        return result

    def quote_v2(self, input_mint: str, output_mint: str, amount: int,
                 slippage_bps: Optional[int] = None) -> dict:
        """Get a swap quote via Jupiter Swap V2 /order endpoint.
        Requires JUPITER_API_KEY. `amount` is in input token raw units.
        Returns a dict — on API error, returns {'error': '...', 'detail': ...}.
        Does NOT include taker, so no transaction is returned — use for
        quote-only checks. For the full swap, use get_quote_and_swap.
        """
        if not self._api_key:
            return {"error": "JUPITER_API_KEY required for V2 API"}
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps if slippage_bps is not None else int(self.slippage_bps)),
        }
        result = self._jup_get_v2("/order", params)
        if "error" in result and "data" not in result:
            return {"error": result.get("error", "Unknown V2 error"), **result}
        return result

    def build_swap_tx(self, quote_response: dict, user_pubkey: str) -> dict:
        """Build the swap transaction from a quote response (Jupiter /swap endpoint)."""
        body = {
            "quoteResponse": quote_response,
            "userPublicKey": user_pubkey,
            "wrapUnwrap": False,
            "computeUnitPriceMicroLamports": DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS,
        }
        return self._jup_post("/swap", body)

    # ── Transaction validation ─────────────────────────────────

    @staticmethod
    def _read_compact_u16(data: bytes, offset: int) -> tuple:
        """Read a compact-u16 from *data* starting at *offset*.

        Returns (value, new_offset). Raises ValueError on truncation.
        """
        value = 0
        shift = 0
        while True:
            if offset >= len(data):
                raise ValueError("truncated compact-u16")
            b = data[offset]
            offset += 1
            value |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
            if shift >= 16:
                raise ValueError("compact-u16 exceeds 16 bits")
        return value, offset

    def _verify_fee_payer(self, message_bytes: bytes, expected_pubkey_b58: str) -> tuple:
        """Verify that the fee payer (first account key) in *message_bytes*
        matches *expected_pubkey_b58*.

        Returns (True, None) on success, (False, reason_str) on failure.
        """
        if not message_bytes or len(message_bytes) < 4:
            return False, "message too short"

        offset = 0
        if message_bytes[0] & 0x80:
            version = message_bytes[0] & 0x7F
            if version != 0:
                return False, f"unsupported message version v{version}"
            offset = 1
        else:
            if len(message_bytes) < 3:
                return False, "legacy message too short for header"

        num_required = message_bytes[offset]
        offset += 3
        if offset > len(message_bytes):
            return False, "message truncated before account keys"

        try:
            count, offset = self._read_compact_u16(message_bytes, offset)
        except ValueError:
            return False, "truncated account count"

        if num_required != 1:
            return False, f"expected exactly 1 required signer, got {num_required}"
        if count < 1:
            return False, "no accounts in message"

        if offset + 32 > len(message_bytes):
            return False, "missing fee payer pubkey"

        fee_payer_bytes = bytes(message_bytes[offset:offset + 32])
        fee_payer_b58 = base58.b58encode(fee_payer_bytes).decode()

        if fee_payer_b58 != expected_pubkey_b58:
            return False, (
                f"fee payer mismatch: transaction fee payer does not match wallet"
            )
        return True, None

    def _verify_transaction_structure(self, decoded: bytes) -> tuple:
        """Verify the transaction structure before signing.

        Checks:
        - Transaction is not empty
        - Signature count is exactly 1 (fee payer only)
        - Version prefix (if present) is v0 only
        - Address lookup tables are NOT accepted (cannot be independently validated)

        Returns (ok, message_bytes_or_reason, version_prefix, sig_count).
        """
        if not decoded or len(decoded) < 64:
            return False, "transaction too short", None, 0

        idx = 0
        version_prefix = None
        if decoded[0] & 0x80:
            version_prefix = decoded[0]
            version = version_prefix & 0x7F
            if version != 0:
                return False, f"unsupported transaction version v{version}", None, 0
            idx = 1

        try:
            sig_count, idx = self._read_compact_u16(decoded, idx)
        except ValueError:
            return False, "truncated signature count", None, 0

        if sig_count != 1:
            return False, (
                f"expected exactly 1 signature in the transaction, got {sig_count}"
            ), version_prefix, sig_count

        msg_start = idx + sig_count * 64
        message_bytes = decoded[msg_start:]
        if not message_bytes:
            return False, "empty message in transaction", version_prefix, sig_count

        # Reject versioned messages — the signing code does not resolve or
        # validate address lookup tables, so v0 messages with ALTs are unsafe.
        if message_bytes[0] & 0x80:
            return False, (
                "versioned message with address lookup tables is unsupported; "
                "refusing to sign"
            ), version_prefix, sig_count

        return True, message_bytes, version_prefix, sig_count

    def sign_and_send(self, swap_response: dict, private_key: bytes) -> dict:
        """Sign and submit the swap transaction.

        Handles both legacy and versioned Solana transactions.
        Supports V1 swapTransaction field and V2 transaction field.
        """
        swap_tx = swap_response.get("swapTransaction") or swap_response.get("transaction", "")
        if not swap_tx:
            return {"ok": False, "error": "No swapTransaction or transaction in response"}

        # Jupiter Swap V1 returns the transaction via /swap endpoint
        # ready for signing. Handle both legacy and versioned transactions.
        decoded = base64.b64decode(swap_tx)

        # SECURITY: Validate transaction structure before signing.
        # Verifies signature count is exactly 1 (fee payer only),
        # rejects versioned messages with address lookup tables
        # that cannot be independently validated.
        ok, message_bytes_or_reason, version_prefix, sig_count = \
            self._verify_transaction_structure(decoded)
        if not ok:
            return {"ok": False, "error": f"Transaction validation failed: {message_bytes_or_reason}"}

        # SECURITY: Verify the fee payer in the message matches the wallet
        # derived from the private key being used to sign.
        signing_key = nacl.signing.SigningKey(private_key)
        derived_pubkey = base58.b58encode(
            bytes(signing_key.verify_key.encode())
        ).decode()

        ok, reason = self._verify_fee_payer(message_bytes_or_reason, derived_pubkey)
        if not ok:
            return {"ok": False, "error": f"Transaction validation failed: {reason}"}

        message_bytes = message_bytes_or_reason

        # signing_key was already created above for fee payer verification
        msg_hash = hashlib.sha256(message_bytes).digest()
        signed = signing_key.sign(msg_hash)
        signature = bytes(signed.signature)[:64]

        # Rebuild the transaction with the signature
        signed_tx = bytearray()
        if version_prefix is not None:
            signed_tx.append(version_prefix)
        # Re-encode sig_count as compact-u16 (always 1 after validation)
        signed_tx.append(1)
        # Our signature (index 0; sig_count is validated as exactly 1)
        signed_tx.extend(signature)
        # Append the message
        signed_tx.extend(message_bytes)
        tx_b64 = base64.b64encode(bytes(signed_tx)).decode()
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [tx_b64, {"skipPreflight": True, "maxRetry": 3, "commitment": "confirmed"}],
        })
        req = urllib.request.Request(
            self.rpc_url, data=payload.encode(),
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            if result.get("error"):
                return {"ok": False, "error": result["error"]}
            return {"ok": True, "signature": result.get("result")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_quote_and_swap(self, output_mint: str, sol_amount: float) -> dict:
        """Convenience: get a SOL to token swap quote and build the swap tx.

        Uses Jupiter Swap V2 /order (with taker) when JUPITER_API_KEY is set,
        falling back to Swap V1 quote + swap when it is not or when V2 fails.
        """
        with self._lock:
            if not self._pubkey:
                return {"ok": False, "error": "Wallet not configured"}
        lamports = int(sol_amount * 1_000_000_000)

        # --- V2 path: /order returns quote + transaction in one call ---
        if self._api_key:
            v2_params = {
                "inputMint": WRAPPED_SOL_MINT,
                "outputMint": output_mint,
                "amount": str(lamports),
                "slippageBps": str(int(self.slippage_bps)),
                "taker": self._pubkey,
            }
            v2_result = self._jup_get_v2("/order", v2_params)
            if "error" not in v2_result:
                out_amount = int(v2_result.get("outAmount", "0"))
                if out_amount > 0:
                    return {
                        "ok": True,
                        "quote": v2_result,
                        "swap": {"transaction": v2_result.get("transaction", "")},
                        "out_amount": out_amount,
                        "price_impact_pct": float(v2_result.get("priceImpactPct", 0)),
                    }
            # V2 failed — log and fall through to V1
            print(f"Jupiter V2 API error, falling back to V1: "
                  f"{v2_result.get('error', 'unknown')}", flush=True)

        # --- V1 path (fallback) ---
        quote = self.quote(WRAPPED_SOL_MINT, output_mint, lamports)
        if "error" in quote:
            return {"ok": False, "error": quote.get("error", "Unknown API error"), "detail": quote}
        out_amount = int(quote.get("outAmount", "0"))
        if out_amount <= 0:
            return {"ok": False, "error": "No swap routes available", "detail": quote}

        swap = self.build_swap_tx(quote, self._pubkey)
        if "swapTransaction" not in swap:
            return {"ok": False, "error": "Swap build failed", "detail": swap}
        return {
            "ok": True,
            "quote": quote,
            "swap": swap,
            "out_amount": out_amount,
            "price_impact_pct": float(quote.get("priceImpactPct", "0")),
        }


# ── Risk gate for small wallet ─────────────────────────────

class MemeRiskGate:
    """Lightweight risk gate for memecoin trading with a small wallet."""

    def __init__(self, max_trade_usd: float = DEFAULT_MAX_TRADE_USD,
                 max_exposure_usd: float = DEFAULT_MAX_EXPOSURE_USD,
                 max_daily_loss_usd: float = DEFAULT_MAX_DAILY_LOSS_USD,
                 arm_ttl_hours: float = 24.0):
        self.max_trade_usd = max_trade_usd
        self.max_exposure_usd = max_exposure_usd
        self.max_daily_loss_usd = max_daily_loss_usd
        self.arm_ttl_hours = arm_ttl_hours
        self.armed = False
        self.armed_until = 0.0
        self.daily_loss = 0.0
        self.day_key = ""
        self._lock = threading.Lock()

    def _roll_day(self):
        key = time.strftime("%Y-%m-%d", time.gmtime())
        if key != self.day_key:
            self.day_key = key
            self.daily_loss = 0.0

    def arm(self, hours: float = None) -> dict:
        with self._lock:
            self._roll_day()
            ttl = hours if hours is not None else self.arm_ttl_hours
            self.armed = True
            self.armed_until = time.time() + ttl * 3600.0
        return self.status()

    def disarm(self) -> dict:
        with self._lock:
            self.armed = False
            self.armed_until = 0.0
        return self.status()

    def status(self) -> dict:
        with self._lock:
            self._roll_day()
            now = time.time()
            if self.armed and self.armed_until and now > self.armed_until:
                self.armed = False
        return {
            "armed": self.armed,
            "seconds_remaining": max(0, int(self.armed_until - time.time())) if self.armed else 0,
            "daily_loss_usd": round(self.daily_loss, 4),
            "limits": {
                "max_trade_usd": self.max_trade_usd,
                "max_exposure_usd": self.max_exposure_usd,
                "max_daily_loss_usd": self.max_daily_loss_usd,
            },
        }

    def check_order(self, notional_usd: float) -> dict:
        """Check if an order is allowed. Returns {allowed, reason, sized_usd}."""
        with self._lock:
            self._roll_day()
            if not self.armed:
                return {"allowed": False, "reason": "DISARMED — arm the bot first", "sized_usd": 0}
            if self.armed_until and time.time() > self.armed_until:
                self.armed = False
                return {"allowed": False, "reason": "ARM expired — re-arm required", "sized_usd": 0}
            if self.daily_loss >= self.max_daily_loss_usd:
                return {"allowed": False, "reason": f"daily loss limit hit (${self.daily_loss:.2f})", "sized_usd": 0}
            sized = min(notional_usd, self.max_trade_usd)
            if sized <= 0:
                return {"allowed": False, "reason": "notional must be > 0", "sized_usd": 0}
            return {"allowed": True, "reason": "ok", "sized_usd": round(sized, 2)}

    def record_loss(self, amount: float):
        with self._lock:
            self.daily_loss += max(0, amount)


# ── Route installer ────────────────────────────────────────

def install(handler_cls, g: dict):
    """Monkey-patch Handler with Jupiter trading routes."""
    jupiter = JupiterClient()
    risk = MemeRiskGate(
        max_trade_usd=float(g.get("MEME_MAX_TRADE_USD", DEFAULT_MAX_TRADE_USD)),
        max_exposure_usd=float(g.get("MEME_MAX_EXPOSURE_USD", DEFAULT_MAX_EXPOSURE_USD)),
        max_daily_loss_usd=float(g.get("MEME_MAX_DAILY_LOSS_USD", DEFAULT_MAX_DAILY_LOSS_USD)),
    )
    g["JUPITER"] = jupiter
    g["JUPITER_RISK"] = risk

    # Auto-connect wallet from SOLANA_PRIVATE_KEY env var (for hosted / persistent mode)
    env_key = os.environ.get("SOLANA_PRIVATE_KEY", "").strip()
    if env_key:
        try:
            jupiter._set_key(env_key)
            print(f"Jupiter wallet auto-connected from env SOLANA_PRIVATE_KEY (pubkey: {jupiter._pubkey})", flush=True)
        except (ValueError, Exception) as _jup_key_err:
            print(f"SOLANA_PRIVATE_KEY in env is invalid: {_jup_key_err}", flush=True)

    orig_get = handler_cls.do_GET
    orig_post = handler_cls.do_POST

    def do_GET(self):
        import urllib.parse
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/jupiter/status":
            self.send_json({"jupiter": jupiter.status(), "risk": risk.status()})
            return
        if path == "/api/jupiter/balance":
            import urllib.parse as _up
            _params = _up.parse_qs(_up.urlparse(self.path).query)
            _addr = _params.get("address", [None])[0]
            _bal = jupiter.sol_balance(_addr) if (_addr or jupiter.configured) else 0.0
            self.send_json({"sol_balance": _bal, "wallet": _addr or jupiter._pubkey, "configured": jupiter.configured})
            return
        return orig_get(self)

    def do_POST(self):
        import urllib.parse
        path = urllib.parse.urlsplit(self.path).path
        if path not in (
            "/api/jupiter/connect",
            "/api/jupiter/disconnect",
            "/api/jupiter/arm",
            "/api/jupiter/disarm",
            "/api/jupiter/quote",
            "/api/jupiter/swap",
        ):
            return orig_post(self)

        if hasattr(self, "_require_auth") and not self._require_auth():
            return

        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > 10000:
                raise ValueError("Invalid request size")
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)
            return

        if path == "/api/jupiter/connect":
            key = str(data.get("private_key", "")).strip()
            if not key:
                self.send_json({"error": "private_key required"}, 400)
                return
            try:
                result = jupiter._set_key(key)
                self.send_json(result)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
            return

        if path == "/api/jupiter/disconnect":
            self.send_json(jupiter.forget_key())
            return

        if path == "/api/jupiter/arm":
            hours = float(data.get("hours", 24))
            self.send_json({"armed": True, **risk.arm(hours)})
            return

        if path == "/api/jupiter/disarm":
            self.send_json(risk.disarm())
            return

        if path == "/api/jupiter/quote":
            if not jupiter.configured:
                self.send_json({"ok": False, "error": "Wallet not connected"}, 400)
                return
            token = str(data.get("token_address", "")).strip()
            sol_amount = float(data.get("sol_amount", 5.0))
            result = jupiter.get_quote_and_swap(token, sol_amount)
            if result.get("ok"):
                result = {
                    "ok": True,
                    "out_amount": result["out_amount"],
                    "price_impact_pct": result["price_impact_pct"],
                    "swap_usd_value": result["quote"].get("swapUsdValue"),
                    "route_plan": result["quote"].get("routePlan"),
                }
            self.send_json(result)
            return

        if path == "/api/jupiter/swap":
            if not jupiter.configured:
                self.send_json({"ok": False, "error": "Wallet not connected"}, 400)
                return
            token = str(data.get("token_address", "")).strip()
            sol_amount = float(data.get("sol_amount", 5.0))
            notional = sol_amount * 100  # rough USD estimate
            check = risk.check_order(notional)
            if not check["allowed"]:
                self.send_json({"ok": False, "error": check["reason"], "risk": risk.status()})
                return

            result = jupiter.get_quote_and_swap(token, sol_amount)
            if not result.get("ok"):
                self.send_json(result)
                return

            swap_result = jupiter.sign_and_send(result["swap"], jupiter._private_key)
            if swap_result.get("ok"):
                self.send_json({
                    "ok": True,
                    "signature": swap_result["signature"],
                    "token": token,
                    "sol_spent": sol_amount,
                    "out_amount": result["out_amount"],
                    "price_impact_pct": result["price_impact_pct"],
                    "explorer": f"https://solscan.io/tx/{swap_result['signature']}",
                })
            else:
                self.send_json({"ok": False, "error": swap_result.get("error")})
            return

        return orig_post(self)

    handler_cls.do_GET = do_GET
    handler_cls.do_POST = do_POST
    return {"jupiter": jupiter, "risk": risk}


def run_jupiter_cycle(jupiter, risk):
    """One autonomous trading cycle.

    Called by the launcher loop when JUPITER_AUTORUN=1.
    Reads JUPITER_AUTOTRADE_TOKENS (comma-separated mint addresses)
    and JUPITER_AUTOTRADE_SOL (SOL per trade) from the environment.
    """
    if not jupiter.configured:
        print("Jupiter auto-trade: wallet not configured, skipping.", flush=True)
        return
    if not risk.armed:
        print("Jupiter auto-trade: risk gate disarmed, skipping.", flush=True)
        return

    tokens_str = os.environ.get("JUPITER_AUTOTRADE_TOKENS", "").strip()
    tokens = [t.strip() for t in tokens_str.split(",") if t.strip()]
    if not tokens:
        print("Jupiter auto-trade: no tokens in JUPITER_AUTOTRADE_TOKENS, skipping.", flush=True)
        return

    sol_amount = float(os.environ.get("JUPITER_AUTOTRADE_SOL", "0.1"))

    for token in tokens:
        try:
            result = jupiter.get_quote_and_swap(token, sol_amount)
            if not result.get("ok"):
                print(f"Jupiter auto-trade: quote failed for {token}: "
                      f"{result.get('error', 'unknown')}", flush=True)
                continue

            notional = sol_amount * 100  # rough USD estimate
            check = risk.check_order(notional)
            if not check["allowed"]:
                print(f"Jupiter auto-trade: risk gate rejected {token}: "
                      f"{check['reason']}", flush=True)
                continue

            swap_result = jupiter.sign_and_send(result["swap"], jupiter._private_key)
            if swap_result.get("ok"):
                print(f"Jupiter auto-trade: swapped {sol_amount} SOL -> {token} | "
                      f"out={result['out_amount']} | "
                      f"impact={result.get('price_impact_pct', 0)}% | "
                      f"sig={swap_result.get('signature', '')[:12]}...", flush=True)
            else:
                print(f"Jupiter auto-trade: swap failed for {token}: "
                      f"{swap_result.get('error')}", flush=True)
        except Exception as exc:
            print(f"Jupiter auto-trade: error for {token}: {exc}", flush=True)