"""Six-agent deliberative paper-trading engine.

Agents talk in sequence. The final decision is still gated by the
deterministic risk engine. No live execution, no wallet, no broker
orders. This module only produces structured paper recommendations.

Supports both Forex and Solana meme / crypto candidates.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

# ── Agent definitions ──────────────────────────────────────────────

AGENT_SPECS = [
    {
        "key": "market",
        "name": "Market Observer",
        "role": (
            "You are the Market Observer. You only describe what is actually "
            "present in the supplied data: prices, freshness, liquidity, volume, "
            "spreads, and data quality. Flag anything stale, missing, or thin. "
            "Never invent numbers or news."
        ),
        "output_keys": ["observation", "data_quality", "concerns"],
    },
    {
        "key": "technical",
        "name": "Technical Analyst",
        "role": (
            "You are the Technical Analyst. From the observed prices and the "
            "Market Observer report, describe short-term structure, momentum, "
            "volatility, and notable levels. Stay strictly inside the data. "
            "Do not claim future prices."
        ),
        "output_keys": ["structure", "momentum_read", "concerns"],
    },
    {
        "key": "macro",
        "name": "Macro / Narrative Analyst",
        "role": (
            "You are the Macro / Narrative Analyst. Form hypotheses about the "
            "current regime (risk-on, risk-off, range, trend) using only the "
            "supplied price data and prior agent reports. Label every inference "
            "as a hypothesis. You have no news feed."
        ),
        "output_keys": ["regime_hypothesis", "narrative", "concerns"],
    },
    {
        "key": "strategy",
        "name": "Strategy Proposer",
        "role": (
            "You are the Strategy Proposer. Using everything so far, propose "
            "1-3 concrete, testable paper-trading hypotheses (long or short). "
            "Each hypothesis must state entry logic, what would falsify it, and "
            "why the data supports trying it. Prefer abstention when evidence "
            "is thin. You cannot execute anything."
        ),
        "output_keys": ["hypotheses", "preferred_action", "concerns"],
    },
    {
        "key": "risk",
        "name": "Risk Critic",
        "role": (
            "You are the independent Risk Critic. Your job is to attack every "
            "proposal. Assume the strategy is wrong until the evidence forces "
            "otherwise. Look for concentration, liquidity, data-quality, and "
            "regime risks. A recommendation to do nothing is often correct. "
            "Be specific and adversarial."
        ),
        "output_keys": ["critique", "veto_reasons", "concerns"],
    },
    {
        "key": "coordinator",
        "name": "Portfolio Coordinator",
        "role": (
            "You are the Portfolio Coordinator. You see the full conversation. "
            "Decide the single best paper action: buy, sell, hold, or reduce. "
            "Respect every prior concern and the deterministic risk limits that "
            "will be applied after you. Prefer hold when uncertainty is high. "
            "Output a clear final recommendation."
        ),
        "output_keys": ["decision", "rationale", "pair_or_token", "side", "size_hint", "concerns"],
    },
]


SYSTEM_PREAMBLE = """You are one specialist in a six-agent paper-trading committee.
You may only reason from the data and prior agent reports supplied in this prompt.
You cannot browse, cannot place real orders, and cannot override risk limits.
Return ONLY a single valid JSON object with the exact keys requested for your role.
Keep every string under 600 characters. Prefer precision over length.
If evidence is weak, say so plainly and favour abstention.
"""


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def build_market_context(
    market: Dict[str, Any],
    account: Dict[str, Any],
    risk: Dict[str, Any],
    history: Dict[str, List],
    positions: List[Dict],
    extra: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Compact, honest context from observed values only."""
    pairs: Dict[str, Any] = {}
    for pair, row in (market.get("pairs") or {}).items():
        if not isinstance(row, dict):
            continue
        price = _safe_float(row.get("price"))
        if price <= 0:
            continue
        observed = _safe_float(row.get("observed"))
        series = [
            _safe_float(p)
            for _, p in (history.get(pair) or [])
            if _safe_float(p) > 0
        ]
        pairs[pair] = {
            "last": price,
            "bid": _safe_float(row.get("bid"), price),
            "ask": _safe_float(row.get("ask"), price),
            "source": str(row.get("source") or "")[:80],
            "quote_age_seconds": round(time.time() - observed, 1) if observed else None,
            "recent_closes": series[-12:],
            "instrument": str(row.get("instrument") or "fx"),
        }

    ctx = {
        "observed_instruments": pairs,
        "account": {
            "equity": _safe_float((account or {}).get("equity")),
            "exposure": _safe_float((account or {}).get("exposure")),
            "realized_pnl": _safe_float((account or {}).get("realized_pnl")),
            "unrealized_pnl": _safe_float((account or {}).get("unrealized_pnl")),
            "daily_halted": bool((account or {}).get("daily_halted")),
            "open_positions": len(positions or []),
        },
        "risk_limits": {
            "max_trade_notional": _safe_float((risk or {}).get("max_trade_notional")),
            "max_exposure": _safe_float((risk or {}).get("max_exposure")),
            "max_positions": (risk or {}).get("max_positions"),
            "max_daily_loss": _safe_float((risk or {}).get("max_daily_loss")),
        },
        "open_positions": [
            {
                "pair": p.get("pair") or p.get("symbol"),
                "side": p.get("side"),
                "notional": _safe_float(p.get("notional")),
                "unrealized_pnl": _safe_float(p.get("unrealized_pnl")),
            }
            for p in (positions or [])
            if isinstance(p, dict)
        ],
        "mode": "paper_only",
        "note": "No live execution is possible. All decisions are simulated.",
    }
    if extra:
        ctx["extra"] = extra
    return ctx


def _parse_json_loose(text: str) -> Dict[str, Any]:
    """Accept clean JSON or recover the first balanced object."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if "\n" in cleaned:
            head = cleaned[:12].strip().lower()
            if head.startswith(("json", "javascript")):
                cleaned = cleaned.split("\n", 1)[-1]
    try:
        val = json.loads(cleaned)
        if isinstance(val, dict):
            return val
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    return item
    except json.JSONDecodeError:
        pass

    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(cleaned):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        val = json.loads(cleaned[start : i + 1])
                        if isinstance(val, dict):
                            return val
                    except json.JSONDecodeError:
                        start = -1
    raise ValueError("no JSON object found in model output")


def _validate_agent_output(raw: Dict[str, Any], expected_keys: List[str]) -> Dict[str, Any]:
    """Keep only expected keys and coerce to safe types."""
    out: Dict[str, Any] = {}
    for key in expected_keys:
        val = raw.get(key)
        if key == "concerns" or key == "veto_reasons" or key == "hypotheses":
            if isinstance(val, list):
                out[key] = [str(x)[:400] for x in val[:8] if x is not None]
            elif isinstance(val, str) and val.strip():
                out[key] = [val.strip()[:400]]
            else:
                out[key] = []
        elif key in ("decision", "side", "preferred_action"):
            out[key] = str(val or "hold").strip().lower()[:40]
        elif key == "size_hint":
            out[key] = _safe_float(val, 0.0)
        else:
            out[key] = str(val or "")[:800]
    if "concerns" not in out:
        out["concerns"] = []
    return out


class MultiAgentEngine:
    """Runs a full six-agent deliberation cycle using the configured LLM."""

    def __init__(self, research_layer, max_rounds: int = 1):
        self.research = research_layer
        self.max_rounds = max(1, min(2, int(max_rounds)))
        self.last_result: Optional[Dict[str, Any]] = None

    def available(self) -> bool:
        layer = self.research
        if layer is None:
            return False
        return bool(getattr(layer, "available", lambda: False)())

    def _call_agent(
        self,
        agent_spec: Dict[str, Any],
        context: Dict[str, Any],
        prior_reports: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        from llm_research import ModelError

        keys = agent_spec["output_keys"]
        prompt = (
            SYSTEM_PREAMBLE
            + "\n\nYour role: "
            + agent_spec["role"]
            + "\n\nReturn ONLY a JSON object with these keys: "
            + ", ".join(f'\"{k}\"' for k in keys)
            + ".\n\nObserved market context (JSON):\n"
            + json.dumps(context, default=str)[:10000]
            + "\n\nPrior agent reports (JSON):\n"
            + json.dumps(prior_reports, default=str)[:8000]
        )

        try:
            raw_obj = self.research._call(prompt, context)
            validated = _validate_agent_output(raw_obj, keys)
            return {
                "agent": agent_spec["name"],
                "key": agent_spec["key"],
                "ok": True,
                "report": validated,
                "advisory": True,
                "affects_execution": False,
            }
        except Exception as exc:
            return {
                "agent": agent_spec["name"],
                "key": agent_spec["key"],
                "ok": False,
                "report": {
                    "concerns": [str(exc)[:300]],
                    "decision": "hold",
                },
                "error": str(exc)[:400],
                "advisory": True,
                "affects_execution": False,
            }

    def deliberate(
        self,
        market: Dict[str, Any],
        account: Dict[str, Any],
        risk: Dict[str, Any],
        history: Dict[str, List],
        positions: List[Dict],
        extra: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        cycle_id = uuid.uuid4().hex[:12]
        started = time.time()
        context = build_market_context(market, account, risk, history, positions, extra)

        if not self.available():
            result = {
                "ok": False,
                "cycle_id": cycle_id,
                "reason": "No usable model configuration. Deterministic pipeline continues unchanged.",
                "agents": [],
                "final_decision": {
                    "decision": "hold",
                    "side": "hold",
                    "pair_or_token": None,
                    "rationale": "AI deliberation unavailable.",
                    "size_hint": 0.0,
                    "concerns": ["Model not configured."],
                },
                "advisory_only": True,
                "execution_enabled": False,
                "duration_seconds": 0.0,
            }
            self.last_result = result
            return result

        reports: List[Dict[str, Any]] = []
        agent_records: List[Dict[str, Any]] = []

        for round_idx in range(self.max_rounds):
            for spec in AGENT_SPECS:
                if round_idx > 0 and spec["key"] not in ("strategy", "risk", "coordinator"):
                    continue
                record = self._call_agent(spec, context, reports)
                agent_records.append(record)
                reports.append(
                    {
                        "agent": record["agent"],
                        "ok": record["ok"],
                        "report": record.get("report", {}),
                    }
                )

        final = {
            "decision": "hold",
            "side": "hold",
            "pair_or_token": None,
            "rationale": "No clear coordinator output.",
            "size_hint": 0.0,
            "concerns": [],
        }
        for rec in reversed(agent_records):
            if rec.get("key") == "coordinator" and rec.get("ok"):
                r = rec["report"]
                final = {
                    "decision": r.get("decision", "hold"),
                    "side": r.get("side") or r.get("decision", "hold"),
                    "pair_or_token": r.get("pair_or_token") or None,
                    "rationale": r.get("rationale", ""),
                    "size_hint": _safe_float(r.get("size_hint")),
                    "concerns": r.get("concerns", []),
                }
                break

        side = str(final.get("side") or "hold").lower()
        if side in ("long", "buy", "enter_long"):
            final["side"] = "buy"
            final["decision"] = "buy"
        elif side in ("short", "sell", "enter_short"):
            final["side"] = "sell"
            final["decision"] = "sell"
        elif side in ("reduce", "close", "exit"):
            final["side"] = "reduce"
            final["decision"] = "reduce"
        else:
            final["side"] = "hold"
            final["decision"] = "hold"

        result = {
            "ok": any(a.get("ok") for a in agent_records),
            "cycle_id": cycle_id,
            "timestamp": started,
            "duration_seconds": round(time.time() - started, 2),
            "agents": agent_records,
            "final_decision": final,
            "advisory_only": True,
            "execution_enabled": False,
            "note": (
                "This deliberation is advisory. The deterministic risk engine "
                "remains the final authority and may still abstain or reject."
            ),
        }
        self.last_result = result
        return result


def apply_decision_to_paper(
    decision: Dict[str, Any],
    lab_open: Callable,
    lab_close: Callable,
    account: Dict[str, Any],
    max_notional: float = 250.0,
) -> Dict[str, Any]:
    side = decision.get("side", "hold")
    pair = decision.get("pair_or_token")
    size = min(max_notional, max(0.0, _safe_float(decision.get("size_hint"), max_notional)))

    if side == "hold" or not pair:
        return {
            "action": "hold",
            "reason": "Coordinator chose hold or no instrument named.",
            "executed": [],
        }

    positions = account.get("positions") or []
    held = {p.get("pair") for p in positions if isinstance(p, dict)}

    try:
        if side in ("buy", "sell"):
            if pair in held:
                return {
                    "action": "abstain",
                    "reason": f"{pair} already has an open position.",
                    "executed": [],
                }
            result = lab_open(pair, side, size)
            return {
                "action": side,
                "pair": pair,
                "notional": size,
                "executed": [result],
            }
        if side == "reduce":
            for p in positions:
                if p.get("pair") == pair:
                    result = lab_close(p.get("id"))
                    return {
                        "action": "reduce",
                        "pair": pair,
                        "executed": [result],
                    }
            return {
                "action": "abstain",
                "reason": f"No open position found for {pair}.",
                "executed": [],
            }
    except Exception as exc:
        return {
            "action": "rejected",
            "reason": str(exc)[:300],
            "executed": [],
        }

    return {"action": "hold", "reason": "Unhandled decision path.", "executed": []}


def build_meme_context(
    candidates: List[Dict],
    trader_status: Dict[str, Any],
    extra: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Compact context for Solana meme-coin candidates (paper only)."""
    cleaned = []
    for c in (candidates or [])[:15]:
        if not isinstance(c, dict):
            continue
        cleaned.append({
            "name": str(c.get("name") or "")[:80],
            "symbol": str(c.get("symbol") or "")[:40],
            "token_address": str(c.get("token_address") or "")[:64],
            "score": _safe_float(c.get("score")),
            "liquidity_usd": _safe_float(c.get("liquidity_usd")),
            "volume_24h_usd": _safe_float(c.get("volume_24h_usd")),
            "price_usd": _safe_float(c.get("price_usd") or c.get("price")),
            "price_change_1h_pct": _safe_float(c.get("price_change_1h_pct")),
            "buy_ratio": _safe_float(c.get("buy_ratio")),
            "txns_24h": c.get("txns_24h") or c.get("transactions_24h"),
            "decision": str(c.get("decision") or "")[:20],
            "rejection_reasons": (c.get("rejection_reasons") or [])[:6],
            "pair_age_minutes": _safe_float(c.get("pair_age_minutes")),
        })
    status = trader_status or {}
    ctx = {
        "mode": "paper_only_solana_meme",
        "note": (
            "No wallet, no swaps, no live execution. Safety checks and "
            "deterministic entry gates remain the final authority."
        ),
        "candidates": cleaned,
        "portfolio": {
            "cash": _safe_float(status.get("cash")),
            "equity": _safe_float(status.get("equity")),
            "open_positions": status.get("open_positions") or status.get("positions") or [],
            "daily_realized_loss": _safe_float(status.get("daily_realized_loss")),
            "risk_halted": bool(status.get("risk_halted")),
        },
        "entry_gates_reminder": {
            "min_score": status.get("min_score"),
            "min_liquidity_usd": status.get("min_liquidity_usd"),
            "min_volume_24h_usd": status.get("min_volume_24h_usd"),
            "max_positions": status.get("max_positions"),
            "daily_loss_limit": status.get("daily_loss_limit"),
        },
    }
    if extra:
        ctx["extra"] = extra
    return ctx


def deliberate_meme(
    research_layer,
    candidates: List[Dict],
    trader_status: Dict[str, Any],
    max_rounds: int = 1,
) -> Dict[str, Any]:
    """Run the six-agent conversation over meme candidates.

    Returns the full deliberation. Does not place paper trades by itself;
    the caller decides whether to feed the recommendation into MemePaperTrader.
    """
    engine = MultiAgentEngine(research_layer, max_rounds=max_rounds)
    market = {"pairs": {}}
    for c in (candidates or [])[:10]:
        if not isinstance(c, dict):
            continue
        addr = str(c.get("token_address") or c.get("symbol") or "")[:48]
        if not addr:
            continue
        price = _safe_float(c.get("price_usd") or c.get("price"))
        if price <= 0:
            continue
        market["pairs"][addr] = {
            "price": price,
            "observed": time.time(),
            "source": "dexscreener",
            "instrument": "solana_meme",
            "symbol": c.get("symbol"),
            "name": c.get("name"),
            "score": c.get("score"),
            "liquidity_usd": c.get("liquidity_usd"),
            "volume_24h_usd": c.get("volume_24h_usd"),
        }

    extra = build_meme_context(candidates, trader_status)
    account = {
        "equity": _safe_float((trader_status or {}).get("equity")),
        "daily_halted": bool((trader_status or {}).get("risk_halted")),
        "positions": (trader_status or {}).get("open_positions")
        or (trader_status or {}).get("positions")
        or [],
    }
    risk = {
        "max_trade_notional": _safe_float((trader_status or {}).get("position_usd"), 50),
        "max_positions": (trader_status or {}).get("max_positions"),
        "max_daily_loss": _safe_float((trader_status or {}).get("daily_loss_limit"), 50),
    }
    result = engine.deliberate(market, account, risk, {}, account.get("positions") or [], extra=extra)
    result["asset_class"] = "solana_meme"
    result["candidates_considered"] = len(candidates or [])
    return result
