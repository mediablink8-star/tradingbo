"""LLM research layer for OpenRouter integration.

Connects the six-agent engine to OpenRouter's API using your
nvidia/nemotron-3-ultra-550b:free model. This makes the deliberation
layer actually talk to the LLM instead of using scripted responses.

Usage:
    from llm_research import build_research_layer
    research = build_research_layer(get_settings())
    if research.available():
        result = research.run(market, account, risk, history, positions)
"""
from __future__ import annotations

import json
import math
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from config import Settings


class LLMResearchLayer:
    """OpenRouter-backed LLM research layer for the six-agent engine.

    The layer is advisory only — it produces agent conversation reports
    but cannot alter risk limits, execute trades, or approve positions.
    The deterministic risk engine remains the final authority.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._open = urllib.request.urlopen
        self.last_result: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None

    def available(self) -> bool:
        """Check if we have proper credentials to talk to OpenRouter."""
        if not self.settings.llm_api_key:
            self.last_error = "LLM_API_KEY not configured"
            return False
        if not self.settings.llm_model:
            self.last_error = "LLM_MODEL not configured"
            return False
        if not self.settings.llm_base_url:
            self.last_error = "LLM_BASE_URL not configured (use https://openrouter.ai/api/v1)"
            return False
        if "openrouter.ai" not in self.settings.llm_base_url:
            self.last_error = "LLM_BASE_URL must be an OpenRouter endpoint"
            return False
        return True

    def _build_prompt(self) -> str:
        """Build the system prompt for the six-agent deliberation."""
        return (
            "You are a six-agent research committee for a paper trading system.\n\n"
            "Your job is to simulate the six agents and produce their analysis "
            "based ONLY on the market data provided. Return results for each agent.\n\n"
            "Agents:\n"
            "1. Market Observer — describe prices, liquidity, data quality\n"
            "2. Technical Analyst — read momentum/structure from the data\n"
            "3. Macro/Narrative Analyst — flag regime risk from price patterns\n"
            "4. Strategy Proposer — propose testable paper action or HOLD\n"
            "5. Risk Critic — attack the proposal, flag weak edges\n"
            "6. Portfolio Coordinator — final decision under risk limits\n\n"
            "Return ONLY a JSON object with keys:\n"
            "  market_observer, technical_analyst, macro_analyst, "
            "strategy_proposer, risk_critic, coordinator\n\n"
            "Each value should be an object with:\n"
            "  summary: string (what the agent said)\n"
            "  concerns: array of strings (concerns or weaknesses)\n\n"
            "Keep each summary under 300 characters.\n"
        )

    def _call(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Call OpenRouter API with the six-agent prompt."""
        if not self.available():
            raise RuntimeError(self.last_error or "LLM layer not available")

        # Build the chat completion request
        messages = [
            {"role": "system", "content": self._build_prompt()},
            {"role": "user", "content": "Market context:\n" + json.dumps(context, default=str, indent=2)[:8000]}
        ]

        body = {
            "model": self.settings.llm_model,
            "messages": messages,
            "max_tokens": 1400,
            "temperature": 0.2,
            "top_p": 0.95,
        }

        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.settings.llm_api_key,
            "HTTP-Referer": "https://github.com/mediablink8-star/tradingbo",
            "X-Title": "Ember Trading Lab - Paper Agent",
        }

        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers
        )

        try:
            with self._open(req, timeout=60) as response:
                raw = json.loads(response.read(4_000_000))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"OpenRouter returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenRouter unreachable: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenRouter returned non-JSON response") from exc

        # Extract text from chat completion
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")

        text = ""
        if isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            text = msg.get("content", "")

        if not text or not text.strip():
            raise RuntimeError("OpenRouter returned empty response")

        # Parse JSON from the response
        try:
            # Handle markdown-wrapped JSON
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("```")
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find the first JSON object
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
                                return json.loads(cleaned[start:i + 1])
                            except json.JSONDecodeError:
                                start = -1
            raise RuntimeError("Could not parse JSON from LLM response")

    def run(
        self,
        market: Dict[str, Any],
        account: Dict[str, Any],
        risk: Dict[str, Any],
        history: Dict[str, List],
        positions: List[Dict],
    ) -> Dict[str, Any]:
        """Run the six-agent advisory analysis. Returns records, never raises."""
        if not self.available():
            return {
                "ok": False,
                "reason": self.last_error or "LLM layer not configured",
                "stages": [],
            }

        # Build context comparable to multi_agent.py expectations
        context = {
            "observed_pairs": {},
            "account": {
                "equity": float(account.get("equity", 0)) if isinstance(account, dict) else 0,
                "exposure": float(account.get("exposure", 0)) if isinstance(account, dict) else 0,
                "daily_halted": bool(account.get("daily_halted", False)) if isinstance(account, dict) else False,
            },
            "risk_limits": {
                "max_trade_notional": float(risk.get("max_trade_notional", 0)) if isinstance(risk, dict) else 0,
                "max_exposure": float(risk.get("max_exposure", 0)) if isinstance(risk, dict) else 0,
                "max_positions": risk.get("max_positions") if isinstance(risk, dict) else None,
                "max_daily_loss": float(risk.get("max_daily_loss", 0)) if isinstance(risk, dict) else 0,
            },
            "pairs": positions,
        }

        # Add market data
        pairs = market.get("pairs", {}) if isinstance(market, dict) else {}
        for pair, row in pairs.items():
            if isinstance(row, dict):
                price = float(row.get("price", 0))
                if price > 0:
                    observed = float(row.get("observed", 0))
                    context["observed_pairs"][pair] = {
                        "last": price,
                        "bid": float(row.get("bid", price)),
                        "ask": float(row.get("ask", price)),
                        "source": str(row.get("source", ""))[:80],
                        "quote_age_seconds": round(time.time() - observed, 1) if observed else None,
                        "instrument": str(row.get("instrument", "fx")),
                    }

        try:
            result = self._call(self._build_prompt(), context)
            # Normalize into stages format
            stages = []
            agent_map = {
                "market_observer": "Market Observer",
                "technical_analyst": "Technical Analyst",
                "macro_analyst": "Macro/Narrative Analyst",
                "strategy_proposer": "Strategy Proposer",
                "risk_critic": "Risk Critic",
                "coordinator": "Portfolio Coordinator",
            }
            for key, name in agent_map.items():
                agent_result = result.get(key, {})
                if agent_result:
                    stages.append({
                        "stage": key,
                        "agent": name,
                        "ok": True,
                        "text": str(agent_result.get("summary", ""))[:4000],
                        "concerns": [str(c)[:400] for c in agent_result.get("concerns", [])[:6]],
                        "advisory": True,
                        "affects_execution": False,
                    })

            self.last_result = {
                "ok": True,
                "model": self.settings.llm_model,
                "provider": "openrouter",
                "advisory_only": True,
                "stages": stages,
                "final_decision": self._extract_coordinator_decision(result.get("coordinator", {}), context),
            }
            return self.last_result

        except Exception as exc:
            self.last_error = str(exc)
            return {
                "ok": False,
                "reason": self.last_error,
                "stages": [],
            }

    def _extract_coordinator_decision(self, coord_result: dict, context: dict) -> dict:
        """Extract the final decision from the coordinator's output."""
        summary = str(coord_result.get("summary", "")).lower()
        decision = "hold"
        pair = None
        side = "hold"

        # Parse coordinator's recommendation from summary text
        for instrument_pair in context.get("observed_pairs", {}):
            if instrument_pair.lower() in summary:
                pair = instrument_pair
                break

        if "buy" in summary and pair:
            decision = "buy"
            side = "buy"
        elif "sell" in summary or "short" in summary:
            decision = "sell"
            side = "sell"
        elif "hold" in summary:
            decision = "hold"
            side = "hold"

        return {
            "decision": decision,
            "side": side,
            "pair_or_token": pair,
            "rationale": str(coord_result.get("summary", ""))[:500],
            "size_hint": context.get("risk_limits", {}).get("max_trade_notional", 0) * 0.5,
            "concerns": [str(c)[:200] for c in coord_result.get("concerns", [])[:4]],
        }


def build_research_layer(settings: Settings) -> Optional[LLMResearchLayer]:
    """Create a research layer from app settings."""
    return LLMResearchLayer(settings)