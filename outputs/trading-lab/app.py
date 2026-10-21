"""Ember Forex Trading Lab HTTP application — launcher."""
import argparse
import base64
import os
import threading
import time
import zlib
from pathlib import Path

_root = Path(__file__).resolve().parent


def _load() -> str:
    # Primary: zlib body across zb_0..5 (small chunks survive git push)
    zparts = []
    for i in range(6):
        p = _root / f"zb_{i}.txt"
        if not p.exists() or p.stat().st_size < 10:
            zparts = []
            break
        zparts.append(p.read_text(encoding="ascii").strip())
    if len(zparts) == 6:
        return zlib.decompress(base64.b64decode("".join(zparts))).decode("utf-8")

    # Secondary: zbody_0..2
    zparts = []
    for name in ("zbody_0.txt", "zbody_1.txt", "zbody_2.txt"):
        p = _root / name
        if not p.exists() or p.stat().st_size < 10:
            zparts = []
            break
        zparts.append(p.read_text(encoding="ascii").strip())
    if len(zparts) == 3:
        return zlib.decompress(base64.b64decode("".join(zparts))).decode("utf-8")

    # Legacy base64 halves
    parts = []
    for name in ("_app_b64_0.txt", "_app_b64_1.txt", "_app_b64_2.txt", "_app_b64_3.txt"):
        text = (_root / name).read_text(encoding="ascii").strip()
        if not text:
            raise RuntimeError(f"empty app body part: {name}")
        parts.append(text)
    p1 = base64.b64decode(parts[0] + parts[1])
    p2 = base64.b64decode(parts[2] + parts[3])
    return (p1 + p2).decode("utf-8")


_src = _load()

# Keep read-only Forex status available for dashboard bootstrap; all mutations
# and all legacy crypto paths remain authenticated and are blocked by live_routes.
_auth_guard_old = (
    "        # Let the static dashboard load so it can present an in-page login.\n"
    "        # All API data and state-changing requests remain authenticated.\n"
    "        if path.startswith(\"/api/\") and not self._require_auth():"
)
_auth_guard_new = (
    "        # Read-only Forex status is public; mutation routes remain authenticated.\n"
    "        public_dashboard_gets = {\"/api/forex\", \"/api/forex/agents\", \"/api/forex/bars\", \"/api/forex/auto\"}\n"
    "        if path.startswith(\"/api/\") and path not in public_dashboard_gets and not self._require_auth():"
)
if _auth_guard_old in _src:
    _src = _src.replace(_auth_guard_old, _auth_guard_new, 1)

# Strip the `if __name__ == "__main__"` block so we can install route
# extensions before starting the server.
_main_marker = "\nif __name__ == \"__main__\""
_cut = _src.rfind(_main_marker)
if _cut >= 0:
    _src = _src[:_cut]

exec(compile(_src, str(_root / "app.py"), "exec"), globals())

try:
    import live_routes

    if "Handler" in globals():
        live_routes.install(Handler, globals())
        print("Live risk gate installed (/api/live/*).", flush=True)
except Exception as _live_exc:
    print(f"Live risk gate not installed: {_live_exc}", flush=True)

# Legacy Solana/Jupiter workers and routes are not installed.

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ember Forex Trading Lab")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    args = parser.parse_args()

    if AUTH_REQUIRED and (not AUTH_USERNAME or not AUTH_PASSWORD):
        raise SystemExit("Hosted mode requires TRADINGLAB_USERNAME and TRADINGLAB_PASSWORD.")
    if AUTH_REQUIRED and len(AUTH_PASSWORD) < 16:
        raise SystemExit("TRADINGLAB_PASSWORD must be at least 16 characters.")

    if AGENTS.auto_run:
        def _agent_loop():
            while True:
                try:
                    AGENTS.agent_cycle()
                except Exception as exc:
                    print(f"[agent_loop] {exc}", flush=True)
                time.sleep(int(os.environ.get("AGENT_CYCLE_INTERVAL", "300")))

        threading.Thread(target=_agent_loop, daemon=True).start()
        print("Forex paper-agent auto-run enabled.", flush=True)
    else:
        print("Forex autonomous proposals are disabled; run research from the dashboard.", flush=True)

    print("Legacy crypto paper workers are disabled in the Forex-only product.", flush=True)

    print(f"Ember Forex Trading Lab listening on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
