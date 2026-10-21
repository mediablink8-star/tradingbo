"""Loopback-only HTTP shell for the fail-closed executor control ledger.

There is deliberately no IBKR connection, arm endpoint, order endpoint, or
remote binding. This process is a durable local control foundation only.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from local_executor_control import CommandRejected, LocalExecutorControl


def build_server(host: str | None = None, port: int | None = None,
                 *, environ: dict[str, str] | None = None) -> ThreadingHTTPServer:
    env = os.environ if environ is None else environ
    bind_host = host or env.get("TRADINGBO_EXECUTOR_HOST", "127.0.0.1")
    try:
        parsed_host = ipaddress.ip_address(bind_host)
    except ValueError as exc:
        raise ValueError("local executor host must be a loopback IP address") from exc
    if not parsed_host.is_loopback:
        raise ValueError("local executor may bind only to a loopback address")
    token = env.get("TRADINGBO_EXECUTOR_TOKEN", "")
    if len(token.encode("utf-8")) < 32:
        raise ValueError("set TRADINGBO_EXECUTOR_TOKEN to a random secret of at least 32 bytes")
    db_path = env.get("TRADINGBO_EXECUTOR_DB", "./data/local-executor.sqlite3")
    control = LocalExecutorControl(db_path, token)

    class Handler(BaseHTTPRequestHandler):
        server_version = "TradingboLocalExecutor/0.1"

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/healthz":
                self._send(200, {"status": "ok", "live_order_submission": False})
            elif path == "/v1/status":
                self._send(200, control.status())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/v1/commands":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    raise ValueError("request body size is invalid")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = control.apply_command(
                    payload,
                    issued_at=self.headers.get("X-Command-Timestamp", ""),
                    nonce=self.headers.get("X-Command-Nonce", ""),
                    signature=self.headers.get("X-Command-Signature", ""),
                )
                self._send(200, result)
            except CommandRejected as exc:
                message = str(exc)
                code = 409 if "already been used" in message else 401 if "signature" in message else 400
                self._send(code, {"ok": False, "error": message})
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                self._send(400, {"ok": False, "error": str(exc)[:200]})

        def log_message(self, fmt: str, *args) -> None:
            # Avoid logging request targets, which can contain sensitive query data.
            print("[local-executor] request completed", flush=True)

    bind_port = int(port if port is not None else env.get("TRADINGBO_EXECUTOR_PORT", "8766"))
    return ThreadingHTTPServer((bind_host, bind_port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradingbo loopback executor control (no broker orders)")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    server = build_server(args.host, args.port)
    print(f"Local executor control listening on http://{server.server_address[0]}:{server.server_address[1]}", flush=True)
    print("Broker adapter absent; order submission and arming are disabled.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
