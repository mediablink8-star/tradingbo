"""Jupiter swap client + bot trading route installer.

Provides live Solana memecoin execution through the Jupiter Swap V1 API.
The private key is held only in server memory — never written to disk.

Install into app.py like live_routes:
    import jupiter_bot
    jupiter_bot.install(Handler, globals())
"""
from __future__ import annotations

import base64
import hashlib
import json
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
    ):
        self._lock = threading.RLock()
        self._private_key: Optional[bytes] = None
        self._pubkey: Optional[str] = None
        self.rpc_url = rpc_url
        self.jupiter_base = jupiter_base
        self.slippage_bps = slippage_bps
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
                "broker": "jupiter_swap_v1",
                "rpc": self.rpc_url,
                "jupiter_api": self.jupiter_base,
                "wallet_configured": self._private_key is not None,
                "wallet_address": self._pubkey,
                "slippage_bps": self.slippage_bps,
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

    def sol_balance(self) -> float:
        """Return SOL balance in lamports (as float SOL)."""
        with self._lock:
            if not self._pubkey:
                return 0.0
        result = self._rpc("getBalance", [self._pubkey, {"commitment": "confirmed"}])
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

    def _jup_get(self, path: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{self.jupiter_base}{path}?{query}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json", "User-Agent": USER_AGENT,
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read(2_000_000))

    def _jup_post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.jupiter_base}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read(2_000_000))

    def quote(self, input_mint: str, output_mint: str, amount: int,
              slippage_bps: Optional[int] = None, restrict_intermediate_tokens: bool = True) -> dict:
        """Get a swap quote from Jupiter Swap V1. `amount` is in input token raw units."""
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps if slippage_bps is not None else int(self.slippage_bps)),
        }
        if restrict_intermediate_tokens:
            params["restrictIntermediateTokens"] = "true"
        return self._jup_get("/quote", params)

    def build_swap_tx(self, quote_response: dict, user_pubkey: str) -> dict:
        """Build the swap transaction from a quote response (Jupiter /swap endpoint)."""
        body = {
            "quoteResponse": quote_response,
            "userPublicKey": user_pubkey,
            "wrapUnwrap": False,
            "computeUnitPriceMicroLamports": DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS,
        }
        return self._jup_post("/swap", body)

    def sign_and_send(self, swap_response: dict, private_key: bytes) -> dict:
        """Sign and submit the swap transaction.

        Handles both legacy and versioned Solana transactions.
        """
        swap_tx = swap_response.get("swapTransaction")
        if not swap_tx:
            return {"ok": False, "error": "No swapTransaction in swap response"}

        # Jupiter Swap V1 returns the transaction via /swap endpoint
        # ready for signing. Handle both legacy and versioned transactions.
        decoded = base64.b64decode(swap_tx)
        idx = 0

        # Check for versioned transaction (first byte has high bit set)
        version_prefix = None
        if decoded[0] & 0x80:
            version_prefix = decoded[0]
            idx = 1

        # Parse compact-u16 for signature count
        sig_count = 0
        for shift in range(0, 16, 7):
            if idx >= len(decoded):
                return {"ok": False, "error": "Truncated signature count"}
            b = decoded[idx]
            idx += 1
            sig_count |= (b & 0x7F) << shift
            if not (b & 0x80):
                break

        sig_offset = idx
        msg_start = idx + sig_count * 64  # each signature is 64 bytes
        message_bytes = decoded[msg_start:]

        signing_key = nacl.signing.SigningKey(private_key)
        msg_hash = hashlib.sha256(message_bytes).digest()
        signed = signing_key.sign(msg_hash)
        signature = bytes(signed.signature)[:64]

        # Rebuild the transaction with the signature
        signed_tx = bytearray()
        if version_prefix is not None:
            signed_tx.append(version_prefix)
        # Re-encode sig_count as compact-u16
        sc = sig_count
        while True:
            b = sc & 0x7F
            sc >>= 7
            if sc:
                signed_tx.append(b | 0x80)
            else:
                signed_tx.append(b)
                break
        # Write signatures
        for i in range(sig_count):
            if i == 0:
                signed_tx.extend(signature)  # our signature
            else:
                start = sig_offset + i * 64
                signed_tx.extend(decoded[start:start + 64])
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
        """Convenience: get a SOL to token swap quote and build the swap tx."""
        with self._lock:
            if not self._pubkey:
                return {"ok": False, "error": "Wallet not configured"}
        lamports = int(sol_amount * 1_000_000_000)
        quote = self.quote(WRAPPED_SOL_MINT, output_mint, lamports)
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

    orig_get = handler_cls.do_GET
    orig_post = handler_cls.do_POST

    def do_GET(self):
        import urllib.parse
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/jupiter/status":
            self.send_json({"jupiter": jupiter.status(), "risk": risk.status()})
            return
        if path == "/api/jupiter/balance":
            if not jupiter.configured:
                self.send_json({"configured": False, "error": "No wallet key"}, 400)
                return
            self.send_json({"sol_balance": jupiter.sol_balance(), "wallet": jupiter._pubkey})
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