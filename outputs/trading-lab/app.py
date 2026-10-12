"""Ember Forex Trading Lab HTTP application — launcher.

Restores full app from split body parts (avoids large single-blob push limits).
"""
from pathlib import Path
_root = Path(__file__).resolve().parent
_parts = [
    (_root / "_app_body_p1.py").read_text(encoding="utf-8"),
    (_root / "_app_body_p2.py").read_text(encoding="utf-8"),
]
_code = "".join(_parts)
exec(compile(_code, str(_root / "app.py"), "exec"), globals())
