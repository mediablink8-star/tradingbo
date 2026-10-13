"""Ember Forex Trading Lab HTTP application — launcher."""
import base64
import zlib
from pathlib import Path

_root = Path(__file__).resolve().parent


def _load():
    # Prefer zlib-compressed single-source body (reliable restore path)
    zparts = []
    for name in ("_app_zlib_0.txt", "_app_zlib_1.txt", "_app_zlib_2.txt"):
        p = _root / name
        if p.exists():
            zparts.append(p.read_text(encoding="ascii"))
    if len(zparts) == 3:
        return zlib.decompress(base64.b64decode("".join(zparts))).decode("utf-8")
    # Fallback: legacy 4-part base64 body
    parts = []
    for name in ("_app_b64_0.txt", "_app_b64_1.txt", "_app_b64_2.txt", "_app_b64_3.txt"):
        parts.append((_root / name).read_text(encoding="ascii"))
    p1 = base64.b64decode(parts[0] + parts[1])
    p2 = base64.b64decode(parts[2] + parts[3])
    return (p1 + p2).decode("utf-8")


_src = _load()
# Repair broken loadMemeTrader injection (missing } before catch)
_src = _src.replace(
    "\"    renderMemeTrader(await api('/api/meme/trader'));\",\n                        1,",
    "\"    renderMemeTrader(await api('/api/meme/trader'));}\",\n                        1,",
    1,
)
_src = _src.replace(
    "renderMemeTrader(await api('/api/meme/trader'));\n  catch(e)",
    "renderMemeTrader(await api('/api/meme/trader'));}\n  catch(e)",
)

exec(compile(_src, str(_root / "app.py"), "exec"), globals())

try:
    import live_routes
    if "Handler" in globals():
        live_routes.install(Handler, globals())
        print("Live risk gate installed (/api/live/*).", flush=True)
except Exception as _live_exc:
    print(f"Live risk gate not installed: {_live_exc}", flush=True)
