"""Process-local secret and inference-budget store.

The API key lives only in this process's memory. It is never written to
lab.sqlite, to a log line, to an export, or to browser storage, and a restart
forgets it. The environment variable OPENAI_API_KEY remains a read-only
fallback so a scheduled run can be started without anyone typing a key.

This module also enforces the inference budget. Every model call is counted and
priced against a caller-supplied estimate, and the budget refuses further calls
once the daily ceiling is reached. A silent model loop is a bill nobody
reviewed, so the ceiling is enforced here rather than trusted to discipline.
"""
import os
import threading
import time

ENV_FALLBACK = "OPENAI_API_KEY"
DEFAULT_MAX_CALLS = 40
DEFAULT_MAX_SPEND = 5.0
DEFAULT_COST_PER_CALL = 0.002

# Every supported provider, its default endpoint, its request style and whether
# it needs a credential. "style" selects the wire format in llm_research:
#   responses -> OpenAI /v1/responses
#   chat      -> OpenAI-compatible /chat/completions
#   anthropic -> Anthropic /v1/messages
#   gemini    -> Google generateContent
#   ollama    -> local /api/chat
# A generic "custom" entry lets any OpenAI-compatible gateway be used by
# supplying a base URL, which covers OpenRouter, Groq, Together, Fireworks,
# vLLM, LM Studio, llama.cpp and similar local servers.
PROVIDER_SPECS = {
    "openai": {
        "label": "OpenAI", "style": "responses",
        "base_url": "https://api.openai.com/v1",
        "needs_key": True, "default_model": "gpt-4o-mini",
    },
    "custom": {
        "label": "OpenAI-compatible (OpenRouter, Groq, vLLM, LM Studio…)",
        "style": "chat", "base_url": "", "needs_key": True,
        "default_model": "",
    },
    "anthropic": {
        "label": "Anthropic", "style": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "needs_key": True, "default_model": "claude-sonnet-4-5",
    },
    "google": {
        "label": "Google Gemini", "style": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "needs_key": True, "default_model": "gemini-2.0-flash",
    },
    "ollama": {
        "label": "Ollama (local)", "style": "ollama",
        "base_url": "http://127.0.0.1:11434", "needs_key": False,
        "default_model": "llama3.1",
    },
}


def is_free_model(model):
    """True when a model id is explicitly advertised as free.

    OpenRouter marks these with a ':free' suffix and reports zero prompt and
    completion pricing. Charging the default estimate against a free model
    would report a spend that never happened, so the estimate drops to zero
    instead.
    """
    return str(model or "").strip().lower().endswith(":free")


class BudgetExceeded(RuntimeError):
    """Raised when the daily inference budget cannot fund another call."""


class KeyStore:
    def __init__(self, max_calls=DEFAULT_MAX_CALLS,
                 max_spend=DEFAULT_MAX_SPEND,
                 cost_per_call=DEFAULT_COST_PER_CALL,
                 clock=time.time):
        # Reentrant: store()/forget() publish a status snapshot while already
        # holding the lock, so a plain Lock would self-deadlock.
        self._lock = threading.RLock()
        self._clock = clock
        self._key = None
        self._key_source = None
        self._model = None
        self._provider = "openai"
        self._base_url = ""
        # Ask the provider to enforce JSON output where the wire format allows
        # it. Structured-mode support varies across gateways, so this is
        # user-controlled rather than forced.
        self._json_mode = True
        self._max_calls = int(max_calls)
        self._max_spend = float(max_spend)
        self._cost_per_call = float(cost_per_call)
        self._day = self._day_key()
        self._calls = 0
        self._spent = 0.0
        self._log = []

    # ── secret handling ────────────────────────────────────────────
    def store(self, key, model=None, provider=None, base_url=None):
        """Keep an entered key in memory only. Blank input clears it."""
        if key is None:
            raise ValueError("A key value is required.")
        key = str(key).strip()
        with self._lock:
            if provider is not None:
                self._provider = str(provider).strip() or self._provider
            if base_url is not None:
                self._base_url = str(base_url).strip() or self._base_url
            if not key:
                self._key = None
                self._key_source = None
                if model:
                    self._model = str(model).strip()
                return self.status()
            self._key = key
            self._key_source = "entered in the dashboard"
            if model:
                self._model = str(model).strip()
            return self.status()

    def forget(self):
        with self._lock:
            had = self._key is not None
            self._key = None
            self._key_source = None
            return {"ok": True, "cleared": had, **self.status()}

    @property
    def model(self):
        return self._model

    @property
    def provider(self):
        return self._provider

    @property
    def base_url(self):
        return self._base_url

    def set_json_mode(self, enabled):
        with self._lock:
            self._json_mode = bool(enabled)
        return self._json_mode

    @property
    def json_mode(self):
        return self._json_mode

    def requires_key(self, provider=None):
        """Local endpoints need no credential."""
        return PROVIDER_SPECS.get(provider or self._provider, {}).get(
            "needs_key", True)

    def set_model(self, model):
        model = str(model or "").strip()
        if not model:
            raise ValueError("An exact model id is required.")
        with self._lock:
            self._model = model
        return model

    def resolve_key(self):
        """Entered key first, then the environment fallback. Never logged."""
        with self._lock:
            if self._key:
                return self._key, self._key_source
        if not self.requires_key():
            return None, "local endpoint, no credential needed"
        env = os.environ.get(ENV_FALLBACK)
        if env and env.strip():
            return env.strip(), "environment fallback"
        return None, None

    def has_key(self):
        if not self.requires_key():
            return True
        key, _ = self.resolve_key()
        return bool(key)

    # ── budget ────────────────────────────────────────────────────
    def _day_key(self):
        return time.strftime("%Y-%m-%d", time.gmtime(self._clock()))

    def _roll_day(self):
        today = self._day_key()
        if today != self._day:
            self._day = today
            self._calls = 0
            self._spent = 0.0

    def budget_remaining(self):
        with self._lock:
            self._roll_day()
            free = is_free_model(self._model)
            return {
                "day": self._day,
                "calls": self._calls,
                "max_calls": self._max_calls,
                "spent_usd": round(self._spent, 6),
                "max_spend_usd": round(self._max_spend, 6),
                "cost_per_call_usd": 0.0 if free else self._cost_per_call,
                "free_model": free,
                "calls_left": max(0, self._max_calls - self._calls),
                "spend_left_usd": round(max(0.0, self._max_spend - self._spent), 6),
                "exhausted": self._calls >= self._max_calls
                             or self._spent >= self._max_spend,
            }

    def _charge(self, purpose):
        """Reserve budget for one call. Raises rather than overspending."""
        with self._lock:
            self._roll_day()
            cost = 0.0 if is_free_model(self._model) else self._cost_per_call
            if self._calls >= self._max_calls:
                raise BudgetExceeded(
                    "Daily model-call allowance of %d is exhausted."
                    % self._max_calls
                )
            if self._spent + cost > self._max_spend:
                raise BudgetExceeded(
                    "Daily model spend cap of $%.2f would be exceeded."
                    % self._max_spend
                )
            self._calls += 1
            self._spent += cost
            self._log.append({
                "t": self._clock(), "purpose": purpose,
                "cost_usd": cost, "free_model": cost == 0.0,
            })
            if len(self._log) > 500:
                del self._log[:-500]

    # ── status ────────────────────────────────────────────────────
    def status(self):
        key, source = self.resolve_key()
        with self._lock:
            model = self._model
            provider = self._provider
            base_url = self._base_url
        spec = PROVIDER_SPECS.get(provider, PROVIDER_SPECS["openai"])
        return {
            "connected": bool(key),
            "needs_key": spec["needs_key"],
            "source": source if key else None,
            "provider": provider,
            "provider_label": spec["label"],
            "style": spec["style"],
            "base_url": base_url or spec["base_url"],
            "model": model,
            "free_model": is_free_model(model),
            "json_mode": self._json_mode,
            "budget": self.budget_remaining(),
        }

    def log_tail(self, limit=20):
        with self._lock:
            return [dict(row) for row in self._log[-limit:]]