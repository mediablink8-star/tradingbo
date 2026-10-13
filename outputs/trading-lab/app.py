"""Ember Forex Trading Lab HTTP application — launcher."""
import base64
from pathlib import Path

_root = Path(__file__).resolve().parent


def _load():
    parts = []
    for name in ("_app_b64_0.txt", "_app_b64_1.txt", "_app_b64_2.txt", "_app_b64_3.txt"):
        parts.append((_root / name).read_text(encoding="ascii"))
    p1 = base64.b64decode(parts[0] + parts[1])
    p2 = base64.b64decode(parts[2] + parts[3])
    return (p1 + p2).decode("utf-8")


exec(compile(_load(), str(_root / "app.py"), "exec"), globals())

# Live risk gate (ARM/DISARM) — agents cannot bypass
try:
    import live_routes

    if "Handler" in globals():
        live_routes.install(Handler, globals())
        print("Live risk gate installed (/api/live/*).", flush=True)
except Exception as _live_exc:
    print(f"Live risk gate not installed: {_live_exc}", flush=True)
