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

from forex_lab import ForexLab
from forex_agents import ForexAgentRuntime

ROOT = Path(__file__).resolve().parent
LAB = ForexLab(ROOT / "lab.sqlite")
AGENTS = ForexAgentRuntime(
    ROOT / "lab.sqlite", LAB,
    auto_run=os.environ.get("EMBER_FOREX_AUTORUN", "").strip() == "1",
)


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

    def do_POST(self):
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
