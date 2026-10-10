"""AI research layer for the forex paper lab.

Scope, deliberately narrow: the model reads observed prices and writes analysis
and candidate strategies. It has no execution tool, cannot size an entry, and
cannot alter a risk limit. Every candidate it returns is a hypothesis to be
tested, not an instruction to trade. Entry, sizing, stops and the daily-loss
breaker remain deterministic in forex_agents and forex_risk.

Providers are pluggable. OpenAI, any OpenAI-compatible gateway (OpenRouter,
Groq, Together, Fireworks, vLLM, LM Studio, llama.cpp), Anthropic, Google
Gemini and a local Ollama server are supported. Without a usable configuration
every stage degrades to an explicit unavailable state; placeholder prose is
never presented as if a model had produced it.
"""
import json
import math
import time
import urllib.error
import urllib.request

from key_store import BudgetExceeded, PROVIDER_SPECS

TIMEOUT = 60
MAX_TOKENS = 1400
MAX_CHARS = 4000

ALLOWED_FIELDS = {
    "research", "macro_view", "strategy", "critique", "concerns",
}


class ModelError(RuntimeError):
    """A model call failed, was refused, or returned an unusable shape."""


# ── provider plumbing ─────────────────────────────────────────
def _spec(store):
    provider = getattr(store, "provider", None) or "openai"
    spec = PROVIDER_SPECS.get(provider)
    if spec is None:
        raise ModelError("Unknown provider '%s'. Choose one of: %s"
                         % (provider, ", ".join(sorted(PROVIDER_SPECS))))
    return provider, spec


def _endpoint_and_headers(store, spec):
    base = (getattr(store, "base_url", "") or spec["base_url"]).rstrip("/")
    key, _ = store.resolve_key()
    style = spec["style"]

    if style == "responses":
        return base + "/responses", {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (key or ""),
        }
    if style == "chat":
        if not base:
            raise ModelError(
                "This provider needs a base URL, for example "
                "https://openrouter.ai/api/v1 or http://127.0.0.1:1234/v1")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        return base + "/chat/completions", headers
    if style == "anthropic":
        return base + "/messages", {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": key or "",
        }
    if style == "gemini":
        if not key:
            raise ModelError("Gemini requires an API key.")
        return (base + "/models/" + store.model + ":generateContent?key=" + key,
                {"Content-Type": "application/json"})
    if style == "ollama":
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        return base + "/api/chat", headers
    raise ModelError("Unsupported provider style '%s'." % style)


def _build_body(style, model, prompt, json_mode=True):
    if style == "responses":
        return {"model": model, "input": prompt,
                "max_output_tokens": MAX_TOKENS, "store": False}
    if style == "chat":
        body = {"model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": MAX_TOKENS, "temperature": 0.2}
        # Structured output is widely supported on OpenAI-compatible gateways
        # and greatly reduces prose-instead-of-JSON failures. Gateways that lack
        # it reject the parameter, so it stays user-controlled.
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body
    if style == "anthropic":
        return {"model": model, "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}]}
    if style == "gemini":
        return {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": MAX_TOKENS,
                                     "temperature": 0.2}}
    if style == "ollama":
        return {"model": model, "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.2, "num_predict": MAX_TOKENS}}
    raise ModelError("Unsupported provider style '%s'." % style)


def _extract_text(style, raw):
    """Pull assistant text out of each provider's response shape."""
    if style == "responses":
        direct = raw.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        parts = []
        for item in raw.get("output") or []:
            if not isinstance(item, dict):
                continue
            for chunk in item.get("content") or []:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(chunk["text"])
        return "".join(parts)
    if style == "chat":
        choices = raw.get("choices") or []
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content")
            if isinstance(content, str):
                return content
    if style == "anthropic":
        return "".join(b.get("text", "") for b in (raw.get("content") or [])
                       if isinstance(b, dict))
    if style == "gemini":
        candidates = raw.get("candidates") or []
        if candidates and isinstance(candidates[0], dict):
            content = candidates[0].get("content") or {}
            return "".join(p.get("text", "") for p in (content.get("parts") or [])
                           if isinstance(p, dict))
    if style == "ollama":
        content = (raw.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
    return ""


# ── context ──────────────────────────────────────────────────
def _finite(value, default=0.0):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def build_context(market, account, risk, history, positions):
    """Compact, honest context built only from observed values."""
    pairs = {}
    for pair, row in (market.get("pairs") or {}).items():
        if not isinstance(row, dict):
            continue
        price = _finite(row.get("price"), 0.0)
        if price <= 0:
            continue
        observed = _finite(row.get("observed"), 0.0)
        series = [_finite(p, 0.0) for _, p in (history.get(pair) or [])
                  if _finite(p, 0.0) > 0]
        pairs[pair] = {
            "last": price,
            "bid": _finite(row.get("bid"), price),
            "ask": _finite(row.get("ask"), price),
            "source": str(row.get("source") or "")[:80],
            "quote_age_seconds": round(time.time() - observed, 1) if observed else None,
            "recent_closes": series[-12:],
            "instrument": str(row.get("instrument") or "fx"),
        }
    return {
        "observed_pairs": pairs,
        "account": {
            "equity": _finite((account or {}).get("equity")),
            "exposure": _finite((account or {}).get("exposure")),
            "realized_pnl": _finite((account or {}).get("realized_pnl")),
            "unrealized_pnl": _finite((account or {}).get("unrealized_pnl")),
            "daily_halted": bool((account or {}).get("daily_halted")),
        },
        "risk_limits": {
            "max_trade_notional": _finite((risk or {}).get("max_trade_notional")),
            "max_exposure": _finite((risk or {}).get("max_exposure")),
            "max_positions": (risk or {}).get("max_positions"),
            "max_daily_loss": _finite((risk or {}).get("max_daily_loss")),
            "stop_loss_pct": _finite((risk or {}).get("stop_loss_pct")),
            "take_profit_pct": _finite((risk or {}).get("take_profit_pct")),
        },
        "open_positions": [
            {"pair": p.get("pair"), "side": p.get("side"),
             "notional": _finite(p.get("notional")),
             "unrealized_pnl": _finite(p.get("unrealized_pnl"))}
            for p in (positions or []) if isinstance(p, dict)
        ],
    }


# ── prompts ──────────────────────────────────────────────────
RESEARCH_PROMPT = """You are the research desk of a paper-trading study. You may
only use the observed prices supplied below. You cannot browse, you cannot see
an order book, and you cannot know any future price.

Write for a competent reader who will check your reasoning. Be specific about
what the data does and does not support. If the evidence is thin, say so plainly
rather than manufacturing a view.

Return ONLY a JSON object with these keys:
  "research": string, describing the observed state of each pair and what it
               implies, naming concrete figures from the data.
  "concerns": array of at most 6 short strings, the weaknesses most likely to
              invalidate any conclusion drawn from this data."""

MACRO_PROMPT = """You are the macro desk of a paper-trading study. You are given
observed FX prices only. You do not have a news feed, a central-bank calendar or
a macro database, so you must not assert the current state of the world. Reason
from the price data and label anything else as a hypothesis.

Return ONLY a JSON object with these keys:
  "macro_view": string, a reasoned regime read grounded in the supplied figures,
                 explicitly naming its own assumptions.
  "concerns": array of at most 6 short strings."""

STRATEGY_PROMPT = """You are the strategy desk of a paper-trading study. Propose
testable strategy hypotheses from the observed data.

Hard rules you must respect:
  - Propose hypotheses to be TESTED. You are not instructing a trade and you
    cannot execute anything.
  - Never claim an expected win rate, an expected return, or profitability.
  - State what evidence would falsify each hypothesis.
  - Prefer abstention over a confident claim on thin data.

Return ONLY a JSON object with these keys:
  "strategy": string, describing 1-3 concrete, testable hypotheses with their
               entry logic, the condition that would invalidate them, and the
               data sample needed before the idea deserves capital.
  "concerns": array of at most 6 short strings."""

CRITIQUE_PROMPT = """You are the independent risk critic of a paper-trading
study, structurally separate from the research and strategy desks. Your job is
to attack, not to agree. Assume the proposal is wrong until the evidence forces
otherwise. A recommendation to do nothing is a valid and often correct answer.

Return ONLY a JSON object with these keys:
  "critique": string, the strongest case against the proposed strategy, and the
               single biggest way it could fail.
  "concerns": array of at most 6 short strings."""

# The field must match the key each prompt actually requests, otherwise that
# stage fails validation on every run.
STAGES = (
    ("research", "Market researcher", RESEARCH_PROMPT),
    ("macro_view", "Macro analyst", MACRO_PROMPT),
    ("strategy", "Strategy analyst", STRATEGY_PROMPT),
    ("critique", "Risk critic", CRITIQUE_PROMPT),
)


def _validate(payload, field):
    if not isinstance(payload, dict):
        raise ModelError("Model response was not a JSON object.")
    text = payload.get(field)
    if not isinstance(text, str) or not text.strip():
        raise ModelError("Model response is missing '%s'." % field)
    concerns = payload.get("concerns", [])
    if not isinstance(concerns, list):
        concerns = []
    clean = [c.strip()[:240] for c in concerns[:6]
             if isinstance(c, str) and c.strip()]
    return {"text": text.strip()[:MAX_CHARS], "concerns": clean}


class ResearchLayer:
    def __init__(self, store, opener=None):
        self.store = store
        self._open = opener or urllib.request.urlopen
        self.last_result = None
        self.last_error = None

    def available(self):
        _provider, spec = _spec(self.store)
        if not self.store.model:
            return False
        if spec["needs_key"] and not self.store.resolve_key()[0]:
            return False
        return True

    def _call(self, prompt, context):
        _provider, spec = _spec(self.store)
        model = self.store.model
        if not model:
            raise ModelError("No model id is configured.")
        url, headers = _endpoint_and_headers(self.store, spec)
        body = _build_body(
            spec["style"], model,
            prompt + "\n\nObserved data (JSON):\n"
            + json.dumps(context, default=str)[:12000],
            json_mode=getattr(self.store, "json_mode", True))
        # Charged before the request, so a failing call still costs.
        self.store._charge("fx-research")
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers)
        try:
            with self._open(req, timeout=TIMEOUT) as response:
                raw = json.loads(response.read(4_000_000))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                err = json.loads(exc.read(4000)).get("error")
                detail = err.get("message") if isinstance(err, dict) else str(err)
            except Exception:
                pass
            raise ModelError("Provider returned HTTP %s%s"
                             % (exc.code,
                                (": " + str(detail)[:160]) if detail else "")
                             ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ModelError("Provider unreachable: %s" % exc) from exc
        except json.JSONDecodeError as exc:
            raise ModelError("Provider returned a non-JSON response.") from exc
        text = _extract_text(spec["style"], raw)
        if not isinstance(text, str) or not text.strip():
            raise ModelError("Provider returned no usable text.")
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ModelError("Model output was not valid JSON.") from exc

    def run(self, market, account, risk, history, positions):
        """Run the advisory stages. Returns a record; never raises."""
        self.last_error = None
        if not self.available():
            self.last_result = {
                "ok": False,
                "reason": "No usable model configuration. The deterministic "
                          "pipeline continues unchanged.",
                "stages": [],
                "budget": self.store.budget_remaining(),
            }
            return self.last_result
        context = build_context(market, account, risk, history, positions)
        stages = []
        for field, label, prompt in STAGES:
            try:
                parsed = _validate(self._call(prompt, context), field)
                stages.append({
                    "stage": field, "agent": label, "ok": True,
                    "text": parsed["text"], "concerns": parsed["concerns"],
                    "advisory": True, "affects_execution": False,
                })
            except BudgetExceeded as exc:
                self.last_error = str(exc)
                stages.append({
                    "stage": field, "agent": label, "ok": False, "text": "",
                    "concerns": ["Budget exhausted: " + str(exc)],
                    "advisory": True, "affects_execution": False,
                })
                break
            except ModelError as exc:
                stages.append({
                    "stage": field, "agent": label, "ok": False, "text": "",
                    "concerns": [str(exc)],
                    "advisory": True, "affects_execution": False,
                })
        self.last_result = {
            "ok": any(s["ok"] for s in stages),
            "model": self.store.model,
            "provider": self.store.provider,
            "advisory_only": True,
            "stages": stages,
            "budget": self.store.budget_remaining(),
        }
        return self.last_result


def verify_connection(store, opener=None):
    """List account models where supported. GET-only, so it costs nothing."""
    provider, spec = _spec(store)
    base = (getattr(store, "base_url", "") or spec["base_url"]).rstrip("/")
    key, _ = store.resolve_key()
    open_ = opener or urllib.request.urlopen
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    if spec["style"] == "anthropic":
        url = base + "/models"
        headers = {"x-api-key": key or "", "anthropic-version": "2023-06-01"}
    elif spec["style"] == "gemini":
        if not key:
            raise ModelError("Gemini requires an API key.")
        url = base + "/models?key=" + key
    elif spec["style"] == "ollama":
        url = base + "/api/tags"
    elif spec["style"] == "chat" and not base:
        raise ModelError("Set a base URL before checking models.")
    else:
        url = base + "/models"
    req = urllib.request.Request(url, headers=headers)
    try:
        with open_(req, timeout=25) as response:
            raw = json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        raise ModelError("Provider returned HTTP %s." % exc.code) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ModelError("Provider unreachable: %s" % exc) from exc
    ids = []
    for row in (raw.get("data") or raw.get("models") or []):
        if isinstance(row, str):
            ids.append(row)
        elif isinstance(row, dict):
            ident = row.get("id") or row.get("name") or row.get("model")
            if isinstance(ident, str):
                ids.append(ident)
    return {"ok": True, "provider": provider, "count": len(ids),
            "models": sorted(ids)[:200],
            "note": "Listing a model does not prove this app can use it."}