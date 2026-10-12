"""Read-only Solana SPL mint risk checks using standard JSON-RPC.

These checks surface a few observable risk signals. They do not prove that a
token is safe, sellable, or free of coordinated holders, and never execute trades.
"""
import json
import math
import os
import time
import urllib.error
import urllib.request


DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
LEGACY_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
USER_AGENT = "TradingBo-MemeSafety/0.1"
MAX_RPC_RETRIES = 2


def _fetch_json(url, payload, timeout=12):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    for attempt in range(MAX_RPC_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read(1_000_000))
        except urllib.error.HTTPError as exc:
            # Retry only throttling/transient server errors. Never retry permanent
            # client errors, and never turn a failed check into a clean result.
            if attempt >= MAX_RPC_RETRIES or (exc.code != 429 and not 500 <= exc.code < 600):
                raise
            try:
                retry_after = float(exc.headers.get("Retry-After", ""))
            except (TypeError, ValueError, AttributeError):
                retry_after = 0.0
            time.sleep(min(3.0, max(retry_after, 0.5 * (2 ** attempt))))
        except (urllib.error.URLError, TimeoutError):
            if attempt >= MAX_RPC_RETRIES:
                raise
            time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError("solana_rpc_retries_exhausted")


def _error_label(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "http_" + str(exc.code)
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "url_error"
    return type(exc).__name__


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


class SolanaMintSafetyChecker:
    """Inspect mint authority and top token-account concentration proxies."""

    def __init__(self, rpc_url=None, rpc_call=None):
        self.rpc_url = rpc_url or os.environ.get("SOLANA_RPC_URL", DEFAULT_RPC_URL)
        self.rpc_call = rpc_call or _fetch_json
        if not self.rpc_url.startswith("https://"):
            raise ValueError("SOLANA_RPC_URL must use HTTPS")

    def _rpc(self, method, params):
        response = self.rpc_call(self.rpc_url, {
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
        })
        if not isinstance(response, dict):
            raise RuntimeError("invalid_rpc_response")
        if response.get("error"):
            raise RuntimeError("rpc_error")
        if "result" not in response:
            raise RuntimeError("missing_rpc_result")
        return response["result"]

    def check(self, mint_address):
        if not isinstance(mint_address, str) or not mint_address.strip() or len(mint_address) > 64:
            raise ValueError("mint_address must be a non-empty Solana mint address")
        mint_address = mint_address.strip()
        findings = []
        errors = []
        account = None
        supply = None
        largest = None
        try:
            result = self._rpc("getAccountInfo", [
                mint_address, {"encoding": "jsonParsed", "commitment": "confirmed"},
            ])
            account = (result or {}).get("value")
            if not account:
                errors.append("mint_account_not_found")
        except Exception as exc:
            errors.append("mint_account_check_failed:" + _error_label(exc))

        owner_program = account.get("owner") if isinstance(account, dict) else None
        parsed = (((account or {}).get("data") or {}).get("parsed") or {})
        mint_info = parsed.get("info") if isinstance(parsed, dict) else None
        mint_info = mint_info if isinstance(mint_info, dict) else {}
        if owner_program not in (LEGACY_TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            findings.append({"code": "unknown_token_program", "severity": "high",
                             "detail": "Mint owner is not a recognized SPL Token program."})
        if account and not mint_info:
            errors.append("mint_data_not_parsed")
        mint_authority = mint_info.get("mintAuthority")
        freeze_authority = mint_info.get("freezeAuthority")
        if mint_authority:
            findings.append({"code": "mint_authority_active", "severity": "high",
                             "detail": "An authority can still mint additional tokens."})
        if freeze_authority:
            findings.append({"code": "freeze_authority_active", "severity": "high",
                             "detail": "An authority can freeze token accounts."})
        if mint_info and not mint_authority:
            findings.append({"code": "mint_authority_revoked", "severity": "info",
                             "detail": "Parsed mint data reports no mint authority."})
        if mint_info and not freeze_authority:
            findings.append({"code": "freeze_authority_revoked", "severity": "info",
                             "detail": "Parsed mint data reports no freeze authority."})

        try:
            result = self._rpc("getTokenSupply", [
                mint_address, {"commitment": "confirmed"},
            ])
            supply = ((result or {}).get("value") or {})
        except Exception as exc:
            errors.append("supply_check_failed:" + type(exc).__name__)

        try:
            result = self._rpc("getTokenLargestAccounts", [
                mint_address, {"commitment": "confirmed"},
            ])
            largest = (result or {}).get("value")
            if not isinstance(largest, list):
                raise RuntimeError("invalid_largest_accounts")
        except Exception as exc:
            errors.append("largest_accounts_check_failed:" + type(exc).__name__)

        total_raw = _finite_number((supply or {}).get("amount"))
        concentration = None
        if total_raw is not None and total_raw > 0 and isinstance(largest, list):
            raw_amounts = [_finite_number(item.get("amount")) for item in largest
                           if isinstance(item, dict)]
            if raw_amounts and all(value is not None and value >= 0 for value in raw_amounts):
                concentration = round(min(100.0, 100.0 * sum(raw_amounts) / total_raw), 2)
                if concentration >= 80:
                    findings.append({"code": "top_20_accounts_concentrated", "severity": "high",
                                     "detail": "Top 20 token accounts hold at least 80% of reported supply."})
                elif concentration >= 50:
                    findings.append({"code": "top_20_accounts_concentrated", "severity": "medium",
                                     "detail": "Top 20 token accounts hold at least 50% of reported supply."})
        else:
            errors.append("top_account_concentration_unavailable")

        # Any failed core check means the result is incomplete, not safe.
        core_complete = bool(account and mint_info and supply and isinstance(largest, list)
                             and owner_program in (LEGACY_TOKEN_PROGRAM, TOKEN_2022_PROGRAM))
        severity_order = {"high": 3, "medium": 2, "info": 1}
        highest = max((f["severity"] for f in findings), key=lambda s: severity_order[s], default=None)
        return {
            "chain": "solana",
            "mint_address": mint_address,
            "provider": "Solana JSON-RPC",
            "status": "CHECKS_COMPLETE" if core_complete and not errors else "INCOMPLETE",
            "mint_owner_program": owner_program,
            "mint_authority_active": bool(mint_authority) if mint_info else None,
            "freeze_authority_active": bool(freeze_authority) if mint_info else None,
            "supply_raw": (supply or {}).get("amount"),
            "decimals": (supply or {}).get("decimals"),
            "top_20_token_accounts_supply_pct": concentration,
            "top_account_count": len(largest) if isinstance(largest, list) else None,
            "highest_finding_severity": highest,
            "findings": findings,
            "errors": errors,
            "limitations": [
                "Top token accounts are not the same as unique beneficial holders and may include pools or exchange accounts.",
                "This does not test whether a swap can be sold, audit Token-2022 extensions, or identify coordinated wallets.",
                "An incomplete check must not be treated as a clean result.",
                "This endpoint is read-only and cannot sign or submit transactions.",
            ],
            "execution_enabled": False,
        }
