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

    # Opt-in FX paper worker. Entries still pass through the deterministic
    # quote-freshness and risk gates in ForexAgentRuntime; no live broker exists.
    fx_agent = g.get("AGENTS")
    fx_worker_lock = threading.RLock()
    fx_worker_stop = threading.Event()
    fx_worker_thread = None
    fx_worker_interval = max(15, int(getattr(fx_agent, "interval", 60)))
    fx_worker_state = {
        "running": False, "stopping": False, "started_at": None,
        "last_cycle_at": None, "last_cycle_id": None, "last_error": None,
        "cycles": 0,
    }

    def fx_worker_status():
        with fx_worker_lock:
            return {
                **fx_worker_state,
                "interval_seconds": fx_worker_interval,
                "mode": "forex_paper",
                "execution_enabled": False,
            }

    def fx_worker_loop():
        while not fx_worker_stop.is_set():
            try:
                result = fx_agent.run_cycle()
                with fx_worker_lock:
                    fx_worker_state.update({
                        "last_cycle_at": time.time(),
                        "last_cycle_id": result.get("cycle_id"),
                        "last_error": None,
                        "cycles": fx_worker_state["cycles"] + 1,
                    })
            except Exception as exc:
                with fx_worker_lock:
                    fx_worker_state["last_cycle_at"] = time.time()
                    fx_worker_state["last_error"] = (
                        type(exc).__name__ + ": " + str(exc)
                    )[:300]
            fx_worker_stop.wait(fx_worker_interval)
        with fx_worker_lock:
            fx_worker_state["running"] = False
            fx_worker_state["stopping"] = False
            if fx_agent is not None:
                fx_agent.auto_run = False

    def start_fx_worker():
        nonlocal fx_worker_thread
        if fx_agent is None or not callable(getattr(fx_agent, "run_cycle", None)):
            return {"ok": False, "error": "Forex paper agent is unavailable"}
        with fx_worker_lock:
            if fx_worker_thread and fx_worker_thread.is_alive():
                if fx_worker_stop.is_set():
                    return {"ok": False, "error": "The current cycle is finishing; retry after it stops"}
                return {"ok": True, **fx_worker_status()}
            fx_worker_stop.clear()
            fx_agent.auto_run = True
            fx_worker_state.update({
                "running": True, "stopping": False,
                "started_at": time.time(), "last_error": None,
            })
            fx_worker_thread = threading.Thread(
                target=fx_worker_loop, name="forex-paper-agent", daemon=True
            )
            fx_worker_thread.start()
        return {"ok": True, **fx_worker_status()}

    def stop_fx_worker():
        fx_worker_stop.set()
        with fx_worker_lock:
            if fx_agent is not None:
                fx_agent.auto_run = False
            fx_worker_state["stopping"] = bool(
                fx_worker_thread and fx_worker_thread.is_alive()
            )
            if not fx_worker_state["stopping"]:
                fx_worker_state["running"] = False
        return {"ok": True, **fx_worker_status()}

    orig_get = handler_cls.do_GET
    orig_post = handler_cls.do_POST

    def do_GET(self):
        import urllib.parse

        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/forex/auto":
            self.send_json(fx_worker_status())
            return
        if path == "/api/live/status":
            self.send_json(engine.status())
            return
        if path in ("/", "/index.html") or path.endswith("/index.html"):
            pass
        return orig_get(self)

    def do_POST(self):
        import urllib.parse

        path = urllib.parse.urlsplit(self.path).path
        if path in ("/api/forex/auto/start", "/api/forex/auto/stop"):
            if hasattr(self, "_require_auth") and not self._require_auth():
                return
            result = start_fx_worker() if path.endswith("/start") else stop_fx_worker()
            self.send_json(result, 200 if result.get("ok") else 503)
            return
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
