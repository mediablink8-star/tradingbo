"""Ember Forex Trading Lab HTTP application."""
import argparse
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

ROOT = Path(__file__).resolve().parent
LAB = ForexLab(ROOT / "lab.sqlite")
AGENTS = ForexAgentRuntime(
    ROOT / "lab.sqlite", LAB,
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


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        raw = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/forex":
            self.send_json(LAB.tick())
            return
        if path == "/api/forex/agents":
            state = AGENTS.status()
            state["account"] = LAB.status().get("account", {})
            state["runtime_available"] = True
            self.send_json(state)
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
            state = AGENTS.status()
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
        """Credential routes require a loopback peer and a matching Host."""
        host = self.headers.get("Host", "")
        peer = self.client_address[0] if self.client_address else ""
        if peer not in ("127.0.0.1", "::1"):
            return "Connections are accepted from this machine only."
        name = host.split(":")[0]
        if name not in ("127.0.0.1", "localhost", "[::1]"):
            return "Unexpected Host header."
        return None

    def do_POST(self):
        if self.path.startswith("/api/connections/"):
            bad = self._local_request()
            if bad:
                self.send_json({"error": bad}, 403)
                return
            self._handle_connection(self.path)
            return
        if self.path not in (
            "/api/forex/open", "/api/forex/close", "/api/forex/agents/run"
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
            if self.path == "/api/forex/open":
                result = LAB.open(data.get("pair"), data.get("side"), float(data.get("notional")))
            elif self.path == "/api/forex/close":
                result = LAB.close(data.get("id"))
            else:
                result = AGENTS.run_cycle()
            self.send_json(result)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

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
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
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
    print(f"Ember Forex Trading Lab: http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
