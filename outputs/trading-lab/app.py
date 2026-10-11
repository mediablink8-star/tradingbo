"""Ember Forex Trading Lab HTTP application."""
import argparse
import base64
import hmac
import json
import mimetypes
import os
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import forex_market
from forex_lab import ForexLab
from forex_agents import ForexAgentRuntime
from key_store import KeyStore, PROVIDER_SPECS
from llm_research import ResearchLayer, ModelError, verify_connection
from meme_research import MemeCoinResearchEngine
from meme_safety import SolanaMintSafetyChecker
from meme_paper import MemePaperTracker
from meme_paper_trader import MemePaperTrader

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TRADINGLAB_DATA_DIR", str(ROOT))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_REQUIRED = os.environ.get("TRADINGLAB_AUTH_REQUIRED", "").strip() == "1"
AUTH_USERNAME = os.environ.get("TRADINGLAB_USERNAME", "")
AUTH_PASSWORD = os.environ.get("TRADINGLAB_PASSWORD", "")
LAB = ForexLab(DATA_DIR / "lab.sqlite")
AGENTS = ForexAgentRuntime(
    DATA_DIR / "lab.sqlite", LAB,
    auto_run=os.environ.get("EMBER_FOREX_AUTORUN", "").strip() == "1",
)
# The AI layer is advisory: it writes recorded commentary only. Entry, sizing,
# stops and the loss breaker remain deterministic inside the runtime.
AGENTS.attach_research(None)
KEYS = KeyStore(
    max_calls=int(os.environ.get("FX_MAX_MODEL_CALLS", "40")),
    max_spend=float(os.environ.get("FX_MAX_MODEL_SPEND", "5.0")),
    cost_per_call=float(os.environ.get("FX_MODEL_COST", "0.002")),
)
RESEARCH = ResearchLayer(KEYS)
AGENTS.attach_research(RESEARCH)
MEME_RESEARCH = MemeCoinResearchEngine()
MEME_SAFETY = SolanaMintSafetyChecker()
MEME_PAPER = MemePaperTracker(
    DATA_DIR / "meme-paper.sqlite",
    slippage_bps=float(os.environ.get("MEME_PAPER_SLIPPAGE_BPS", "50")),
    fee_bps=float(os.environ.get("MEME_PAPER_FEE_BPS", "30")),
)
MEME_TRADER = MemePaperTrader(
    DATA_DIR / "meme-trader.sqlite",
    position_usd=float(os.environ.get("MEME_PAPER_POSITION_USD", "50")),
    max_positions=int(os.environ.get("MEME_PAPER_MAX_POSITIONS", "3")),
    daily_loss_limit=float(os.environ.get("MEME_PAPER_DAILY_LOSS_LIMIT_USD", "50")),
    fee_bps=float(os.environ.get("MEME_PAPER_FEE_BPS", "30")),
    slippage_bps=float(os.environ.get("MEME_PAPER_SLIPPAGE_BPS", "50")),
    min_liquidity_usd=float(os.environ.get("MEME_PAPER_MIN_LIQUIDITY_USD", "10000")),
    min_volume_24h_usd=float(os.environ.get("MEME_PAPER_MIN_VOLUME_24H_USD", "25000")),
)


def meme_current_price(token_address):
    """Fetch a fresh public DEX quote; never treat missing data as zero."""
    safe = urllib.parse.quote(str(token_address or ""), safe="")
    if not safe:
        return None
    pairs = MEME_RESEARCH.fetch_json(
        f"https://api.dexscreener.com/token-pairs/v1/solana/{safe}"
    )
    if not isinstance(pairs, list):
        return None
    matching = [
        pair for pair in pairs
        if isinstance(pair, dict)
        and str(pair.get("chainId") or "").lower() == "solana"
        and str((pair.get("baseToken") or {}).get("address") or "").lower()
        == str(token_address).lower()
    ]
    if not matching:
        return None
    def liquidity(pair):
        try:
            value = float((pair.get("liquidity") or {}).get("usd") or 0)
            return value if value > 0 and value < float("inf") else 0
        except (TypeError, ValueError, OverflowError):
            return 0
    best = max(matching, key=liquidity)
    try:
        price = float(best.get("priceUsd"))
        return price if price > 0 and price < float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


def run_meme_paper_cycle(limit=20):
    """Discover, safety-screen, paper-trade and persist one complete cycle."""
    scan = MEME_RESEARCH.run(limit)
    all_candidates = scan.get("candidates", [])
    # Record trader-cycle candidates for forward evaluation as well as research scans.
    # The tracker accepts only WATCH candidates with valid observed prices.
    paper_tracking = MEME_PAPER.record_scan(all_candidates)
    watchlist = sorted(
        (candidate for candidate in all_candidates
         if candidate.get("decision") == "WATCH"),
        key=lambda candidate: float(candidate.get("score") or 0),
        reverse=True,
    )
    # Keep the number of expensive on-chain checks bounded per manual cycle.
    candidates = watchlist[:5]
    market_rejection_counts = {}
    for candidate in all_candidates:
        for reason in candidate.get("rejection_reasons", []):
            market_rejection_counts[reason] = market_rejection_counts.get(reason, 0) + 1
    decisions = MEME_TRADER.run_cycle(
        candidates, MEME_SAFETY.check, meme_current_price
    )
    decision_counts = {}
    for decision in decisions.get("decisions", []):
        key = decision.get("reason") or decision.get("action", "unknown").lower()
        decision_counts[key] = decision_counts.get(key, 0) + 1
    return {
        "scan": {
            "generated_at": scan.get("generated_at"),
            "discovered_tokens": scan.get("discovered_tokens", 0),
            "scored_candidates": scan.get("scored_candidates", 0),
            "watchlist_count": scan.get("watchlist_count", 0),
            "watchlist_considered": len(candidates),
            "market_rejected_count": sum(
                1 for candidate in all_candidates if candidate.get("decision") != "WATCH"
            ),
            "market_rejection_reasons": market_rejection_counts,
            "market_rejection_examples": [
                {
                    "name": candidate.get("name", "Unknown"),
                    "symbol": candidate.get("symbol", "UNKNOWN"),
                    "liquidity_usd": candidate.get("liquidity_usd"),
                    "volume_24h_usd": candidate.get("volume_24h_usd"),
                    "price_change_1h_pct": candidate.get("price_change_1h_pct"),
                    "rejection_reasons": candidate.get("rejection_reasons", []),
                }
                for candidate in all_candidates
                if candidate.get("decision") != "WATCH"
            ][:3],
            "errors": scan.get("errors", []),
        },
        "cycle": {**decisions, "decision_counts": decision_counts},
        "status": MEME_TRADER.status(),
        "paper_tracking": paper_tracking,
        "paper_outcome_update": MEME_PAPER.update_due(),
        "paper_status": MEME_PAPER.status(),
        "execution_enabled": False,
    }


class Handler(BaseHTTPRequestHandler):
    def _require_auth(self):
        if not AUTH_REQUIRED:
            return True
        header = self.headers.get("Authorization", "")
        supplied = ""
        if header.startswith("Basic "):
            try:
                supplied = base64.b64decode(header[6:], validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                supplied = ""
        expected = f"{AUTH_USERNAME}:{AUTH_PASSWORD}"
        if AUTH_USERNAME and AUTH_PASSWORD and hmac.compare_digest(supplied, expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Tradingbo", charset="UTF-8"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b'{"error":"authentication required"}')
        return False

    def send_json(self, data, status=200):
        raw = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            self.send_json({"status": "ok"})
            return
        # Let the static dashboard load so it can present an in-page login.
        # All API data and state-changing requests remain authenticated.
        if path.startswith("/api/") and not self._require_auth():
            return
        if path == "/api/forex":
            self.send_json(LAB.tick())
            return
        if path == "/api/forex/agents":
            state = AGENTS.status()
            state["account"] = LAB.status().get("account", {})
            state["runtime_available"] = True
            self.send_json(state)
            return
        if path == "/api/meme/research":
            self.send_json(MEME_RESEARCH.last_result or {
                "available": True,
                "mode": "research_only",
                "chain": "solana",
                "last_run": None,
                "execution_enabled": False,
                "note": "POST /api/meme/research/run to discover and screen candidates.",
            })
            return
        if path == "/api/meme/paper":
            self.send_json(MEME_PAPER.status())
            return
        if path == "/api/meme/trader":
            self.send_json(MEME_TRADER.status())
            return
        if path == "/api/connections/model":
            self.send_json({**KEYS.status(),
                            "providers": {
                                name: {"label": spec["label"],
                                       "base_url": spec["base_url"],
                                       "needs_key": spec["needs_key"],
                                       "default_model": spec["default_model"]}
                                for name, spec in PROVIDER_SPECS.items()}})
            return
        if path == "/api/connections/research":
            self.send_json({
                "available": RESEARCH.available(),
                "model": KEYS.model,
                "budget": KEYS.budget_remaining(),
                "last": RESEARCH.last_result,
                "note": "Advisory only. These reports never place or size an order.",
            })
            return
        if path == "/api/forex/bars":
            query = urllib.parse.parse_qs(
                urllib.parse.urlsplit(self.path).query
            )
            pair = (query.get("pair") or ["EUR/USD"])[0].upper()
            interval = (query.get("interval") or ["15m"])[0]
            try:
                limit = int((query.get("limit") or ["400"])[0])
            except ValueError:
                limit = 400
            if "/" not in pair:
                self.send_json({"error": "invalid pair"}, 400)
                return
            if interval not in forex_market.YAHOO_INTERVALS:
                self.send_json(
                    {"error": "unsupported interval"}, 400
                )
                return
            try:
                self.send_json(forex_market.yahoo_bars(
                    pair, interval, max(1, min(limit, 1500))
                ))
            except Exception as exc:
                self.send_json({"error": str(exc)}, 502)
            return
        # Serve dashboard files safely, including the immersive office.
        try:
            relative = urllib.parse.unquote(path).lstrip("/") or "index.html"
            target = (ROOT / relative).resolve()
            target.relative_to(ROOT.resolve())
        except (ValueError, OSError):
            self.send_json({"error": "not found"}, 404)
            return
        if not target.is_file() or target.suffix.lower() not in {
            ".html", ".css", ".js", ".svg", ".png", ".jpg", ".webp", ".ico"
        }:
            self.send_json({"error": "not found"}, 404)
            return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "image/svg+xml"):
            mime += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def _local_request(self):
        """Local-only in desktop mode; hosted mode is protected by HTTP Basic Auth."""
        if AUTH_REQUIRED:
            return None
        host = self.headers.get("Host", "")
        peer = self.client_address[0] if self.client_address else ""
        if peer not in ("127.0.0.1", "::1"):
            return "Connections are accepted from this machine only."
        name = host.split(":")[0]
        if name not in ("127.0.0.1", "localhost", "[::1]"):
            return "Unexpected Host header."
        return None

    def do_POST(self):
        if not self._require_auth():
            return
        if self.path.startswith("/api/connections/"):
            bad = self._local_request()
            if bad:
                self.send_json({"error": bad}, 403)
                return
            self._handle_connection(self.path)
            return
        if self.path not in (
            "/api/forex/open", "/api/forex/close", "/api/forex/agents/run",
            "/api/forex/agents/config",
            "/api/meme/research/run", "/api/meme/security/check",
            "/api/meme/paper/update", "/api/meme/trader/run", "/api/meme/trader/tick",
        ):
            self.send_json({"error": "not found"}, 404)
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.send_json({"error": "JSON required"}, 400)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 1 <= n <= 10000:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(n))
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            if self.path == "/api/forex/open":
                result = LAB.open(data.get("pair"), data.get("side"), float(data.get("notional")))
            elif self.path == "/api/forex/close":
                result = LAB.close(data.get("id"))
            elif self.path == "/api/forex/agents/config":
                result = {"ok": True,
                          "agent_config": AGENTS.set_config(
                              data.get("agent"), data.get("enabled"))}
            elif self.path == "/api/meme/research/run":
                result = MEME_RESEARCH.run(data.get("limit", 20))
                result["paper_tracking"] = MEME_PAPER.record_scan(result.get("candidates", []))
                result["paper_outcome_update"] = MEME_PAPER.update_due()
                result["paper_status"] = MEME_PAPER.status()
            elif self.path == "/api/meme/paper/update":
                result = MEME_PAPER.update_due()
                result["status"] = MEME_PAPER.status()
            elif self.path == "/api/meme/trader/run":
                result = run_meme_paper_cycle(data.get("limit", 20))
            elif self.path == "/api/meme/trader/tick":
                result = MEME_TRADER.tick(meme_current_price)
                result["status"] = MEME_TRADER.status()
            elif self.path == "/api/meme/security/check":
                result = MEME_SAFETY.check(data.get("mint_address"))
            else:
                result = AGENTS.run_cycle()
            self.send_json(result)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 502 if self.path in ("/api/meme/research/run", "/api/meme/security/check", "/api/meme/paper/update", "/api/meme/trader/run", "/api/meme/trader/tick") else 400)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if not 1 <= n <= 10000:
            raise ValueError("Invalid request size")
        return json.loads(self.rfile.read(n))

    def _handle_connection(self, path):
        try:
            if path == "/api/connections/model":
                data = self._read_json()
                status = KEYS.store(data.get("key"), data.get("model"),
                                    data.get("provider"), data.get("base_url"))
                if data.get("json_mode") is not None:
                    KEYS.set_json_mode(data["json_mode"])
                # The entered secret is never echoed back to the browser.
                status = KEYS.status()
                self.send_json(status)
                return
            if path == "/api/connections/model/forget":
                self._read_json()
                self.send_json(KEYS.forget())
                return
            if path == "/api/connections/model/verify":
                self._read_json()
                self.send_json(verify_connection(KEYS))
                return
            if path == "/api/connections/research/run":
                self._read_json()
                self.send_json(AGENTS.run_research())
                return
            self.send_json({"error": "not found"}, 404)
        except ModelError as exc:
            self.send_json({"error": str(exc)}, 502)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()
    if AUTH_REQUIRED and (not AUTH_USERNAME or not AUTH_PASSWORD):
        raise SystemExit("Hosted mode requires TRADINGLAB_USERNAME and TRADINGLAB_PASSWORD.")
    if AUTH_REQUIRED and len(AUTH_PASSWORD) < 16:
        raise SystemExit("TRADINGLAB_PASSWORD must be at least 16 characters.")
    if AGENTS.auto_run:
        def agent_loop():
            while True:
                try:
                    AGENTS.run_cycle()
                except Exception as exc:
                    print(f"Forex agent cycle failed: {exc}", flush=True)
                time.sleep(AGENTS.interval)
        threading.Thread(target=agent_loop, name="forex-paper-agents", daemon=True).start()
        print(f"Forex paper-agent auto-run enabled (every {AGENTS.interval:.0f}s)", flush=True)
    else:
        print("Forex paper-agent auto-run disabled; use the office Run agent cycle control.", flush=True)
    if os.environ.get("MEME_PAPER_AUTORUN", "").strip() == "1":
        def meme_paper_loop():
            while True:
                try:
                    result = run_meme_paper_cycle()
                    print(
                        "Meme paper cycle: "
                        f"{result['scan']['scored_candidates']} scored, "
                        f"{len(result['cycle'].get('decisions', []))} decisions",
                        flush=True,
                    )
                except Exception as exc:
                    print(f"Meme paper cycle failed: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(max(60, int(os.environ.get("MEME_PAPER_INTERVAL_SECONDS", "300"))))
        threading.Thread(target=meme_paper_loop, name="meme-paper-trader", daemon=True).start()
        print("Solana meme paper-trading auto-run enabled (default 300s interval)", flush=True)
    else:
        print("Solana meme paper-trading auto-run disabled; use Run paper cycle in dashboard.", flush=True)
    print(f"Ember Forex Trading Lab listening on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
