"""Install /api/live/* routes onto the existing Handler class."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def install(handler_cls: type, g: dict) -> Any:
    """Monkey-patch Handler with live risk endpoints. Returns the engine."""
    from live_risk import LiveRiskEngine

    data_dir = g.get("DATA_DIR") or Path(os.environ.get("TRADINGLAB_DATA_DIR", "."))
    data_dir = Path(data_dir)
    engine = LiveRiskEngine(data_dir / "live-risk.sqlite")
    g["LIVE_RISK"] = engine

    orig_get = handler_cls.do_GET
    orig_post = handler_cls.do_POST

    def do_GET(self):
        import urllib.parse

        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/live/status":
            self.send_json(engine.status())
            return
        if path in ("/", "/index.html") or path.endswith("/index.html"):
            pass
        return orig_get(self)

    def do_POST(self):
        import urllib.parse

        path = urllib.parse.urlsplit(self.path).path
        if path not in (
            "/api/live/arm",
            "/api/live/disarm",
            "/api/live/gate",
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

        if path == "/api/live/arm":
            result = engine.arm(actor=str(data.get("actor") or "operator")[:80])
            self.send_json({"ok": True, **result})
            return
        if path == "/api/live/disarm":
            result = engine.disarm(
                actor=str(data.get("actor") or "operator")[:80],
                reason=str(data.get("reason") or "manual")[:120],
            )
            self.send_json({"ok": True, **result})
            return
        if path == "/api/live/gate":
            result = engine.can_open(
                notional_usd=float(data.get("notional_usd") or 0),
                open_positions=int(data.get("open_positions") or 0),
                current_exposure_usd=float(data.get("current_exposure_usd") or 0),
            )
            self.send_json(result)
            return

    handler_cls.do_GET = do_GET
    handler_cls.do_POST = do_POST
    return engine
