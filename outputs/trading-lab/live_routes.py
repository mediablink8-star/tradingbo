"""Install /api/live/* routes onto the existing Handler class."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


def install(handler_cls: type, g: dict) -> Any:
    """Monkey-patch Handler with live risk endpoints. Returns the engine."""
    from live_risk import LiveRiskEngine

    data_dir = g.get("DATA_DIR") or Path(os.environ.get("TRADINGLAB_DATA_DIR", "."))
    data_dir = Path(data_dir)
    engine = LiveRiskEngine(data_dir / "live-risk.sqlite")
    g["LIVE_RISK"] = engine

    # Opt-in six-agent FX paper worker. AI never submits live broker orders;
    # lab.open/close remain the only paper execution calls.
    fx_agent = g.get("AGENTS")
    # The legacy startup loop invokes the deterministic baseline engine, which
    # can open a paper position without reviewing a proposal. Keep it off; the
    # explicit research worker below only records AI proposals.
    if fx_agent is not None:
        fx_agent.auto_run = False
    fx_worker_lock = threading.RLock()
    fx_worker_stop = threading.Event()
    fx_worker_thread = None
    fx_worker_interval = max(60, int(os.environ.get("FX_AI_AUTONOMOUS_INTERVAL", "300")))
    fx_worker_state = {
        "running": False, "stopping": False, "started_at": None,
        "last_cycle_at": None, "last_cycle_id": None, "last_error": None,
        "cycles": 0,
    }

    def fx_worker_status():
        try:
            research = getattr(fx_agent, "research", None)
            ai_available = bool(research and research.available())
        except Exception:
            ai_available = False
        try:
            budget = fx_agent._ai_cycle_budget().get("budget") if fx_agent is not None else None
        except Exception:
            budget = None
        with fx_worker_lock:
            return {
                **fx_worker_state,
                "interval_seconds": fx_worker_interval,
                "mode": "research_proposals_only",
                "execution_enabled": False,
                "ai_available": ai_available,
                "budget": budget,
            }

    def fx_worker_loop():
        while not fx_worker_stop.is_set():
            try:
                budget = fx_agent._ai_cycle_budget()
                if not budget.get("ready"):
                    with fx_worker_lock:
                        fx_worker_state["last_error"] = budget.get("reason", "AI budget unavailable")
                    break
                result = fx_agent.run_ai_cycle()
                gate = result.get("ai_gate") or {}
                final = (result.get("deliberation") or {}).get("final_decision") or {}
                with fx_worker_lock:
                    fx_worker_state.update({
                        "last_cycle_at": time.time(),
                        "last_cycle_id": result.get("cycle_id"),
                        "last_decision": {
                            "side": str(final.get("side") or "hold")[:20],
                            "pair": str(final.get("pair_or_token") or "")[:20],
                            "rationale": str(final.get("rationale") or result.get("reason") or "")[:180],
                            "entry_allowed": False,
                            "proposal_eligible": bool((result.get("proposal") or {}).get("eligible")),
                            "blockers": gate.get("blockers", []),
                        },
                        "last_error": result.get("reason") if not result.get("ok") else None,
                        "cycles": fx_worker_state["cycles"] + 1,
                    })
                budget = fx_agent._ai_cycle_budget()
                if not budget.get("ready"):
                    with fx_worker_lock:
                        fx_worker_state["last_error"] = budget.get("reason", "Daily AI budget exhausted; worker stopped.")
                    fx_worker_stop.set()
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
        if fx_agent is None or not callable(getattr(fx_agent, "run_ai_cycle", None)):
            return {"ok": False, "error": "Forex paper agent is unavailable"}
        research = getattr(fx_agent, "research", None)
        try:
            if research is None or not research.available():
                return {"ok": False, "error": "Connect and verify an AI model before starting autonomous Forex research"}
            budget = fx_agent._ai_cycle_budget()
            if not budget.get("ready"):
                return {"ok": False, "error": budget.get("reason", "AI model budget cannot cover a six-agent cycle")}
        except Exception:
            return {"ok": False, "error": "AI model readiness could not be verified; no worker started"}
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
        if path.startswith(("/api/meme/", "/api/jupiter/")):
            self.send_json({"error": "This Forex-only product does not expose legacy crypto routes."}, 404)
            return
        if path == "/api/forex/bars":
            from instrument_catalog import get_instrument
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            pair = (query.get("pair") or ["EUR/USD"])[0]
            try:
                get_instrument(pair)
            except ValueError as exc:
                self.send_json({"error": str(exc)}, 400)
                return
        if path == "/api/forex/agents/audit":
            if hasattr(self, "_require_auth") and not self._require_auth():
                return
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            cycle_id = (query.get("cycle_id") or [""])[0]
            audit = fx_agent.get_cycle_audit(cycle_id) if fx_agent is not None else None
            self.send_json(audit or {"error": "Forex agent audit was not found."}, 200 if audit else 404)
            return
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
        if path.startswith(("/api/meme/", "/api/jupiter/")):
            if hasattr(self, "_require_auth") and not self._require_auth():
                return
            self.send_json({"error": "This Forex-only product does not expose legacy crypto routes."}, 404)
            return
        if path in ("/api/forex/auto/start", "/api/forex/auto/stop"):
            if hasattr(self, "_require_auth") and not self._require_auth():
                return
            result = start_fx_worker() if path.endswith("/start") else stop_fx_worker()
            self.send_json(result, 200 if result.get("ok") else 503)
            return
        if path in ("/api/forex/agents/run", "/api/forex/agents/ai-cycle", "/api/forex/agents/plan", "/api/forex/agents/approve", "/api/forex/agents/deliberate"):
            if hasattr(self, "_require_auth") and not self._require_auth():
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n < 0 or n > 10000:
                    raise ValueError("Invalid request size")
                data = json.loads((self.rfile.read(n) if n else b"{}").decode("utf-8") or "{}")
                if not isinstance(data, dict):
                    raise ValueError("JSON object required")
                if path == "/api/forex/agents/approve":
                    result = fx_agent.approve_paper_cycle(data.get("cycle_id")) if fx_agent is not None else {"ok": False, "reason": "Forex paper agent is unavailable"}
                else:
                    result = fx_agent.run_ai_proposal(pair=data.get("pair")) if fx_agent is not None else {
                        "ok": False, "reason": "Forex paper agent is unavailable"
                    }
                self.send_json(result, 200 if result.get("ok") else 503)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)[:300]}, 500)
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
